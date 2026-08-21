import re
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

class BrowserNavigateTool(Tool):
    """Navigate to a URL and return page metadata."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="browser_navigate",
            description="Navigate to a URL and return page metadata (headers).",
            capability="browser.navigate",
            input_schema=ToolInputSchema(required_arguments=frozenset({"url"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        url = request.arguments.get("url", "")
        if not _is_valid_http_url(url):
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_url",
                "URL must be a valid http or https URL"
            )
            
        # For Option B (no playwright), we simulate navigation using curl to fetch headers
        result = self._sandbox.execute(["curl", "-sI", "--max-time", "10", url], timeout_seconds=15)
        
        if result.exit_code != 0:
            if result.timed_out or result.exit_code == 28:
                return ToolResult.failure(
                    request.request_id, ToolResultStatus.FAILURE, "timeout", "Navigation timed out"
                )
            return ToolResult.failure(
                request.request_id, ToolResultStatus.FAILURE, "navigation_failed", result.stderr.strip() or f"curl exit code {result.exit_code}"
            )
            
        # Parse status code from HTTP/1.1 200 OK
        status_code = -1
        match = re.search(r"HTTP/[\d\.]+\s+(\d+)", result.stdout)
        if match:
            status_code = int(match.group(1))
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={
                "url": url,
                "status_code": status_code,
                "headers": result.stdout,
            },
        )

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
            return ToolResult.failure(
                request.request_id, ToolResultStatus.INVALID_REQUEST, "invalid_url", "URL must be a valid http or https URL"
            )
            
        max_length = request.arguments.get("max_length", 51200) # 50KB default
        
        # We limit the max output size of sandbox execution
        result = self._sandbox.execute(["curl", "-sL", "--max-time", "15", url], timeout_seconds=20, max_output_bytes=max_length)
        
        if result.exit_code != 0:
            if result.timed_out or result.exit_code == 28:
                return ToolResult.failure(
                    request.request_id, ToolResultStatus.FAILURE, "timeout", "Extraction timed out"
                )
            return ToolResult.failure(
                request.request_id, ToolResultStatus.FAILURE, "extraction_failed", result.stderr.strip() or f"curl exit code {result.exit_code}"
            )
            
        # In a real Playwright setup, this would extract text content. With curl, it's HTML.
        # But we adhere to the MVP Option B scope.
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={
                "url": url,
                "content": result.stdout,
                "truncated": result.output_truncated,
            },
        )

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
        url = request.arguments.get("url", "")
        if not _is_valid_http_url(url):
            return ToolResult.failure(
                request.request_id, ToolResultStatus.INVALID_REQUEST, "invalid_url", "URL must be a valid http or https URL"
            )
            
        filename = request.arguments.get("filename", "downloaded_file")
        if "/" in filename or ".." in filename:
            return ToolResult.failure(
                request.request_id, ToolResultStatus.INVALID_REQUEST, "invalid_filename", "Filename cannot contain paths"
            )
            
        path = f"/downloads/{filename}"
        
        result = self._sandbox.execute(["wget", "-q", "-O", path, url], timeout_seconds=60)
        
        if result.exit_code != 0:
            if result.timed_out or result.exit_code == 4:
                return ToolResult.failure(
                    request.request_id, ToolResultStatus.FAILURE, "timeout", "Download timed out"
                )
            return ToolResult.failure(
                request.request_id, ToolResultStatus.FAILURE, "download_failed", result.stderr.strip() or f"wget exit code {result.exit_code}"
            )
            
        # Get file size using stat
        stat_result = self._sandbox.execute(["stat", "-c", "%s", path], timeout_seconds=5)
        size_bytes = 0
        if stat_result.exit_code == 0:
            try:
                size_bytes = int(stat_result.stdout.strip())
            except ValueError:
                pass
                
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={
                "path": path,
                "size_bytes": size_bytes,
            },
        )

class BrowserClickTool(Tool):
    """Stub for clicking elements. (Not implemented in MVP Option B)"""
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
        return ToolResult.failure(request.request_id, ToolResultStatus.FAILURE, "not_implemented", "Option B minimal browser does not support interaction.")

class BrowserTypeTool(Tool):
    """Stub for typing text. (Not implemented in MVP Option B)"""
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
        return ToolResult.failure(request.request_id, ToolResultStatus.FAILURE, "not_implemented", "Option B minimal browser does not support interaction.")
