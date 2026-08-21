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

    def __init__(self, image: str = "ubuntu:22.04") -> None:
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

    def execute(self, command: list[str], timeout_seconds: int) -> SandboxResult:
        container = self._get_container()
        state = self.inspect()
        if state != SandboxState.RUNNING:
            raise SandboxError(f"Cannot execute command; sandbox is in state {state.value}")

        try:
            # Docker python SDK doesn't natively support timeouts on exec_run.
            # We can use the 'timeout' linux command inside the container to enforce it.
            # If the base image doesn't have 'timeout', this may fail, but coreutils is standard.
            timeout_cmd = ["timeout", str(timeout_seconds)] + command
            
            # Bounded output reading is achieved by passing demux=True, but we must
            # also be careful not to read infinite streams. docker SDK buffers it.
            # For this simple primitive, we use the synchronous exec_run.
            exit_code, output = container.exec_run(
                timeout_cmd,
                demux=True,
            )
            
            stdout_bytes, stderr_bytes = output if output else (b"", b"")
            stdout_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            timed_out = (exit_code == 124) # standard exit code for 'timeout' command

            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                timed_out=timed_out,
            )

        except DockerException as e:
            raise SandboxError(f"Execution failed in sandbox {self._id}: {e}") from e
