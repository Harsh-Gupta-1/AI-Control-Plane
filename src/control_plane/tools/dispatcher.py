"""The single supported execution path for registered tools."""

from copy import deepcopy

from control_plane.domain import ToolRequest, ToolResult, ToolResultStatus
from control_plane.policy import PolicyDecision, PolicyGate
from control_plane.tools.contracts import ToolInputSchema
from control_plane.tools.registry import ToolNotFoundError, ToolRegistry


class ToolDispatcher:
    """Validates, authorizes, resolves, and executes a structured request."""

    def __init__(self, registry: ToolRegistry, policy_gate: PolicyGate, authorizer=None) -> None:
        self._registry = registry
        self._policy_gate = policy_gate
        self._authorizer = authorizer

    def dispatch(self, request: object, approval_id: str | None = None) -> ToolResult:
        """Return a structured result; never execute an invalid or blocked request."""
        validation_error = self._validate_request(request)
        if validation_error is not None:
            return validation_error
        assert isinstance(request, ToolRequest)

        policy_result = self._policy_gate.evaluate(request)
        
        if policy_result.decision is PolicyDecision.APPROVE:
            if not self._authorizer:
                return ToolResult.failure(
                    request.request_id, ToolResultStatus.BLOCKED, "approval_required", policy_result.reason
                )
            
            if approval_id is None:
                return ToolResult.failure(
                    request.request_id,
                    ToolResultStatus.BLOCKED,
                    "approval_required",
                    policy_result.reason,
                )
            
            # Structurally verify the approval grant against the incoming request via authoritative boundary
            if not self._authorizer.authorize(request, approval_id):
                return ToolResult.failure(request.request_id, ToolResultStatus.BLOCKED, "forged_grant", "Invalid or forged approval.")
            
            # Verified: this request was explicitly approved
            
        elif policy_result.decision is PolicyDecision.BLOCK:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.BLOCKED,
                "policy_blocked",
                policy_result.reason,
            )

        try:
            tool = self._registry.resolve_tool(request.tool_name)
        except ToolNotFoundError:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "unknown_tool",
                f"tool is not registered: {request.tool_name}",
            )

        if request.capability != tool.metadata.capability:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "capability_mismatch",
                "request capability does not match the registered tool capability",
            )

        schema_error = self._validate_input_schema(request, tool.metadata.input_schema)
        if schema_error is not None:
            return schema_error

        try:
            result = tool._execute(deepcopy(request))
        except Exception as error:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "tool_execution_failed",
                str(error),
            )

        if not isinstance(result, ToolResult) or result.request_id != request.request_id:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.FAILURE,
                "invalid_tool_result",
                "tool returned an invalid result",
            )
        return deepcopy(result)

    @staticmethod
    def _validate_request(request: object) -> ToolResult | None:
        if not isinstance(request, ToolRequest):
            return ToolResult.failure(
                "",
                ToolResultStatus.INVALID_REQUEST,
                "invalid_request_type",
                "request must be a ToolRequest",
            )
        if not request.request_id or not isinstance(request.request_id, str):
            return ToolResult.failure(
                "",
                ToolResultStatus.INVALID_REQUEST,
                "invalid_request_id",
                "request_id must be a non-empty string",
            )
        if not isinstance(request.tool_name, str) or not request.tool_name.strip():
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_tool_name",
                "tool_name must be a non-empty string",
            )
        if not isinstance(request.capability, str) or not request.capability.strip():
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_capability",
                "capability must be a non-empty string",
            )
        if not isinstance(request.arguments, dict):
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "invalid_arguments",
                "arguments must be a dictionary",
            )
        return None

    @staticmethod
    def _validate_input_schema(
        request: ToolRequest, schema: ToolInputSchema
    ) -> ToolResult | None:
        required_arguments = schema.required_arguments
        missing = sorted(required_arguments.difference(request.arguments))
        if missing:
            return ToolResult.failure(
                request.request_id,
                ToolResultStatus.INVALID_REQUEST,
                "missing_arguments",
                f"missing required arguments: {', '.join(missing)}",
            )
        return None

    def available_tools(self):
        """Return the metadata for all available tools in the registry."""
        return self._registry.available_tools()
