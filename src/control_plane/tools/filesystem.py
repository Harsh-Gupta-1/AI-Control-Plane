from typing import Any
import base64
from control_plane.sandbox.contracts import Sandbox
from control_plane.domain import ToolRequest, ToolResult, ToolResultStatus
from control_plane.tools.contracts import Tool, ToolMetadata, ToolInputSchema
from control_plane.tools.path_validation import validate_sandbox_path, ALLOWED_ROOTS

def _resolve_and_validate_path(sandbox: Sandbox, path: str) -> str:
    """Validate path and securely resolve symlinks using the sandbox."""
    # First do lexical validation to prevent basic injection / windows paths
    lexical_path = validate_sandbox_path(path)
    
    # Run realpath -m inside the sandbox to canonically resolve all symlinks 
    # (even for missing components, which is needed for write_file/move_file)
    result = sandbox.execute(["realpath", "-m", lexical_path], timeout_seconds=10)
    if result.exit_code != 0:
        raise ValueError(f"Failed to resolve path: {result.stderr.strip()}")
        
    resolved_path = result.stdout.strip()
    
    # Ensure the resolved canonical path is still within allowed roots
    if not any(resolved_path == root or resolved_path.startswith(root + "/") for root in ALLOWED_ROOTS):
        raise ValueError(f"path resolves outside sandbox boundaries: {resolved_path}")
        
    return resolved_path

class ListDirectoryTool(Tool):
    """Tool to list directory contents inside the sandbox."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="list_directory",
            description="List the contents of a directory in the sandbox.",
            capability="filesystem.read",
            input_schema=ToolInputSchema(required_arguments=frozenset({"path"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        try:
            path = _resolve_and_validate_path(self._sandbox, request.arguments.get("path", ""))
        except ValueError as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_path",
                str(e),
            )
            
        result = self._sandbox.execute(["ls", "-la", path], timeout_seconds=10)
        
        if result.exit_code != 0:
            if "No such file or directory" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "directory_not_found",
                    result.stderr.strip()
                )
            if "Permission denied" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "permission_denied",
                    result.stderr.strip()
                )
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "command_failed",
                result.stderr.strip() or f"exit code {result.exit_code}"
            )
            
        # Parse output into structured list
        entries = []
        lines = result.stdout.strip().split('\n')
        if lines and lines[0].startswith('total'):
            lines = lines[1:]
            
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(None, 8)
            if len(parts) >= 9:
                # permissions, links, owner, group, size, month, day, time/year, name
                entry_type = "directory" if parts[0].startswith('d') else "file"
                entries.append({
                    "name": parts[8],
                    "type": entry_type,
                    "size": int(parts[4]),
                })
                
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={"entries": entries},
        )


class ReadFileTool(Tool):
    """Tool to read file contents inside the sandbox."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="read_file",
            description="Read the contents of a file in the sandbox.",
            capability="filesystem.read",
            input_schema=ToolInputSchema(required_arguments=frozenset({"path"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        try:
            path = _resolve_and_validate_path(self._sandbox, request.arguments.get("path", ""))
        except ValueError as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_path",
                str(e),
            )
            
        max_bytes = request.arguments.get("max_bytes", 1048576)
            
        result = self._sandbox.execute(["cat", path], timeout_seconds=30, max_output_bytes=max_bytes)
        
        if result.exit_code != 0:
            if "No such file or directory" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "file_not_found",
                    result.stderr.strip()
                )
            if "Permission denied" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "permission_denied",
                    result.stderr.strip()
                )
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "command_failed",
                result.stderr.strip() or f"exit code {result.exit_code}"
            )
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={
                "content": result.stdout,
                "truncated": result.output_truncated
            },
        )


class WriteFileTool(Tool):
    """Tool to write file contents inside the sandbox."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="write_file",
            description="Write contents to a file in the sandbox.",
            capability="filesystem.write",
            input_schema=ToolInputSchema(required_arguments=frozenset({"path", "content"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        try:
            path = _resolve_and_validate_path(self._sandbox, request.arguments.get("path", ""))
        except ValueError as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_path",
                str(e),
            )
            
        content = request.arguments.get("content", "")
        if not isinstance(content, str):
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_input",
                "content must be a string",
            )
            
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        result = self._sandbox.execute(["sh", "-c", f"echo {encoded} | base64 -d > {path}"], timeout_seconds=30)
        
        if result.exit_code != 0:
            if "No such file or directory" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "directory_not_found",
                    result.stderr.strip()
                )
            if "Permission denied" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "permission_denied",
                    result.stderr.strip()
                )
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "command_failed",
                result.stderr.strip() or f"exit code {result.exit_code}"
            )
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={
                "bytes_written": len(content.encode("utf-8")),
                "path": path,
            },
        )


class MoveFileTool(Tool):
    """Tool to move a file or directory inside the sandbox."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="move_file",
            description="Move a file or directory in the sandbox.",
            capability="filesystem.write",
            input_schema=ToolInputSchema(required_arguments=frozenset({"source", "destination"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        try:
            source = _resolve_and_validate_path(self._sandbox, request.arguments.get("source", ""))
            destination = _resolve_and_validate_path(self._sandbox, request.arguments.get("destination", ""))
        except ValueError as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_path",
                str(e),
            )
            
        result = self._sandbox.execute(["mv", source, destination], timeout_seconds=30)
        
        if result.exit_code != 0:
            if "No such file or directory" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "file_not_found",
                    result.stderr.strip()
                )
            if "Permission denied" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "permission_denied",
                    result.stderr.strip()
                )
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "command_failed",
                result.stderr.strip() or f"exit code {result.exit_code}"
            )
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={
                "success": True,
                "source": source,
                "destination": destination,
            },
        )


class DeleteFileTool(Tool):
    """Tool to delete a file or directory inside the sandbox."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="delete_file",
            description="Delete a file or directory in the sandbox.",
            capability="filesystem.delete",
            input_schema=ToolInputSchema(required_arguments=frozenset({"path"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        try:
            path = _resolve_and_validate_path(self._sandbox, request.arguments.get("path", ""))
        except ValueError as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_path",
                str(e),
            )
            
        result = self._sandbox.execute(["rm", "-rf", path], timeout_seconds=30)
        
        if result.exit_code != 0:
            if "Permission denied" in result.stderr:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.FAILURE,
                    "permission_denied",
                    result.stderr.strip()
                )
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "command_failed",
                result.stderr.strip() or f"exit code {result.exit_code}"
            )
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={
                "success": True,
                "path": path,
            },
        )
