import pytest
import docker
from control_plane.sandbox.docker_sandbox import DockerSandbox
from control_plane.domain import ToolRequest, ToolResultStatus
from control_plane.tools.terminal import ExecuteCommandTool

try:
    client = docker.from_env()
    client.ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker is not available")

@pytest.fixture
def sandbox():
    sb = DockerSandbox()
    sb.start()
    yield sb
    sb.stop()
    sb.destroy()

def test_terminal_echo_integration(sandbox):
    tool = ExecuteCommandTool(sandbox)
    req = ToolRequest(
        tool_name="execute_command", capability="terminal.execute",
        arguments={"command": "echo hello integration"}
    )
    res = tool._execute(req)
    assert res.status == ToolResultStatus.SUCCESS
    assert "hello integration" in res.output["stdout"]

def test_terminal_failing_command_integration(sandbox):
    tool = ExecuteCommandTool(sandbox)
    req = ToolRequest(
        tool_name="execute_command", capability="terminal.execute",
        arguments={"command": "ls /nonexistent_dir"}
    )
    res = tool._execute(req)
    assert res.status == ToolResultStatus.FAILURE
    assert "No such file or directory" in res.error.message

def test_terminal_timeout_integration(sandbox):
    tool = ExecuteCommandTool(sandbox)
    req = ToolRequest(
        tool_name="execute_command", capability="terminal.execute",
        arguments={"command": "sleep 5", "timeout_seconds": 1}
    )
    res = tool._execute(req)
    assert res.status == ToolResultStatus.FAILURE
    assert res.error.code == "timeout"

def test_terminal_working_directory_integration(sandbox):
    tool = ExecuteCommandTool(sandbox)
    req = ToolRequest(
        tool_name="execute_command", capability="terminal.execute",
        arguments={"command": "pwd", "working_directory": "/downloads"}
    )
    res = tool._execute(req)
    assert res.status == ToolResultStatus.SUCCESS
    assert "/downloads" in res.output["stdout"]
