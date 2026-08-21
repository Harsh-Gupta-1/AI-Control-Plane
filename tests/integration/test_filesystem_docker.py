import pytest
import docker
from control_plane.sandbox.docker_sandbox import DockerSandbox
from control_plane.domain import ToolRequest, ToolResultStatus
from control_plane.tools.filesystem import (
    WriteFileTool, 
    ReadFileTool, 
    ListDirectoryTool, 
    MoveFileTool, 
    DeleteFileTool
)

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

def test_filesystem_tools_integration(sandbox):
    write_tool = WriteFileTool(sandbox)
    read_tool = ReadFileTool(sandbox)
    list_tool = ListDirectoryTool(sandbox)
    move_tool = MoveFileTool(sandbox)
    delete_tool = DeleteFileTool(sandbox)
    
    # 1. Write file
    write_req = ToolRequest(
        tool_name="write_file", capability="filesystem.write",
        arguments={"path": "/workspace/test_file.txt", "content": "hello integration"}
    )
    write_res = write_tool._execute(write_req)
    assert write_res.status == ToolResultStatus.SUCCESS
    
    # 2. Read file
    read_req = ToolRequest(
        tool_name="read_file", capability="filesystem.read",
        arguments={"path": "/workspace/test_file.txt"}
    )
    read_res = read_tool._execute(read_req)
    assert read_res.status == ToolResultStatus.SUCCESS
    assert "hello integration" in read_res.output["content"]
    
    # 3. List directory
    list_req = ToolRequest(
        tool_name="list_directory", capability="filesystem.read",
        arguments={"path": "/workspace"}
    )
    list_res = list_tool._execute(list_req)
    assert list_res.status == ToolResultStatus.SUCCESS
    assert any(entry["name"] == "test_file.txt" for entry in list_res.output["entries"])
    
    # 4. Move file
    move_req = ToolRequest(
        tool_name="move_file", capability="filesystem.write",
        arguments={"source": "/workspace/test_file.txt", "destination": "/workspace/moved_file.txt"}
    )
    move_res = move_tool._execute(move_req)
    assert move_res.status == ToolResultStatus.SUCCESS
    
    # Verify moved
    read_req.arguments["path"] = "/workspace/moved_file.txt"
    read_res = read_tool._execute(read_req)
    assert read_res.status == ToolResultStatus.SUCCESS
    
    # 5. Delete file
    delete_req = ToolRequest(
        tool_name="delete_file", capability="filesystem.delete",
        arguments={"path": "/workspace/moved_file.txt"}
    )
    delete_res = delete_tool._execute(delete_req)
    assert delete_res.status == ToolResultStatus.SUCCESS
    
    # Verify deleted
    read_res = read_tool._execute(read_req)
    assert read_res.status == ToolResultStatus.FAILURE

def test_filesystem_path_traversal_integration(sandbox):
    read_tool = ReadFileTool(sandbox)
    req = ToolRequest(
        tool_name="read_file", capability="filesystem.read",
        arguments={"path": "../../../etc/passwd"}
    )
    res = read_tool._execute(req)
    assert res.status == ToolResultStatus.INVALID_REQUEST
    assert res.error.code == "invalid_path"

def test_filesystem_symlink_escape_integration(sandbox):
    # Setup a symlink inside the workspace pointing to /etc
    sandbox.execute(["ln", "-s", "/etc", "/workspace/symlink"], timeout_seconds=10)
    
    # Try to read /etc/passwd through the symlink
    read_tool = ReadFileTool(sandbox)
    req = ToolRequest(
        tool_name="read_file", capability="filesystem.read",
        arguments={"path": "/workspace/symlink/passwd"}
    )
    res = read_tool._execute(req)
    assert res.status == ToolResultStatus.INVALID_REQUEST
    assert res.error.code == "invalid_path"
    assert "resolves outside sandbox boundaries" in res.error.message

    # Try to write to /etc/evil through the symlink
    write_tool = WriteFileTool(sandbox)
    req = ToolRequest(
        tool_name="write_file", capability="filesystem.write",
        arguments={"path": "/workspace/symlink/evil", "content": "bad"}
    )
    res = write_tool._execute(req)
    assert res.status == ToolResultStatus.INVALID_REQUEST
    assert res.error.code == "invalid_path"
    assert "resolves outside sandbox boundaries" in res.error.message
