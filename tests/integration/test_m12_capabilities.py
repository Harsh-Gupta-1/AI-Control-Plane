"""Integration tests for M12 Fine-Grained Capability Security."""

import pytest
from uuid import uuid4
from control_plane.domain.models import CapabilityConstraints, TaskState, ToolRequest
from control_plane.policy.gate import CapabilityPolicyGate, PolicyDecision
from control_plane.runtime.agent_loop import AgentLoop
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.tools.registry import ToolRegistry
from tests.unit.fake_tools import RecordingTool

class FastFakeTool(RecordingTool):
    def __init__(self):
        super().__init__()
        from control_plane.tools import ToolMetadata, ToolInputSchema
        self._metadata = ToolMetadata(
            name="fast_tool",
            description="fast fake tool",
            capability="capability.fast",
            input_schema=ToolInputSchema(required_arguments={"input"})
        )
        
    def _execute(self, request: ToolRequest) -> 'ToolResult':
        from control_plane.domain.models import ToolResult, ToolResultStatus
        self._record_execution(request)
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={"result": f"processed {request.arguments.get('input')}"}
        )
from control_plane.llm.contracts import LLMProposal, ProposalAction
from tests.integration.test_m11_long_running import FakeLLMProvider

def test_task_blocked_by_constraints():
    """M12: A task attempting to use a capability not in its constraints is blocked."""
    runtime = TaskRuntime()
    registry = ToolRegistry()
    registry.register(FastFakeTool())
    
    # Policy says fast tool capability is ALLOW
    policy_gate = CapabilityPolicyGate({"capability.fast": PolicyDecision.ALLOW})
    dispatcher = ToolDispatcher(registry, policy_gate)
    
    loop = AgentLoop(
        runtime=runtime,
        dispatcher=dispatcher,
        llm=FakeLLMProvider([]),
    )
    
    # Task only allowed to use some other capability
    constraints = CapabilityConstraints(frozenset({"capability.other"}))
    task = runtime.create_task("do restricted work", capability_constraints=constraints)
    
    class RestrictingLLMProvider(FakeLLMProvider):
        def propose(self, context) -> LLMProposal:
            # LLM ignores constraints and tries to use fast tool
            return LLMProposal(
                action=ProposalAction.TOOL_CALL,
                tool_request=ToolRequest(tool_name="fast_tool", capability="capability.fast", arguments={"input": "1"}),
                reasoning="I will use fast_tool"
            )
            
    loop._llm = RestrictingLLMProvider([])
    
    final_task = loop.run(task.task_id)
    
    # The task should fail due to policy rejection because of capability constraints
    assert final_task.state == TaskState.FAILED
    
    # Look for the policy rejection observation
    policy_rejections = [obs for obs in final_task.observations if "restricted by task constraints" in obs.content]
    assert len(policy_rejections) > 0

def test_task_allowed_by_constraints():
    """M12: A task with appropriate constraints can execute tools."""
    runtime = TaskRuntime()
    registry = ToolRegistry()
    registry.register(FastFakeTool())
    
    policy_gate = CapabilityPolicyGate({"capability.fast": PolicyDecision.ALLOW})
    dispatcher = ToolDispatcher(registry, policy_gate)
    
    loop = AgentLoop(
        runtime=runtime,
        dispatcher=dispatcher,
        llm=FakeLLMProvider([]),
    )
    
    # Task is explicitly allowed to use fast tool
    constraints = CapabilityConstraints(frozenset({"capability.fast"}))
    task = runtime.create_task("do allowed work", capability_constraints=constraints)
    
    class AllowedLLMProvider(FakeLLMProvider):
        def __init__(self):
            super().__init__([])
            self.calls = 0
            
        def propose(self, context) -> LLMProposal:
            if self.calls == 0:
                self.calls += 1
                return LLMProposal(
                    action=ProposalAction.TOOL_CALL,
                    tool_request=ToolRequest(tool_name="fast_tool", capability="capability.fast", arguments={"input": "1"}),
                    reasoning="I will use fast_tool"
                )
            return LLMProposal(
                action=ProposalAction.COMPLETE,
                completion_reason="done",
                reasoning="finished"
            )
            
    loop._llm = AllowedLLMProvider()
    
    final_task = loop.run(task.task_id)
    
    assert final_task.state == TaskState.COMPLETED
    assert len(final_task.actions) == 1
    assert final_task.actions[0].request.action_type == "fast_tool"
