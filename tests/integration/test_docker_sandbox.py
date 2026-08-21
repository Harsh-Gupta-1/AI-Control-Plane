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
    
    # Inspect the underlying Docker container configuration
    container = sandbox._get_container()
    container.reload()
    binds = container.attrs["HostConfig"]["Binds"]
    
    # Assert no host directories are bound
    assert binds is None or len(binds) == 0, f"Found host bind mounts: {binds}"
    
    # Create a file inside the sandbox
    test_filename = f"test_isolation_{uuid.uuid4().hex}.txt"
    sandbox.execute(["touch", f"/workspace/{test_filename}"], timeout_seconds=5)
    
    # Verify the file does NOT exist on the host machine in the current directory
    # (Since we didn't mount it, it shouldn't, but let's double check)
    assert not os.path.exists(test_filename)
    
    # Verify it DOES exist inside the sandbox
    result = sandbox.execute(["ls", f"/workspace/{test_filename}"], timeout_seconds=5)
    assert result.exit_code == 0


def test_sandbox_execution_success(sandbox: DockerSandbox):
    """Verify basic command execution and output capture."""
    sandbox.start()
    
    result = sandbox.execute(["echo", "hello", "world"], timeout_seconds=5)
    
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello world"
    assert result.stderr == ""
    assert not result.timed_out


def test_sandbox_execution_failure(sandbox: DockerSandbox):
    """Verify that failed commands return the correct exit code and stderr."""
    sandbox.start()
    
    result = sandbox.execute(["ls", "/nonexistent_path"], timeout_seconds=5)
    
    assert result.exit_code != 0
    assert "No such file or directory" in result.stderr
    assert not result.timed_out


def test_sandbox_execution_timeout(sandbox: DockerSandbox):
    """Verify that timeout commands are interrupted and return a timeout status."""
    sandbox.start()
    
    # Run a command that takes 10 seconds, but set timeout to 2
    result = sandbox.execute(["sleep", "10"], timeout_seconds=2)
    
    assert result.exit_code == 124  # standard timeout exit code
    assert result.timed_out


def test_sandbox_invalid_lifecycle_operations(sandbox: DockerSandbox):
    """Verify that invalid operations on destroyed sandboxes raise errors."""
    sandbox.destroy()
    
    with pytest.raises(SandboxError, match="already destroyed"):
        sandbox.start()
        
    with pytest.raises(SandboxError, match="already destroyed"):
        sandbox.execute(["echo", "hi"], timeout_seconds=5)
