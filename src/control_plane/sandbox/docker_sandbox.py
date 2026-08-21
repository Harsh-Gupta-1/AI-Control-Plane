"""Docker-backed implementation of the Sandbox interface."""

import logging
import uuid
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container

from control_plane.sandbox.contracts import (
    Sandbox,
    SandboxError,
    SandboxResult,
    SandboxState,
)

logger = logging.getLogger(__name__)

# Standard isolated workspace paths required by the architecture
WORKSPACE_PATHS = [
    "/workspace",
    "/downloads",
    "/input",
    "/output",
    "/temp",
]


class DockerSandbox(Sandbox):
    """A disposable Docker container providing an isolated computer environment."""

    def __init__(self, image: str = "control-plane-sandbox:latest") -> None:
        """Initialize the Docker sandbox.

        This creates the container but does not start it.
        """
        self._id = str(uuid.uuid4())
        self._container_name = f"sandbox-{self._id}"

        try:
            self._client = docker.from_env()
        except DockerException as e:
            raise SandboxError(f"Failed to initialize Docker client: {e}") from e

        self._container: Container | None = None
        
        try:
            try:
                self._client.images.get(image)
            except docker.errors.ImageNotFound:
                logger.info(f"Pulling image {image}...")
                self._client.images.pull(image)
                
            # We use tail -f /dev/null as an idle process to keep the container running
            # when started.
            self._container = self._client.containers.create(
                image,
                command=["tail", "-f", "/dev/null"],
                name=self._container_name,
                detach=True,
                network_mode="bridge",
                # Security: no bind mounts to the host!
                volumes=None,
                # Create the standard isolated workspace directories
                working_dir="/workspace",
            )
            
            # Since the container is only created, we cannot execute 'mkdir' yet.
            # We will create the directories immediately after it starts.
        except DockerException as e:
            raise SandboxError(f"Failed to create Docker container: {e}") from e

    @property
    def id(self) -> str:
        return self._id

    def _get_container(self) -> Container:
        if self._container is None:
            raise SandboxError(f"Sandbox {self._id} is already destroyed.")
        return self._container

    def start(self) -> None:
        container = self._get_container()
        try:
            container.start()
            
            # Setup isolated directories
            mkdir_command = ["mkdir", "-p"] + WORKSPACE_PATHS
            exit_code, output = container.exec_run(mkdir_command)
            if exit_code != 0:
                output_str = output.decode("utf-8") if isinstance(output, bytes) else str(output)
                raise SandboxError(f"Failed to initialize workspace paths: {output_str}")
                
        except DockerException as e:
            raise SandboxError(f"Failed to start sandbox {self._id}: {e}") from e

    def stop(self) -> None:
        container = self._get_container()
        try:
            container.stop(timeout=5)
        except APIError as e:
            # Ignore errors if it was already stopped
            if "already stopped" not in str(e).lower() and e.status_code != 304:
                raise SandboxError(f"Failed to stop sandbox {self._id}: {e}") from e
        except DockerException as e:
            raise SandboxError(f"Failed to stop sandbox {self._id}: {e}") from e

    def destroy(self) -> None:
        if self._container is None:
            return
            
        try:
            # Remove container (forces removal even if running)
            self._container.remove(force=True)
            self._container = None
        except NotFound:
            # Already removed
            self._container = None
        except DockerException as e:
            raise SandboxError(f"Failed to destroy sandbox {self._id}: {e}") from e
        finally:
            self._client.close()

    def inspect(self) -> SandboxState:
        if self._container is None:
            return SandboxState.DESTROYED
            
        try:
            # Reload attributes from Docker daemon
            self._container.reload()
            status = self._container.status
            if status == "running":
                return SandboxState.RUNNING
            elif status == "created":
                return SandboxState.CREATED
            elif status == "exited" or status == "dead":
                return SandboxState.STOPPED
            else:
                # Other statuses like 'restarting', 'paused' mapping to RUNNING for simplicity
                return SandboxState.RUNNING
        except NotFound:
            self._container = None
            return SandboxState.DESTROYED
        except DockerException as e:
            raise SandboxError(f"Failed to inspect sandbox {self._id}: {e}") from e

    def execute(self, command: list[str], timeout_seconds: int, max_output_bytes: int = 1048576) -> SandboxResult:
        container = self._get_container()
        state = self.inspect()
        if state != SandboxState.RUNNING:
            raise SandboxError(f"Cannot execute command; sandbox is in state {state.value}")

        try:
            # Docker python SDK doesn't natively support timeouts on exec_run.
            # We can use the 'timeout' linux command inside the container to enforce it.
            timeout_cmd = ["timeout", str(timeout_seconds)] + command
            
            exec_id = self._client.api.exec_create(
                container.id,
                timeout_cmd,
                tty=False
            )
            
            output_stream = self._client.api.exec_start(
                exec_id['Id'], 
                stream=True, 
                demux=True
            )
            
            stdout_bytes = bytearray()
            stderr_bytes = bytearray()
            output_truncated = False
            
            for chunk in output_stream:
                stdout_chunk, stderr_chunk = chunk
                if stdout_chunk:
                    stdout_bytes.extend(stdout_chunk)
                if stderr_chunk:
                    stderr_bytes.extend(stderr_chunk)
                    
                if len(stdout_bytes) + len(stderr_bytes) > max_output_bytes:
                    output_truncated = True
                    output_stream.close()
                    break

            exec_info = self._client.api.exec_inspect(exec_id['Id'])
            exit_code = exec_info.get('ExitCode')
            
            if exit_code is None:
                # If we truncated and broke early, the process may still be running
                # We can't know the final exit code, so we use a fallback.
                exit_code = -1

            timed_out = (exit_code == 124) # standard exit code for 'timeout' command

            # Convert to strings, truncating to exact max_output_bytes if we exceeded it
            # just in case the last chunk was very large
            if output_truncated:
                stdout_bytes = stdout_bytes[:max_output_bytes]
                stderr_bytes = stderr_bytes[:max_output_bytes]

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                timed_out=timed_out,
                output_truncated=output_truncated,
            )

        except DockerException as e:
            raise SandboxError(f"Execution failed in sandbox {self._id}: {e}") from e
