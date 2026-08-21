"""Integration tests for M11: Long-Running Autonomous Execution."""

import os
import pytest
from pathlib import Path
from typing import Any

from control_plane.domain.models import TaskState, ToolResultStatus, ApprovalStatus, ApprovalGrant
from control_plane.llm.contracts import LLMProposal, ProposalAction, ToolRequest
from control_plane.runtime.agent_loop import AgentLoop
from control_plane.runtime.checkpoint import JsonFileCheckpointStore
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.tools.registry import ToolRegistry
from control_plane.sandbox.docker_sandbox import DockerSandbox
from tests.unit.fake_tools import RecordingTool
from tests.unit.test_agent_loop import FakeLLMProvider
class FakeApprovalStore:
    def create_request(self, request):
        return request
    def wait_for_resolution(self, approval_id, timeout_seconds):
        from control_plane.domain.models import ApprovalRequest, ApprovalStatus
        return ApprovalRequest(
            approval_id=approval_id, task_id="t", request_id="r", tool_name="n", capability="c", arguments={}, reason="", status=ApprovalStatus.APPROVED
        )
    def get_grant(self, approval_id):
        from control_plane.domain.models import ApprovalGrant, ApprovalStatus
        return ApprovalGrant(
            approval_id=approval_id, request_id="r", capability="c", arguments_hash="h", status=ApprovalStatus.APPROVED
        )



def _setup_loop(checkpoint_dir: Path) -> tuple[AgentLoop, TaskRuntime, FakeLLMProvider]:
    runtime = TaskRuntime()
    registry = ToolRegistry()
    
    class FastFakeTool(RecordingTool):
        def __init__(self):
            super().__init__()
            from control_plane.tools import ToolMetadata, ToolInputSchema
            self._metadata = ToolMetadata(
                name="fast_tool",
                description="Fast tool for testing",
                capability="capability.fast",
                input_schema=ToolInputSchema(required_arguments=frozenset({"input"}))
            )
        def _execute(self, request: ToolRequest) -> Any:
            from control_plane.domain.models import ToolResult
            return ToolResult(
                request_id=request.request_id,
                status=ToolResultStatus.SUCCESS,
                output={"result": f"processed {request.arguments.get('input')}"}
            )
            
    registry.register(FastFakeTool())
    
    from control_plane.policy.gate import AllowListedPolicyGate
    policy_gate = AllowListedPolicyGate(frozenset({"capability.fast"}))
    dispatcher = ToolDispatcher(registry, policy_gate)
    llm = FakeLLMProvider([])
    checkpoint_store = JsonFileCheckpointStore(str(checkpoint_dir))
    approval_store = FakeApprovalStore()
    
    loop = AgentLoop(
        runtime=runtime,
        dispatcher=dispatcher,
        llm=llm,
        checkpoint_store=checkpoint_store,
        approval_store=approval_store,
        max_iterations=10,
    )
    return loop, runtime, llm


def test_explicit_pause_resume(tmp_path: Path):
    """M11.3: A running task can be paused safely and resumed."""
    loop, runtime, llm = _setup_loop(tmp_path)
    
    task = runtime.create_task("do some long work")
    
    # We will use an LLM provider that pauses the task mid-way through.
    class PausingLLMProvider(FakeLLMProvider):
        def __init__(self, loop_ref):
            super().__init__([])
            self.loop_ref = loop_ref
            self.calls = 0
            
        def propose(self, context: Any) -> LLMProposal:
            if self.calls == 0:
                self.calls += 1
                return LLMProposal(
                    action=ProposalAction.TOOL_CALL,
                    tool_request=ToolRequest(tool_name="fast_tool", capability="capability.fast", arguments={"input": "1"}),
                    reasoning="step 1"
                )
            if self.calls == 1:
                # Pause the task
                self.loop_ref.pause_task(task.task_id)
                self.calls += 1
                # Return something that doesn't matter much because loop will exit at start of next iteration
                return LLMProposal(
                    action=ProposalAction.TOOL_CALL,
                    tool_request=ToolRequest(tool_name="fast_tool", capability="capability.fast", arguments={"input": "2"}),
                    reasoning="step 2"
                )
            return LLMProposal(
                action=ProposalAction.COMPLETE,
                completion_reason="done",
                reasoning="done"
            )

    llm = PausingLLMProvider(loop)
    loop._llm = llm
    
    final_task = loop.run(task.task_id)
    
    # Task should exit early in PAUSED state
    assert final_task.state == TaskState.PAUSED
    
    # The checkpoint should still exist because it was NOT deleted for PAUSED state
    assert len(list(tmp_path.glob("*.json"))) == 1
    
    # Now we resume
    final_task = loop.run(task.task_id, resume=True)
    assert final_task.state == TaskState.COMPLETED
    
    # Checkpoint should be deleted after completion
    assert len(list(tmp_path.glob("*.json"))) == 0


def test_cancel_task(tmp_path: Path):
    """M11.4: Graceful cancellation."""
    loop, runtime, llm = _setup_loop(tmp_path)
    
    task = runtime.create_task("do work")
    
    # Simulate some initial work to create a checkpoint
    llm.proposals = [
        LLMProposal(
            action=ProposalAction.TOOL_CALL,
            tool_request=ToolRequest(tool_name="fast_tool", capability="capability.fast", arguments={"input": "A"}),
            reasoning="step A"
        )
    ]
    
    class CancelLLM(FakeLLMProvider):
        def __init__(self, loop_ref):
            super().__init__([])
            self.loop_ref = loop_ref
            self.calls = 0
            
        def propose(self, context: Any) -> LLMProposal:
            if self.calls == 0:
                self.calls += 1
                return LLMProposal(
                    action=ProposalAction.TOOL_CALL,
                    tool_request=ToolRequest(tool_name="fast_tool", capability="capability.fast", arguments={"input": "1"}),
                    reasoning="step 1"
                )
            # Cancel it
            self.loop_ref.cancel_task(task.task_id)
            return LLMProposal(
                action=ProposalAction.COMPLETE,
                completion_reason="done",
                reasoning="done"
            )

    loop._llm = CancelLLM(loop)
    loop.run(task.task_id)
    
    final_task = runtime.get_task(task.task_id)
    assert final_task.state == TaskState.CANCELLED
    
    # Running it again should just return immediately
    final_task2 = loop.run(task.task_id)
    assert final_task2.state == TaskState.CANCELLED
    
    # Checkpoint should be deleted upon cancellation
    assert list(tmp_path.glob("*.json")) == []


def test_cross_process_restore(tmp_path: Path):
    """M11.5: Process interruption / restart."""
    # Process A
    loop_a, runtime_a, llm_a = _setup_loop(tmp_path)
    task = runtime_a.create_task("interrupted work")
    
    class CrashLLM(FakeLLMProvider):
        def __init__(self):
            super().__init__([])
            self.calls = 0
        def propose(self, context):
            if self.calls == 0:
                self.calls += 1
                return LLMProposal(
                    action=ProposalAction.TOOL_CALL,
                    tool_request=ToolRequest(tool_name="fast_tool", capability="capability.fast", arguments={"input": "1"}),
                    reasoning="step 1"
                )
            if self.calls == 1:
                # hard crash simulation (RuntimeError is caught, but we want to simulate process death)
                # Instead of crashing python, we just raise an Exception and patch checkpoint deletion so it survives
                self.calls += 1
                raise KeyboardInterrupt("Simulate kill -9")
            return LLMProposal(action=ProposalAction.COMPLETE, completion_reason="done", reasoning="done")
            
    loop_a._llm = CrashLLM()
    
    try:
        loop_a.run(task.task_id)
    except KeyboardInterrupt:
        pass
        
    # Checkpoint MUST exist since process died
    assert len(list(tmp_path.glob("*.json"))) == 1
    
    # Process B
    loop_b, runtime_b, llm_b = _setup_loop(tmp_path)
    
    llm_b._proposals = [
        LLMProposal(action=ProposalAction.COMPLETE, completion_reason="resumed and finished", reasoning="done")
    ]
    
    # Resume the task
    final_task_b = loop_b.run(task.task_id, resume=True)
    
    assert final_task_b.state == TaskState.COMPLETED
    assert len(final_task_b.actions) == 1
    assert final_task_b.actions[0].request.arguments["input"] == "1"
    
    # Checkpoint should be deleted now
    assert len(list(tmp_path.glob("*.json"))) == 0

