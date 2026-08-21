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
