import pytest
from control_plane.domain import TaskState, ToolRequest, PlanStep, Plan
from control_plane.llm.contracts import LLMProposal, ProposalAction
from control_plane.llm.fake_provider import FakeLLMProvider
from control_plane.policy.gate import AllowListedPolicyGate
from control_plane.runtime.task_runtime import TaskRuntime

from control_plane.runtime.agent_loop import AgentLoop
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.tools.registry import ToolRegistry
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

