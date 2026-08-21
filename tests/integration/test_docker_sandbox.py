"""Integration tests for the Docker sandbox adapter."""

import os
import pytest
import uuid

try:
    import docker
    from docker.errors import DockerException
    
    # Check if Docker is available
    client = docker.from_env()
    client.ping()
    client.close()
    DOCKER_AVAILABLE = True
except (ImportError, DockerException):
    DOCKER_AVAILABLE = False

from control_plane.sandbox.contracts import SandboxState, SandboxError
from control_plane.sandbox.docker_sandbox import DockerSandbox

pytestmark = pytest.mark.skipif(
    not DOCKER_AVAILABLE, 
    reason="Docker is not available or not running."
)


@pytest.fixture
def sandbox():
    """Provides a fresh, unstarted sandbox for each test."""
    # We use a very small alpine image for faster testing if desired,
    # but ubuntu:22.04 is the default. Let's use the default.
    box = DockerSandbox()
    yield box
    box.destroy()


def test_sandbox_lifecycle(sandbox: DockerSandbox):
    """Test the full lifecycle: create -> start -> inspect -> stop -> destroy."""
    # After creation (fixture initialization), state should be CREATED
    assert sandbox.inspect() == SandboxState.CREATED
    assert sandbox.id is not None
    
    # Start it
    sandbox.start()
    assert sandbox.inspect() == SandboxState.RUNNING
    
    # Stop it
    sandbox.stop()
    assert sandbox.inspect() == SandboxState.STOPPED
    
    # Destroy it
    sandbox.destroy()
    assert sandbox.inspect() == SandboxState.DESTROYED


def test_sandbox_workspace_directories(sandbox: DockerSandbox):
    """Verify that the required workspace directories are created inside the sandbox."""
    sandbox.start()
    
    expected_paths = ["/workspace", "/downloads", "/input", "/output", "/temp"]
    
    for path in expected_paths:
        result = sandbox.execute(["test", "-d", path], timeout_seconds=5)
        assert result.exit_code == 0, f"Directory {path} does not exist"


def test_sandbox_isolation(sandbox: DockerSandbox):
    """Prove that no host bind mounts exist and files stay inside the container."""
    sandbox.start()
    
    # 1. Verify no host bind mounts exist at the Docker API level
    container = sandbox._get_container()
    container.reload()
    binds = container.attrs["HostConfig"]["Binds"]
    assert binds is None or len(binds) == 0, f"Found host bind mounts: {binds}"
    
    # 2. Create a file inside the sandbox at /workspace
    test_filename = f"test_isolation_{uuid.uuid4().hex}.txt"
    sandbox.execute(["touch", f"/workspace/{test_filename}"], timeout_seconds=5)
    
    # 3. Verify it DOES exist inside the sandbox
    result = sandbox.execute(["ls", f"/workspace/{test_filename}"], timeout_seconds=5)
    assert result.exit_code == 0
    
    # 4. Prove the host filesystem is not modified
    # We check both the current project directory (in case it was mapped locally)
    # and the host's absolute /workspace equivalent (in case it was mapped by absolute path).
    host_local_path = os.path.join(os.getcwd(), test_filename)
    host_absolute_path = os.path.join(os.path.abspath("/workspace"), test_filename)
    
    assert not os.path.exists(host_local_path), "File leaked to host project directory!"
    assert not os.path.exists(host_absolute_path), "File leaked to host absolute /workspace directory!"


def test_sandbox_execution_success(sandbox: DockerSandbox):
    """Verify basic command execution and output capture."""
    sandbox.start()
    
    result = sandbox.execute(["echo", "hello", "world"], timeout_seconds=5)
    
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello world"
    assert result.stderr == ""
    assert not result.timed_out
    assert not result.output_truncated


def test_sandbox_execution_failure(sandbox: DockerSandbox):
    """Verify that failed commands return the correct exit code and stderr."""
    sandbox.start()
    
    result = sandbox.execute(["ls", "/nonexistent_path"], timeout_seconds=5)
    
    assert result.exit_code != 0
    assert "No such file or directory" in result.stderr
    assert not result.timed_out
    assert not result.output_truncated


def test_sandbox_execution_timeout(sandbox: DockerSandbox):
    """Verify that timeout commands are interrupted and return a timeout status."""
    sandbox.start()
    
    # Run a command that takes 10 seconds, but set timeout to 2
    result = sandbox.execute(["sleep", "10"], timeout_seconds=2)
    
    assert result.exit_code == 124  # standard timeout exit code
    assert result.timed_out
    assert not result.output_truncated


def test_sandbox_execution_truncation(sandbox: DockerSandbox):
    """Verify that output exceeding the max bytes limit is truncated."""
    sandbox.start()
    
    # Generate 10000 bytes of output
    command = ["head", "-c", "10000", "/dev/zero"]
    # Limit to 1000 bytes
    max_bytes = 1000
    
    result = sandbox.execute(command, timeout_seconds=5, max_output_bytes=max_bytes)
    
    assert result.output_truncated is True
    # Due to chunking, exact length might be slightly off if we didn't strict slice, 
    # but we added exact slicing in the adapter!
    assert len(result.stdout) == max_bytes
    # Since we broke the stream early, the command may still run or get killed, 
    # but the output size is strictly bound.
    
    # Test stderr truncation as well
    # Generate large output on stderr
    command_stderr = ["sh", "-c", "head -c 10000 /dev/zero >&2"]
    result_stderr = sandbox.execute(command_stderr, timeout_seconds=5, max_output_bytes=max_bytes)
    
    assert result_stderr.output_truncated is True
    assert len(result_stderr.stderr) == max_bytes


def test_sandbox_invalid_lifecycle_operations(sandbox: DockerSandbox):
    """Verify that invalid operations on destroyed sandboxes raise errors."""
    sandbox.destroy()
    
    with pytest.raises(SandboxError, match="already destroyed"):
        sandbox.start()
        
    with pytest.raises(SandboxError, match="already destroyed"):
        sandbox.execute(["echo", "hi"], timeout_seconds=5)
