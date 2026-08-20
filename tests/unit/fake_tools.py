"""Test-only tools used to verify the controlled dispatcher boundary."""

from control_plane.domain import ToolRequest, ToolResult, ToolResultStatus
from control_plane.tools import Tool, ToolInputSchema, ToolMetadata


class RecordingTool(Tool):
    def __init__(self) -> None:
        self.execution_count = 0
        self._metadata = ToolMetadata(
            name="fake_read_tool",
            description="Records that the dispatcher invoked it.",
            capability="test.read",
            input_schema=ToolInputSchema(required_arguments=frozenset({"value"})),
        )

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        self.execution_count += 1
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={"echo": request.arguments["value"]},
        )


class FailingTool(RecordingTool):
    def _execute(self, request: ToolRequest) -> ToolResult:
        self.execution_count += 1
        raise RuntimeError("test tool failed")
