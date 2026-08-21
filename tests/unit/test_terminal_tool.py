import pytest
from control_plane.sandbox.contracts import SandboxResult
from control_plane.domain import ToolRequest, ToolResultStatus
from control_plane.tools.terminal import ExecuteCommandTool
from tests.unit.fake_sandbox import FakeSandbox

def test_execute_command_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout="hello\n",
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = ExecuteCommandTool(sandbox)
    request = ToolRequest(
        tool_name="execute_command",
        capability="terminal.execute",
        arguments={"command": "echo hello", "working_directory": "/workspace"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["exit_code"] == 0
    assert result.output["stdout"] == "hello\n"
    assert result.output["stderr"] == ""
    assert result.output["timed_out"] is False
    assert result.output["output_truncated"] is False

def test_execute_command_failure():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=1,
            stdout="",
            stderr="command not found\n",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = ExecuteCommandTool(sandbox)
    request = ToolRequest(
        tool_name="execute_command",
        capability="terminal.execute",
        arguments={"command": "invalidcmd", "working_directory": "/workspace"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.FAILURE
    assert result.error.code == "command_failed"
    assert result.error.message == "command not found"

def test_execute_command_timeout():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=124,
            stdout="",
            stderr="",
            timed_out=True,
            output_truncated=False,
        )
    ])
    tool = ExecuteCommandTool(sandbox)
    request = ToolRequest(
        tool_name="execute_command",
        capability="terminal.execute",
        arguments={"command": "sleep 100", "working_directory": "/workspace"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.FAILURE
    assert result.error.code == "timeout"
    assert result.error.message == "Command execution timed out"

def test_execute_command_invalid_wd():
    sandbox = FakeSandbox([])
    tool = ExecuteCommandTool(sandbox)
    request = ToolRequest(
        tool_name="execute_command",
        capability="terminal.execute",
        arguments={"command": "ls", "working_directory": "../../etc"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.INVALID_REQUEST
    assert result.error.code == "invalid_path"
