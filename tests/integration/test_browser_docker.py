import pytest
import docker
import time
from control_plane.sandbox.docker_sandbox import DockerSandbox
from control_plane.domain import ToolRequest, ToolResultStatus
from control_plane.tools.browser import (
    BrowserNavigateTool,
    BrowserExtractTool,
    BrowserDownloadTool,
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
    
    # Start a simple HTTP server in the sandbox to serve as our target
    # Write test page to sandbox
    sb.execute(["sh", "-c", "echo '<html><body><h1>Test</h1><p>Content</p></body></html>' > /workspace/test.html"], timeout_seconds=5)
    # Start server
    sb._client.api.exec_start(
        sb._client.api.exec_create(sb._container.id, ["sh", "-c", "cd /workspace && python3 -m http.server 8080 &"], tty=False)['Id'],
        detach=True
    )
    time.sleep(2) # Give it time to start
    
    yield sb
    sb.stop()
    sb.destroy()

def test_browser_navigate_integration(sandbox):
    tool = BrowserNavigateTool(sandbox)
    req = ToolRequest(
        tool_name="browser_navigate", capability="browser.navigate",
        arguments={"url": "http://localhost:8080/test.html"}
    )
    res = tool._execute(req)
    assert res.status == ToolResultStatus.SUCCESS
    assert res.output["status_code"] == 200
    assert "text/html" in res.output["headers"]

def test_browser_extract_integration(sandbox):
    tool = BrowserExtractTool(sandbox)
    req = ToolRequest(
        tool_name="browser_extract", capability="browser.read",
        arguments={"url": "http://localhost:8080/test.html"}
    )
    res = tool._execute(req)
    assert res.status == ToolResultStatus.SUCCESS
    assert "<h1>Test</h1>" in res.output["content"]

def test_browser_download_integration(sandbox):
    tool = BrowserDownloadTool(sandbox)
    req = ToolRequest(
        tool_name="browser_download", capability="browser.download",
        arguments={"url": "http://localhost:8080/test.html", "filename": "downloaded.html"}
    )
    res = tool._execute(req)
    assert res.status == ToolResultStatus.SUCCESS
    assert res.output["path"] == "/downloads/downloaded.html"
    assert res.output["size_bytes"] > 0
    
    # Verify file actually exists
    check = sandbox.execute(["cat", "/downloads/downloaded.html"], timeout_seconds=5)
    assert check.exit_code == 0
    assert "<h1>Test</h1>" in check.stdout

def test_browser_navigate_timeout_integration(sandbox):
    tool = BrowserNavigateTool(sandbox)
    # Example.com port 81 should timeout
    req = ToolRequest(
        tool_name="browser_navigate", capability="browser.navigate",
        arguments={"url": "http://10.255.255.1"} # Unroutable IP
    )
    # the tool itself has a timeout_seconds=15 inside it
    res = tool._execute(req)
    assert res.status == ToolResultStatus.FAILURE
    assert res.error.code == "timeout"
