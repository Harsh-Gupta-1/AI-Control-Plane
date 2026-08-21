import pytest
import json
import hashlib
from uuid import uuid4

from control_plane.domain.models import (
    ToolRequest,
    ApprovalGrant,
    ApprovalStatus,
    ApprovalRequest,
    ApprovalDecision
)
from control_plane.policy.gate import CapabilityPolicyGate, PolicyDecision
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.tools.registry import ToolRegistry
from control_plane.tools.contracts import Tool, ToolInputSchema, ToolMetadata
from control_plane.domain import ToolResult, ToolResultStatus

class DummyTool(Tool):
    metadata = ToolMetadata(
        name="dummy",
        capability="secure.action",
        description="Dummy",
        input_schema=ToolInputSchema(required_arguments=frozenset({"target"}))
    )
    def _execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(request.request_id, ToolResultStatus.SUCCESS, output={"done": True})

from control_plane.approval.in_memory import InMemoryApprovalStore, DefaultApprovalAuthorizer

def test_dispatcher_rejects_forged_grant():
    registry = ToolRegistry()
    registry.register(DummyTool())
    policy = CapabilityPolicyGate(rules={"secure.action": PolicyDecision.APPROVE})
    
    store = InMemoryApprovalStore()
    authorizer = DefaultApprovalAuthorizer(store)
    dispatcher = ToolDispatcher(registry, policy, authorizer=authorizer)

    req = ToolRequest(
        request_id="req-123",
        tool_name="dummy",
        capability="secure.action",
        arguments={"target": "foo"}
    )
    
    # 1. No grant
    result = dispatcher.dispatch(req)
    assert result.status == ToolResultStatus.BLOCKED
    assert result.error.code == "approval_required"
    
    # 2. Forged arguments in grant
    approval_req = store.create_request(ApprovalRequest(
        approval_id="app-1",
        task_id="task-1",
        request_id="req-123",
        tool_name="dummy",
        capability="secure.action",
        arguments={"target": "bar"}, # FORGED ARGUMENTS
        reason="Test"
    ))
    store.resolve(ApprovalDecision("app-1", True))
    
    result = dispatcher.dispatch(req, approval_id="app-1")
    assert result.status == ToolResultStatus.BLOCKED
    assert result.error.code == "forged_grant"
    
    # 3. Valid grant
    approval_req2 = store.create_request(ApprovalRequest(
        approval_id="app-2",
        task_id="task-1",
        request_id="req-123",
        tool_name="dummy",
        capability="secure.action",
        arguments={"target": "foo"}, # VALID ARGUMENTS
        reason="Test"
    ))
    store.resolve(ApprovalDecision("app-2", True))
    result = dispatcher.dispatch(req, approval_id="app-2")

    assert result.status == ToolResultStatus.SUCCESS
