import pytest
from control_plane.sandbox.contracts import SandboxResult
from control_plane.domain import ToolRequest, ToolResultStatus
from control_plane.tools.filesystem import ListDirectoryTool, ReadFileTool
from tests.unit.fake_sandbox import FakeSandbox

def test_list_directory_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout="total 12\ndrwxr-xr-x 2 root root 4096 Aug 21 00:00 .\ndrwxr-xr-x 3 root root 4096 Aug 21 00:00 ..\n-rw-r--r-- 1 root root   15 Aug 21 00:00 file.txt\n",
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = ListDirectoryTool(sandbox)
    request = ToolRequest(
        tool_name="list_directory",
        capability="filesystem.read",
        arguments={"path": "/workspace"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.SUCCESS
    assert result.error is None
    entries = result.output["entries"]
    assert len(entries) == 3
    assert entries[0] == {"name": ".", "type": "directory", "size": 4096}
    assert entries[2] == {"name": "file.txt", "type": "file", "size": 15}

def test_list_directory_not_found():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=1,
            stdout="",
            stderr="ls: cannot access '/workspace/missing': No such file or directory\n",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = ListDirectoryTool(sandbox)
    request = ToolRequest(
        tool_name="list_directory",
        capability="filesystem.read",
        arguments={"path": "/workspace/missing"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.FAILURE
    assert result.error is not None
    assert result.error.code == "directory_not_found"

def test_list_directory_invalid_path():
    sandbox = FakeSandbox([])
    tool = ListDirectoryTool(sandbox)
    request = ToolRequest(
        tool_name="list_directory",
        capability="filesystem.read",
        arguments={"path": "../../etc/passwd"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.INVALID_REQUEST
    assert result.error is not None
    assert result.error.code == "invalid_path"

def test_read_file_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout="hello world",
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = ReadFileTool(sandbox)
    request = ToolRequest(
        tool_name="read_file",
        capability="filesystem.read",
        arguments={"path": "/workspace/hello.txt"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["content"] == "hello world"
    assert result.output["truncated"] is False

def test_read_file_not_found():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=1,
            stdout="",
            stderr="cat: /workspace/missing.txt: No such file or directory\n",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = ReadFileTool(sandbox)
    request = ToolRequest(
        tool_name="read_file",
        capability="filesystem.read",
        arguments={"path": "/workspace/missing.txt"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.FAILURE
    assert result.error.code == "file_not_found"


from control_plane.tools.filesystem import WriteFileTool, MoveFileTool, DeleteFileTool

def test_write_file_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = WriteFileTool(sandbox)
    request = ToolRequest(
        tool_name="write_file",
        capability="filesystem.write",
        arguments={"path": "/workspace/hello.txt", "content": "hello world"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["bytes_written"] == 11
    assert result.output["path"] == "/workspace/hello.txt"

def test_write_file_invalid_input():
    sandbox = FakeSandbox([])
    tool = WriteFileTool(sandbox)
    request = ToolRequest(
        tool_name="write_file",
        capability="filesystem.write",
        arguments={"path": "/workspace/hello.txt", "content": 123},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.INVALID_REQUEST
    assert result.error.code == "invalid_input"

def test_move_file_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = MoveFileTool(sandbox)
    request = ToolRequest(
        tool_name="move_file",
        capability="filesystem.write",
        arguments={"source": "/workspace/a.txt", "destination": "/workspace/b.txt"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["success"] is True
    assert result.output["source"] == "/workspace/a.txt"
    assert result.output["destination"] == "/workspace/b.txt"

def test_delete_file_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = DeleteFileTool(sandbox)
    request = ToolRequest(
        tool_name="delete_file",
        capability="filesystem.delete",
        arguments={"path": "/workspace/hello.txt"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["success"] is True
    assert result.output["path"] == "/workspace/hello.txt"

def test_move_file_not_found():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=1,
            stdout="",
            stderr="mv: cannot stat '/workspace/missing': No such file or directory\n",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = MoveFileTool(sandbox)
    request = ToolRequest(
        tool_name="move_file",
        capability="filesystem.write",
        arguments={"source": "/workspace/missing", "destination": "/workspace/b.txt"},
        request_id="req1",
    )
    
    result = tool._execute(request)
    
    assert result.status == ToolResultStatus.FAILURE
    assert result.error.code == "file_not_found"
