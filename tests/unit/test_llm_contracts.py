import pytest
from control_plane.domain import ToolRequest
from control_plane.llm.contracts import AgentContext, LLMProposal, ProposalAction
from control_plane.llm.fake_provider import FakeLLMProvider

def test_fake_llm_provider():
    req1 = ToolRequest("test_tool", "test", {"arg": "val"}, "req1")
    proposals = [
        LLMProposal(action=ProposalAction.PLAN, plan_steps=["Step 1"], reasoning="Start"),
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=req1, reasoning="Do it"),
        LLMProposal(action=ProposalAction.COMPLETE, completion_reason="Done", reasoning="Finished"),
    ]
    provider = FakeLLMProvider(proposals)
    ctx = AgentContext(task_goal="test")
    
    p1 = provider.propose(ctx)
    assert p1.action == ProposalAction.PLAN
    assert p1.plan_steps == ["Step 1"]
    
    p2 = provider.propose(ctx)
    assert p2.action == ProposalAction.TOOL_CALL
    assert p2.tool_request.tool_name == "test_tool"
    
    p3 = provider.propose(ctx)
    assert p3.action == ProposalAction.COMPLETE
    assert p3.completion_reason == "Done"
    
    p4 = provider.propose(ctx)
    assert p4.action == ProposalAction.GIVE_UP
    assert p4.reasoning == "no more proposals"

def test_agent_context_defaults():
    ctx = AgentContext(task_goal="test")
    assert ctx.plan_summary is None
    assert ctx.current_step is None
    assert ctx.completed_actions == []
    assert ctx.recent_observations == []
    assert ctx.available_tools == []
    assert ctx.error_context is None
