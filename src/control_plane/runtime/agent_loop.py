import logging
from uuid import uuid4
from typing import Any

from control_plane.domain import (
    ActionRequest, Observation, Task, TaskState, Plan, PlanStep, ToolResultStatus, ApprovalRequest, ApprovalDecision, ApprovalGrant
)
from control_plane.llm.contracts import AgentContext, LLMProvider, ProposalAction
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.approval.contracts import ApprovalStore
from control_plane.runtime.checkpoint import CheckpointStore, TaskCheckpoint
from control_plane.runtime.recovery import determine_recovery
from control_plane.domain.models import FailureCategory
from control_plane.verification.contracts import VerificationCheck
from control_plane.tracing.contracts import TraceSink, TraceEvent, TraceEventType
from control_plane.sandbox.contracts import Sandbox
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def _summarize_result(result) -> str:
    summary = f"status={result.status.value}"
    if result.error:
        summary += f" error={result.error.code}:{result.error.message}"
    
    if result.output:
        keys = list(result.output.keys())
        summary += f" output_keys={keys}"
        for k in ["content", "stdout", "stderr"]:
            if k in result.output and isinstance(result.output[k], str):
                summary += f" {k}_len={len(result.output[k])}"
    return summary

class AgentLoop:
    """Drives the plan-act-observe loop with deterministic governance."""
    
    def __init__(
        self,
        runtime: TaskRuntime,
        dispatcher: ToolDispatcher,
        llm: LLMProvider,
        approval_store: ApprovalStore | None = None,
        checkpoint_store: CheckpointStore | None = None,
        trace_sink: TraceSink | None = None,
        verification_checks: list[tuple[VerificationCheck, dict]] | None = None,
        sandbox: Sandbox | None = None,
        max_iterations: int = 50,
        max_consecutive_failures: int = 3,
        context_action_history_limit: int = 10,
        context_observation_limit: int = 10,
    ) -> None:
        self._runtime = runtime
        self._dispatcher = dispatcher
        self._llm = llm
        self._approval_store = approval_store
        self._checkpoint_store = checkpoint_store
        self._trace_sink = trace_sink
        self._verification_checks = verification_checks or []
        self._sandbox = sandbox
        self._max_iterations = max_iterations
        self._max_consecutive_failures = max_consecutive_failures
        self._context_action_history_limit = context_action_history_limit
        self._context_observation_limit = context_observation_limit
        
    def _emit_trace(self, event_type: TraceEventType, task_id: str, **payload: Any) -> None:
        if self._trace_sink:
            try:
                self._trace_sink.emit(TraceEvent(
                    event_id=str(uuid4()),
                    event_type=event_type,
                    task_id=task_id,
                    payload=payload,
                ))
            except Exception as e:
                logger.error(f"Failed to emit trace: {e}")
                # Hardening fix: Do not swallow trace failure silently. Record it as an Observation.
                try:
                    self._runtime.record_observation(task_id, Observation(
                        observation_id=str(uuid4()),
                        source="trace_system",
                        content=f"Warning: Telemetry trace emission failed: {str(e)}",
                        data={"event_type": event_type.value}
                    ))
                except Exception:
                    pass # Ignore if recording observation also fails (e.g. task terminal)
        
    def _save_checkpoint(self, task: Task, iterations: int, failures: int) -> None:
        if not self._checkpoint_store:
            return
        checkpoint = TaskCheckpoint(
            task=task,
            plan=task.plan,
            action_history=task.actions,
            observations=task.observations,
            iteration_count=iterations,
            consecutive_failures=failures,
            sandbox_id=getattr(self._sandbox, "id", None) if self._sandbox else None,
            created_at=datetime.now(timezone.utc)
        )
        self._checkpoint_store.save(task.task_id, checkpoint)
        self._emit_trace(TraceEventType.CHECKPOINT_SAVED, task.task_id, iteration=iterations, consecutive_failures=failures)
        
    def _wait_for_approval(self, approval_id: str) -> ApprovalGrant | None:
        """Wait for the approval store to resolve the request (MVP sync block without busy-waiting)."""
        if not self._approval_store:
            # Fallback if no store provided: instantly reject
            return None
            
        # We wait for up to 300 seconds for a human to resolve the request
        req = self._approval_store.wait_for_resolution(approval_id, timeout_seconds=300)
        
        if req.status == "approved":
            return self._approval_store.get_grant(approval_id)
        return None
        
    def run(self, task_id: str, resume: bool = False) -> Task:
        """Execute the agent loop for a task until completion or failure."""
        task = self._runtime.get_task(task_id)
        
        iterations = 0
        consecutive_failures = 0
        
        if resume and self._checkpoint_store:
            ckpt = self._checkpoint_store.load(task_id)
            if ckpt:
                iterations = ckpt.iteration_count
                consecutive_failures = ckpt.consecutive_failures
                # Hardening fix: actually restore the task into the runtime
                # so a new AgentLoop can pick up exactly where it left off.
                task = self._runtime.restore_task(ckpt.task)
        
        if task.state == TaskState.PENDING:
            task = self._runtime.transition_task(task_id, TaskState.PLANNING)
            self._emit_trace(TraceEventType.TASK_STATE_CHANGED, task_id, new_state=TaskState.PLANNING.value)
            
        consecutive_same_actions = 0
        last_action_repr = None
        error_context = None

        while True:
            if iterations >= self._max_iterations:
                self._runtime.record_observation(task_id, Observation(
                    observation_id=str(uuid4()),
                    source="agent_loop",
                    content="Exceeded maximum iterations"
                ))
                task = self._runtime.transition_task(task_id, TaskState.FAILED)
                self._emit_trace(TraceEventType.TASK_FAILED, task_id, reason="max iterations exceeded")
                if self._checkpoint_store:
                    self._checkpoint_store.delete(task_id)
                return task
                
            task = self._runtime.get_task(task_id)
            if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                if self._checkpoint_store:
                    self._checkpoint_store.delete(task_id)
                return task
                
            # Construct AgentContext
            plan_summary = None
            current_step = None
            if task.plan and task.plan.steps:
                plan_summary = ", ".join([s.description for s in task.plan.steps])
                idx = task.plan.current_step_index
                if idx < len(task.plan.steps):
                    current_step = task.plan.steps[idx].description
                else:
                    current_step = "All planned steps completed"
                    
            available_tools = []
            for tool_meta in self._dispatcher.available_tools():
                available_tools.append({
                    "name": tool_meta.name,
                    "description": tool_meta.description,
                    "capability": tool_meta.capability,
                    "schema": {
                        "required_arguments": list(tool_meta.input_schema.required_arguments),
                    }
                })
                
            completed_actions = []
            for action in task.actions[-self._context_action_history_limit:]:
                completed_actions.append({
                    "action_type": action.request.action_type,
                    "arguments": action.request.arguments
                })
                
            recent_observations = []
            for obs in task.observations[-self._context_observation_limit:]:
                recent_observations.append({
                    "source": obs.source,
                    "content": obs.content,
                })
                
            context = AgentContext(
                task_goal=task.goal,
                plan_summary=plan_summary,
                current_step=current_step,
                completed_actions=completed_actions,
                recent_observations=recent_observations,
                available_tools=available_tools,
                error_context=error_context
            )
            
            # Reset error context for the next iteration unless we set it below
            error_context = None
            
            try:
                proposal = self._llm.propose(context)
            except Exception as e:
                self._runtime.record_observation(task_id, Observation(
                    observation_id=str(uuid4()),
                    source="agent_loop",
                    content=f"LLM Provider Error: {e}"
                ))
                task = self._runtime.transition_task(task_id, TaskState.FAILED)
                self._emit_trace(TraceEventType.TASK_FAILED, task_id, reason=f"LLM Error: {e}")
                if self._checkpoint_store:
                    self._checkpoint_store.delete(task_id)
                return task
                
            iterations += 1
            
            if proposal.action == ProposalAction.PLAN:
                self._emit_trace(TraceEventType.PLAN_PROPOSED, task_id, plan_steps=proposal.plan_steps)
                if proposal.plan_steps:
                    new_plan = Plan(steps=[PlanStep(step_id=str(uuid4()), description=s) for s in proposal.plan_steps])
                    self._runtime.update_plan(task_id, new_plan)
                if task.state != TaskState.RUNNING:
                    task = self._runtime.transition_task(task_id, TaskState.RUNNING)
                self._emit_trace(TraceEventType.PLAN_ACCEPTED, task_id)
                self._save_checkpoint(task, iterations, consecutive_failures)
                continue
                
            elif proposal.action == ProposalAction.TOOL_CALL:
                if not proposal.tool_request:
                    error_context = "TOOL_CALL proposed but tool_request is missing."
                    consecutive_failures += 1
                    continue
                    
                req = proposal.tool_request
                
                self._emit_trace(TraceEventType.ACTION_PROPOSED, task_id, tool_name=req.tool_name, arguments=req.arguments)
                
                action_repr = f"{req.tool_name}({req.arguments})"
                if action_repr == last_action_repr:
                    consecutive_same_actions += 1
                else:
                    consecutive_same_actions = 0
                last_action_repr = action_repr
                
                if consecutive_same_actions >= 3:
                    error_context = "You are repeating the same action without progress. Please rethink your approach."
                    consecutive_failures += 1
                    self._emit_trace(TraceEventType.REPLAN_TRIGGERED, task_id, reason="repeated action")
                    continue
                    
                action_req = ActionRequest(action_type=req.tool_name, arguments=req.arguments)
                self._runtime.record_action(task_id, action_req)
                
                result = self._dispatcher.dispatch(req)
                
                if result.error and result.error.code == "approval_required":
                    self._emit_trace(TraceEventType.APPROVAL_REQUESTED, task_id, capability=result.error.message)
                    if not self._approval_store:
                        obs_content = "Approval required but no approval store configured."
                        result = ToolResult.failure(req.request_id, ToolResultStatus.BLOCKED, "approval_error", obs_content)
                    else:
                        approval = self._approval_store.create_request(ApprovalRequest(
                            approval_id=str(uuid4()),
                            task_id=task_id,
                            request_id=req.request_id,
                            tool_name=req.tool_name,
                            capability=req.capability,
                            arguments=req.arguments,
                            reason=result.error.message,
                        ))
                        
                        self._save_checkpoint(task, iterations, consecutive_failures)
                        task = self._runtime.transition_task(task_id, TaskState.WAITING_FOR_APPROVAL)
                        self._emit_trace(TraceEventType.TASK_STATE_CHANGED, task_id, new_state=TaskState.WAITING_FOR_APPROVAL.value)
                        grant = self._wait_for_approval(approval.approval_id)
                        self._emit_trace(TraceEventType.APPROVAL_RESOLVED, task_id, approved=grant is not None)
                        
                        task = self._runtime.transition_task(task_id, TaskState.RUNNING)
                        self._emit_trace(TraceEventType.TASK_STATE_CHANGED, task_id, new_state=TaskState.RUNNING.value)
                        
                        if grant:
                            self._emit_trace(TraceEventType.TOOL_INVOKED, task_id, tool_name=req.tool_name)
                            result = self._dispatcher.dispatch(req, approval_id=grant.approval_id)
                            self._emit_trace(TraceEventType.TOOL_RESULT, task_id, status=result.status.value, tool_name=req.tool_name)
                        else:
                            obs_content = f"status=blocked error=approval_rejected:Request was rejected"
                            self._runtime.record_observation(task_id, Observation(
                                observation_id=str(uuid4()),
                                source=f"tool:{req.tool_name}",
                                content=obs_content,
                            ))
                            consecutive_failures += 1
                            rec = determine_recovery(FailureCategory.APPROVAL_REJECTION, consecutive_failures, self._max_consecutive_failures)
                            self._emit_trace(TraceEventType.RECOVERY_ATTEMPTED, task_id, strategy=rec.strategy, category=FailureCategory.APPROVAL_REJECTION.value)
                            if rec.strategy == "replan" and task.state != TaskState.PLANNING:
                                error_context = f"{rec.reason}. Last error: {obs_content}. Please replan."
                                task = self._runtime.transition_task(task_id, TaskState.PLANNING)
                                self._emit_trace(TraceEventType.REPLAN_TRIGGERED, task_id, reason="approval_rejection")
                            elif rec.strategy == "abort":
                                task = self._runtime.transition_task(task_id, TaskState.FAILED)
                                self._emit_trace(TraceEventType.TASK_FAILED, task_id, reason="approval_rejection max retries")
                            continue
                else:
                    self._emit_trace(TraceEventType.TOOL_INVOKED, task_id, tool_name=req.tool_name)
                    self._emit_trace(TraceEventType.TOOL_RESULT, task_id, status=result.status.value, tool_name=req.tool_name)
                    
                obs_content = _summarize_result(result)
                self._runtime.record_observation(task_id, Observation(
                    observation_id=str(uuid4()),
                    source=f"tool:{req.tool_name}",
                    content=obs_content,
                    data={
                        "request_id": result.request_id,
                        "status": result.status.value,
                        "output": result.output,
                    }
                ))
                
                if result.status != ToolResultStatus.SUCCESS:
                    consecutive_failures += 1
                    fc = FailureCategory.TOOL_FAILURE
                    if result.error:
                        if result.error.code == "invalid_request":
                            fc = FailureCategory.INVALID_INPUT
                        elif result.error.code == "policy_blocked":
                            fc = FailureCategory.POLICY_REJECTION
                            
                    rec = determine_recovery(fc, consecutive_failures, self._max_consecutive_failures)
                    self._emit_trace(TraceEventType.RECOVERY_ATTEMPTED, task_id, strategy=rec.strategy, category=fc.value)
                    if rec.strategy == "replan" and task.state != TaskState.PLANNING:
                        error_context = f"{rec.reason}. Last error: {obs_content}. Please replan."
                        task = self._runtime.transition_task(task_id, TaskState.PLANNING)
                        self._emit_trace(TraceEventType.REPLAN_TRIGGERED, task_id, reason=fc.value)
                    elif rec.strategy == "abort":
                        task = self._runtime.transition_task(task_id, TaskState.FAILED)
                        self._emit_trace(TraceEventType.TASK_FAILED, task_id, reason=f"{fc.value} abort")
                else:
                    consecutive_failures = 0
                    task = self._runtime.get_task(task_id)
                    if task.plan and task.plan.current_step_index < len(task.plan.steps):
                        new_plan = task.plan
                        new_plan.current_step_index += 1
                        self._runtime.update_plan(task_id, new_plan)
                
                self._save_checkpoint(self._runtime.get_task(task_id), iterations, consecutive_failures)
                        
            elif proposal.action == ProposalAction.COMPLETE:
                self._runtime.record_observation(task_id, Observation(
                    observation_id=str(uuid4()),
                    source="agent_loop",
                    content=f"LLM completed task: {proposal.completion_reason}"
                ))
                task = self._runtime.transition_task(task_id, TaskState.VERIFYING)
                self._emit_trace(TraceEventType.TASK_STATE_CHANGED, task_id, new_state=TaskState.VERIFYING.value)
                
                if self._verification_checks and self._sandbox:
                    self._emit_trace(TraceEventType.VERIFICATION_STARTED, task_id, checks=len(self._verification_checks))
                    # Run verifications (MVP: run all checks configured, they could come from task args in the future)
                    all_passed = True
                    for check, criteria in self._verification_checks:
                        res = check.verify(self._sandbox, criteria)
                        self._emit_trace(TraceEventType.VERIFICATION_RESULT, task_id, check_type=check.__class__.__name__, status=res.status.value, reason=res.reason)
                        if res.status == "failed":
                            all_passed = False
                            error_context = f"Verification failed: {res.reason}. Evidence: {res.evidence}"
                            self._runtime.record_observation(task_id, Observation(
                                observation_id=str(uuid4()), source="verification", content=error_context
                            ))
                            break
                            
                    if not all_passed:
                        task = self._runtime.transition_task(task_id, TaskState.RUNNING)
                        self._emit_trace(TraceEventType.TASK_STATE_CHANGED, task_id, new_state=TaskState.RUNNING.value)
                        consecutive_failures += 1
                        rec = determine_recovery(FailureCategory.VERIFICATION_FAILURE, consecutive_failures, self._max_consecutive_failures)
                        self._emit_trace(TraceEventType.RECOVERY_ATTEMPTED, task_id, strategy=rec.strategy, category="verification_failure")
                        if rec.strategy == "replan":
                            task = self._runtime.transition_task(task_id, TaskState.PLANNING)
                            self._emit_trace(TraceEventType.REPLAN_TRIGGERED, task_id, reason="verification_failure")
                        elif rec.strategy == "abort":
                            task = self._runtime.transition_task(task_id, TaskState.FAILED)
                            self._emit_trace(TraceEventType.TASK_FAILED, task_id, reason="verification_failure abort")
                        continue
                
                task = self._runtime.transition_task(task_id, TaskState.COMPLETED)
                self._emit_trace(TraceEventType.TASK_COMPLETED, task_id, reason=proposal.completion_reason)
                if self._checkpoint_store:
                    self._checkpoint_store.delete(task_id)
                return task
                
            elif proposal.action == ProposalAction.GIVE_UP:
                self._runtime.record_observation(task_id, Observation(
                    observation_id=str(uuid4()),
                    source="agent_loop",
                    content=f"LLM gave up: {proposal.completion_reason or proposal.reasoning}"
                ))
                task = self._runtime.transition_task(task_id, TaskState.FAILED)
                self._emit_trace(TraceEventType.TASK_FAILED, task_id, reason=proposal.completion_reason or proposal.reasoning)
                if self._checkpoint_store:
                    self._checkpoint_store.delete(task_id)
                return task

            else:
                self._runtime.record_observation(task_id, Observation(
                    observation_id=str(uuid4()),
                    source="agent_loop",
                    content=f"LLM proposed unknown action: {proposal.action}"
                ))
                task = self._runtime.transition_task(task_id, TaskState.FAILED)
                self._emit_trace(TraceEventType.TASK_FAILED, task_id, reason=proposal.completion_reason or proposal.reasoning)
                if self._checkpoint_store:
                    self._checkpoint_store.delete(task_id)
                return task
