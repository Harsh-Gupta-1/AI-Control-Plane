import json
import base64
from typing import Any
from urllib.parse import urlparse
from control_plane.sandbox.contracts import Sandbox
from control_plane.domain import ToolRequest, ToolResult, ToolResultStatus
from control_plane.tools.contracts import Tool, ToolMetadata, ToolInputSchema

def _is_valid_http_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except ValueError:
        return False

# A lightweight stateful browser runner injected on demand
PLAYWRIGHT_SCRIPT = """
import sys, json, os

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(json.dumps({"error": "Playwright is not installed in the sandbox. Hardening requirement failed."}))
    sys.exit(0)

STATE_FILE = "/workspace/browser_state.json"
URL_FILE = "/workspace/current_url.txt"

def get_current_url():
    if os.path.exists(URL_FILE):
        with open(URL_FILE, "r") as f:
            return f.read().strip()
    return ""

def set_current_url(url):
    with open(URL_FILE, "w") as f:
        f.write(url)

def run():
    cmd = sys.argv[1]
    args = json.loads(sys.argv[2])
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=STATE_FILE if os.path.exists(STATE_FILE) else None)
        page = context.new_page()
        
        try:
            if cmd == 'navigate':
                url = args['url']
                resp = page.goto(url, wait_until='domcontentloaded', timeout=15000)
                set_current_url(page.url)
                context.storage_state(path=STATE_FILE)
                return {'url': page.url, 'status_code': resp.status if resp else -1, 'title': page.title()}
                
            elif cmd == 'extract':
                url = args.get('url') or get_current_url()
                if not url: return {'error': 'No URL provided or active'}
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                text = page.locator('body').inner_text()
                set_current_url(page.url)
                context.storage_state(path=STATE_FILE)
                return {'url': page.url, 'content': text[:args.get('max_length', 51200)]}
                
            elif cmd == 'click':
                url = get_current_url()
                if not url: return {'error': 'No active URL'}
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                page.locator(args['selector']).click(timeout=5000)
                try:
                    page.wait_for_load_state('domcontentloaded', timeout=3000)
                except:
                    pass
                set_current_url(page.url)
                context.storage_state(path=STATE_FILE)
                return {'success': True, 'url': page.url}
                
            elif cmd == 'type':
                url = get_current_url()
                if not url: return {'error': 'No active URL'}
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                page.locator(args['selector']).fill(args['text'], timeout=5000)
                try:
                    page.wait_for_load_state('domcontentloaded', timeout=3000)
                except:
                    pass
                set_current_url(page.url)
                context.storage_state(path=STATE_FILE)
                return {'success': True, 'url': page.url}
                
        except Exception as e:
            return {'error': str(e)}
        finally:
            browser.close()

if __name__ == '__main__':
    print(json.dumps(run()))
"""

def _execute_playwright(sandbox: Sandbox, cmd: str, args: dict[str, Any], timeout: int = 30) -> ToolResult:
    import base64
    script_b64 = base64.b64encode(PLAYWRIGHT_SCRIPT.encode("utf-8")).decode("utf-8")
    args_json = json.dumps(args)
    
    # We use python3 -c to execute the decoded script
    command = ["bash", "-c", f"echo '{script_b64}' | base64 -d | python3 - {cmd} '{args_json}'"]
    result = sandbox.execute(command, timeout_seconds=timeout)
    
    if result.exit_code != 0 or result.timed_out:
        return ToolResult.failure(
            "", ToolResultStatus.FAILURE, "browser_error", result.stderr.strip() or "Browser execution failed or timed out"
        )
        
    try:
        data = json.loads(result.stdout.strip())
        if "error" in data:
            return ToolResult.failure("", ToolResultStatus.FAILURE, "browser_error", data["error"])
        return ToolResult("", ToolResultStatus.SUCCESS, output=data)
    except json.JSONDecodeError:
        return ToolResult.failure("", ToolResultStatus.FAILURE, "browser_error", f"Invalid browser output: {result.stdout.strip()}")


class BrowserNavigateTool(Tool):
    """Navigate to a URL and return page metadata."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="browser_navigate",
            description="Navigate to a URL and return page metadata (title, status).",
            capability="browser.navigate",
            input_schema=ToolInputSchema(required_arguments=frozenset({"url"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        url = request.arguments.get("url", "")
        if not _is_valid_http_url(url):
            return ToolResult.failure(request.request_id, ToolResultStatus.INVALID_REQUEST, "invalid_url", "URL must be a valid http or https URL")
            
        res = _execute_playwright(self._sandbox, "navigate", {"url": url}, timeout=20)
        res.request_id = request.request_id
        return res

class BrowserExtractTool(Tool):
    """Extract text content from a page."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="browser_extract",
            description="Extract text content from a URL.",
            capability="browser.read",
            input_schema=ToolInputSchema(required_arguments=frozenset({"url"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        url = request.arguments.get("url", "")
        if not _is_valid_http_url(url):
            return ToolResult.failure(request.request_id, ToolResultStatus.INVALID_REQUEST, "invalid_url", "URL must be a valid http or https URL")
            
        max_length = request.arguments.get("max_length", 51200)
        res = _execute_playwright(self._sandbox, "extract", {"url": url, "max_length": max_length}, timeout=30)
        res.request_id = request.request_id
        return res

class BrowserDownloadTool(Tool):
    """Download a file from a URL to /downloads."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="browser_download",
            description="Download a file from a URL to the sandbox downloads directory.",
            capability="browser.download",
            input_schema=ToolInputSchema(required_arguments=frozenset({"url"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        # Wget remains fine for downloads as it avoids playwright memory overhead for large binaries
        url = request.arguments.get("url", "")
        if not _is_valid_http_url(url):
            return ToolResult.failure(request.request_id, ToolResultStatus.INVALID_REQUEST, "invalid_url", "URL must be a valid http or https URL")
            
        filename = request.arguments.get("filename", "downloaded_file")
        if "/" in filename or ".." in filename:
            return ToolResult.failure(request.request_id, ToolResultStatus.INVALID_REQUEST, "invalid_filename", "Filename cannot contain paths")
            
        path = f"/downloads/{filename}"
        result = self._sandbox.execute(["wget", "-q", "-O", path, url], timeout_seconds=60)
        
        if result.exit_code != 0:
            return ToolResult.failure(request.request_id, ToolResultStatus.FAILURE, "download_failed", result.stderr.strip() or "Download failed")
            
        stat_result = self._sandbox.execute(["stat", "-c", "%s", path], timeout_seconds=5)
        size_bytes = int(stat_result.stdout.strip()) if stat_result.exit_code == 0 else 0
                
        return ToolResult(request.request_id, ToolResultStatus.SUCCESS, output={"path": path, "size_bytes": size_bytes})

class BrowserClickTool(Tool):
    """Click an element in the browser."""
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="browser_click",
            description="Click an element in the browser.",
            capability="browser.interact",
            input_schema=ToolInputSchema(required_arguments=frozenset({"selector"})),
        )
    @property
    def metadata(self) -> ToolMetadata: return self._metadata
    def _execute(self, request: ToolRequest) -> ToolResult:
        res = _execute_playwright(self._sandbox, "click", {"selector": request.arguments["selector"]}, timeout=20)
        res.request_id = request.request_id
        return res

class BrowserTypeTool(Tool):
    """Type text into an element in the browser."""
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="browser_type",
            description="Type text into an element in the browser.",
            capability="browser.interact",
            input_schema=ToolInputSchema(required_arguments=frozenset({"selector", "text"})),
        )
    @property
    def metadata(self) -> ToolMetadata: return self._metadata
    def _execute(self, request: ToolRequest) -> ToolResult:
        res = _execute_playwright(self._sandbox, "type", {"selector": request.arguments["selector"], "text": request.arguments["text"]}, timeout=20)
        res.request_id = request.request_id
        return res
