from typing import Any
from control_plane.sandbox.contracts import Sandbox
from control_plane.domain import ToolRequest, ToolResult, ToolResultStatus
from control_plane.tools.contracts import Tool, ToolMetadata, ToolInputSchema
from control_plane.tools.path_validation import validate_sandbox_path

class ExecuteCommandTool(Tool):
    """Tool to execute a shell command inside the sandbox."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="execute_command",
            description="Execute a shell command inside the sandbox.",
            capability="terminal.execute",
            input_schema=ToolInputSchema(required_arguments=frozenset({"command"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        try:
            working_directory = validate_sandbox_path(request.arguments.get("working_directory", "/workspace"))
        except ValueError as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_path",
                str(e),
            )
            
        command = request.arguments.get("command", "")
        if not isinstance(command, str):
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_input",
                "command must be a string",
            )
            
        timeout = request.arguments.get("timeout_seconds", 30)
        if not isinstance(timeout, int):
            try:
                timeout = int(timeout)
            except (ValueError, TypeError):
                timeout = 30
                
        result = self._sandbox.execute(
            ["sh", "-c", f"cd {working_directory} && {command}"], 
            timeout_seconds=timeout
        )
        
        if result.timed_out:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "timeout",
                "Command execution timed out",
            )
        
        if result.exit_code != 0:
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
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
                "output_truncated": result.output_truncated,
            },
        )

class ExecuteBackgroundCommandTool(Tool):
    """Tool to execute a shell command in the background inside the sandbox."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="execute_background_command",
            description="Execute a shell command in the background inside the sandbox. Returns a unique background ID.",
            capability="terminal.execute_background",
            input_schema=ToolInputSchema(required_arguments=frozenset({"command"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        try:
            working_directory = validate_sandbox_path(request.arguments.get("working_directory", "/workspace"))
        except ValueError as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_path",
                str(e),
            )
            
        command = request.arguments.get("command", "")
        if not isinstance(command, str):
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_input",
                "command must be a string",
            )
                
        try:
            bg_id = self._sandbox.execute_background(
                ["sh", "-c", f"cd {working_directory} && {command}"]
            )
        except Exception as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "command_failed",
                str(e)
            )
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={"background_id": bg_id},
        )

class GetBackgroundCommandStatusTool(Tool):
    """Tool to get the status and recent logs of a background command."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="get_background_status",
            description="Get the status ('running' or 'stopped') and recent logs of a background command using its background ID.",
            capability="terminal.get_background_status",
            input_schema=ToolInputSchema(required_arguments=frozenset({"background_id"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        bg_id = request.arguments.get("background_id", "")
        if not isinstance(bg_id, str):
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_input",
                "background_id must be a string",
            )
                
        try:
            status_dict = self._sandbox.get_background_status(bg_id)
        except Exception as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "status_check_failed",
                str(e)
            )
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output=status_dict,
        )

class StopBackgroundCommandTool(Tool):
    """Tool to forcefully stop a running background command."""
    
    def __init__(self, sandbox: Sandbox) -> None:
        self._sandbox = sandbox
        self._metadata = ToolMetadata(
            name="stop_background_command",
            description="Forcefully stop a running background command using its background ID.",
            capability="terminal.stop_background",
            input_schema=ToolInputSchema(required_arguments=frozenset({"background_id"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        bg_id = request.arguments.get("background_id", "")
        if not isinstance(bg_id, str):
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_input",
                "background_id must be a string",
            )
                
        try:
            self._sandbox.stop_background(bg_id)
        except Exception as e:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "stop_failed",
                str(e)
            )
            
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={"success": True},
        )
