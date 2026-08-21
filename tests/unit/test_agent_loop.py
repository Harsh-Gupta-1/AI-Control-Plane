import pytest
from control_plane.domain import TaskState, ToolRequest, PlanStep, Plan
from control_plane.llm.contracts import LLMProposal, ProposalAction
from control_plane.llm.fake_provider import FakeLLMProvider
from control_plane.policy.gate import AllowListedPolicyGate
from control_plane.runtime.task_runtime import TaskRuntime

from control_plane.runtime.agent_loop import AgentLoop
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.tools.registry import ToolRegistry
from control_plane.approval.in_memory import InMemoryApprovalStore
from control_plane.policy.gate import CapabilityPolicyGate, PolicyDecision
from tests.unit.fake_sandbox import FakeSandbox

def test_agent_loop_simple_completion():
    runtime = TaskRuntime()
    registry = ToolRegistry()
    dispatcher = ToolDispatcher(registry, AllowListedPolicyGate(frozenset({"cap"})))
    
    proposals = [
        LLMProposal(action=ProposalAction.PLAN, plan_steps=["Step 1"], reasoning="Start"),
        LLMProposal(action=ProposalAction.COMPLETE, completion_reason="Done", reasoning="Finished"),
    ]
    llm = FakeLLMProvider(proposals)
    loop = AgentLoop(runtime, dispatcher, llm)
    
    task = runtime.create_task("Test goal")
    final_task = loop.run(task.task_id)
    
    assert final_task.state == TaskState.COMPLETED

def test_agent_loop_give_up():
    runtime = TaskRuntime()
    dispatcher = ToolDispatcher(ToolRegistry(), AllowListedPolicyGate(frozenset({"cap"})))
    
    proposals = [
        LLMProposal(action=ProposalAction.PLAN, plan_steps=["Step 1"], reasoning="Start"),
        LLMProposal(action=ProposalAction.GIVE_UP, reasoning="Can't do it"),
    ]
    llm = FakeLLMProvider(proposals)
    loop = AgentLoop(runtime, dispatcher, llm)
    
    task = runtime.create_task("Test goal")
    final_task = loop.run(task.task_id)
    
    assert final_task.state == TaskState.FAILED

def test_agent_loop_max_iterations():
    runtime = TaskRuntime()
    dispatcher = ToolDispatcher(ToolRegistry(), AllowListedPolicyGate(frozenset({"cap"})))
    
    # 51 tool calls
    req = ToolRequest("nonexistent", "cap", {}, "req1")
    proposals = [LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=req)] * 51
    llm = FakeLLMProvider(proposals)
    loop = AgentLoop(runtime, dispatcher, llm, max_iterations=5)
    
    task = runtime.create_task("Test goal")
    final_task = loop.run(task.task_id)
    
    assert final_task.state == TaskState.FAILED
    assert "Exceeded maximum iterations" in final_task.observations[-1].content

def test_agent_loop_repeated_action_detection():
    runtime = TaskRuntime()
    dispatcher = ToolDispatcher(ToolRegistry(), AllowListedPolicyGate(frozenset({"cap"})))
    
    req = ToolRequest("nonexistent", "cap", {}, "req1")
    proposals = [
        LLMProposal(action=ProposalAction.PLAN, plan_steps=["1"]),
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=req),
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=req),
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=req), # 3rd repeat triggers replan
        LLMProposal(action=ProposalAction.COMPLETE, completion_reason="Done"),
    ]
    llm = FakeLLMProvider(proposals)
    loop = AgentLoop(runtime, dispatcher, llm)
    
    task = runtime.create_task("Test goal")
    final_task = loop.run(task.task_id)
    
    assert final_task.state == TaskState.COMPLETED
    assert final_task.observations[-2].content.startswith("status=failure error=unknown_tool:tool is not registered: nonexistent")


def test_agent_loop_approval_workflow():
    runtime = TaskRuntime()
    registry = ToolRegistry()
    
    # We use a tool that requires APPROVE
    policy = CapabilityPolicyGate({"cap": PolicyDecision.APPROVE})
    approval_store = InMemoryApprovalStore()
    from control_plane.approval.in_memory import DefaultApprovalAuthorizer
    authorizer = DefaultApprovalAuthorizer(approval_store)
    dispatcher = ToolDispatcher(registry, policy, authorizer=authorizer)
    
    req = ToolRequest("nonexistent", "cap", {}, "req1")
    
    # A single proposal. Agent loop will pause for approval.
    proposals = [
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=req),
        LLMProposal(action=ProposalAction.COMPLETE, completion_reason="Done"),
    ]
    llm = FakeLLMProvider(proposals)
    
    # We'll run the loop in a thread or we can pre-approve in a mock?
    # Wait, _wait_for_approval blocks. Since this is a test, we can mock _wait_for_approval,
    # or just use a mock ApprovalStore that auto-approves.
    # Actually, we can just patch _wait_for_approval to resolve it and then return.
    
    class AutoApprovingLoop(AgentLoop):
        def _wait_for_approval(self, approval_id: str):
            # Auto-approve
            req = self._approval_store.get_request(approval_id)
            from control_plane.domain.models import ApprovalDecision
            self._approval_store.resolve(ApprovalDecision(approval_id, True))
            return super()._wait_for_approval(approval_id)
            
    loop = AutoApprovingLoop(runtime, dispatcher, llm, approval_store=approval_store)
    
    task = runtime.create_task("Test approval")
    final_task = loop.run(task.task_id)
    
    # The tool was unknown, so it will fail after approval, but it did get approved
    assert final_task.state == TaskState.COMPLETED
    
    # Verify approval was created and approved
    approvals = approval_store.get_pending_for_task(task.task_id)
    assert len(approvals) == 0 # because it's resolved
    
    # Check observations: should see the failure from after it was approved
    assert "status=failure error=unknown_tool" in final_task.observations[0].content


def test_agent_loop_approval_rejection():
    runtime = TaskRuntime()
    registry = ToolRegistry()
    
    policy = CapabilityPolicyGate({"cap": PolicyDecision.APPROVE})
    approval_store = InMemoryApprovalStore()
    from control_plane.approval.in_memory import DefaultApprovalAuthorizer
    authorizer = DefaultApprovalAuthorizer(approval_store)
    dispatcher = ToolDispatcher(registry, policy, authorizer=authorizer)
    
    req = ToolRequest("nonexistent", "cap", {}, "req1")
    
    proposals = [
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=req),
        LLMProposal(action=ProposalAction.COMPLETE, completion_reason="Done"),
    ]
    llm = FakeLLMProvider(proposals)
    
    class AutoRejectingLoop(AgentLoop):
        def _wait_for_approval(self, approval_id: str):
            # Auto-reject
            req = self._approval_store.get_request(approval_id)
            from control_plane.domain.models import ApprovalDecision
            self._approval_store.resolve(ApprovalDecision(approval_id, False))
            return super()._wait_for_approval(approval_id)
            
    loop = AutoRejectingLoop(runtime, dispatcher, llm, approval_store=approval_store)
    
    task = runtime.create_task("Test approval")
    final_task = loop.run(task.task_id)
    
    assert final_task.state == TaskState.COMPLETED
    
    # Check observations: should see the rejection
    assert "status=blocked error=approval_rejected" in final_task.observations[0].content


