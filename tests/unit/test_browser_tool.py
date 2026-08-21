import pytest
from control_plane.sandbox.contracts import SandboxResult
from control_plane.domain import ToolRequest, ToolResultStatus
from control_plane.tools.browser import (
    BrowserNavigateTool,
    BrowserExtractTool,
    BrowserDownloadTool,
    BrowserClickTool,
    BrowserTypeTool,
)
from tests.unit.fake_sandbox import FakeSandbox

def test_browser_navigate_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout='{"url": "http://example.com", "status_code": 200, "title": "Example"}',
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = BrowserNavigateTool(sandbox)
    request = ToolRequest(
        tool_name="browser_navigate",
        capability="browser.navigate",
        arguments={"url": "http://example.com"},
        request_id="req1",
    )
    result = tool._execute(request)
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["status_code"] == 200
    assert result.output["title"] == "Example"

def test_browser_navigate_invalid_url():
    sandbox = FakeSandbox([])
    tool = BrowserNavigateTool(sandbox)
    request = ToolRequest(
        tool_name="browser_navigate",
        capability="browser.navigate",
        arguments={"url": "not_a_url"},
        request_id="req1",
    )
    result = tool._execute(request)
    assert result.status == ToolResultStatus.INVALID_REQUEST

def test_browser_extract_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout='{"url": "http://example.com", "content": "hello"}',
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    tool = BrowserExtractTool(sandbox)
    request = ToolRequest(
        tool_name="browser_extract",
        capability="browser.read",
        arguments={"url": "http://example.com"},
        request_id="req1",
    )
    result = tool._execute(request)
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["content"] == "hello"

def test_browser_download_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0, stdout="", stderr="", timed_out=False, output_truncated=False,
        ),
        SandboxResult(
            exit_code=0, stdout="1024\n", stderr="", timed_out=False, output_truncated=False,
        )
    ])
    tool = BrowserDownloadTool(sandbox)
    request = ToolRequest(
        tool_name="browser_download",
        capability="browser.download",
        arguments={"url": "http://example.com/file.zip", "filename": "file.zip"},
        request_id="req1",
    )
    result = tool._execute(request)
    assert result.status == ToolResultStatus.SUCCESS
    assert result.output["path"] == "/downloads/file.zip"
    assert result.output["size_bytes"] == 1024

def test_browser_interact_success():
    sandbox = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout='{"success": true, "url": "http://example.com"}',
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    click_tool = BrowserClickTool(sandbox)
    req1 = ToolRequest("browser_click", "browser.interact", {"selector": "a"}, "req1")
    assert click_tool._execute(req1).status == ToolResultStatus.SUCCESS
    
    sandbox2 = FakeSandbox([
        SandboxResult(
            exit_code=0,
            stdout='{"success": true, "url": "http://example.com"}',
            stderr="",
            timed_out=False,
            output_truncated=False,
        )
    ])
    type_tool = BrowserTypeTool(sandbox2)
    req2 = ToolRequest("browser_type", "browser.interact", {"selector": "a", "text": "b"}, "req2")
    assert type_tool._execute(req2).status == ToolResultStatus.SUCCESS

def test_browser_navigate_rejects_shell_metacharacters():
    class TrackingFakeSandbox(FakeSandbox):
        def __init__(self):
            super().__init__([])
            self.executed_commands = []
        
        def execute(self, command: list[str], timeout_seconds: int, max_output_bytes: int = 1048576) -> SandboxResult:
            self.executed_commands.append(command)
            return SandboxResult(0, "{}", "", False, False)
            
    sandbox = TrackingFakeSandbox()
    tool = BrowserNavigateTool(sandbox)
    malicious_url = "http://example.com'; touch /tmp/pwned; echo '"
    
    request = ToolRequest(
        tool_name="browser_navigate",
        capability="browser.navigate",
        arguments={"url": malicious_url},
        request_id="req1",
    )
    tool._execute(request)
    
    assert len(sandbox.executed_commands) == 1
    command = sandbox.executed_commands[0]
    
    # We verify it's the expected bash wrapper
    assert command[0] == "bash"
    assert command[1] == "-c"
    
    # The crucial part: the shell command should not contain the literal single quote
    # anywhere directly in the payload interpolation (since the payload is base64 encoded).
    shell_string = command[2]
    
    # Ensure our malicious payload characters don't appear directly in the shell script
    assert malicious_url not in shell_string
    assert "touch /tmp/pwned" not in shell_string
