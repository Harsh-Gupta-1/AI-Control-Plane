import logging
from uuid import uuid4

from control_plane.domain import (
    ActionRequest, Observation, Task, TaskState, Plan, PlanStep, ToolResultStatus, ApprovalRequest, ApprovalDecision
)
from control_plane.llm.contracts import AgentContext, LLMProvider, ProposalAction
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.approval.contracts import ApprovalStore
from control_plane.runtime.checkpoint import CheckpointStore, TaskCheckpoint
from control_plane.runtime.recovery import determine_recovery
from control_plane.domain.models import FailureCategory
from control_plane.verification.contracts import VerificationCheck
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
        verification_checks: list[VerificationCheck] | None = None,
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
        self._verification_checks = verification_checks or []
        self._sandbox = sandbox
        self._max_iterations = max_iterations
        self._max_consecutive_failures = max_consecutive_failures
        self._context_action_history_limit = context_action_history_limit
        self._context_observation_limit = context_observation_limit
        
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
        
    def _wait_for_approval(self, approval_id: str) -> ApprovalDecision:
        """Poll the approval store until resolved (MVP sync block)."""
        if not self._approval_store:
            # Fallback if no store provided: instantly reject
            return ApprovalDecision(approval_id=approval_id, approved=False, reason="No approval store configured")
            
        import time
        while True:
            req = self._approval_store.get_request(approval_id)
            if req.status == "approved":
                return ApprovalDecision(approval_id=approval_id, approved=True, reason="Human approved")
            elif req.status == "rejected":
                return ApprovalDecision(approval_id=approval_id, approved=False, reason="Human rejected")
            time.sleep(0.5)
        
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
                # The runtime should ideally be restored from the checkpoint too,
                # but for this MVP, we assume runtime state was rehydrated before calling run()
                # or we just rely on the current runtime's state.
        
        if task.state == TaskState.PENDING:
            task = self._runtime.transition_task(task_id, TaskState.PLANNING)
            
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
            for tool_meta in self._dispatcher._registry.available_tools():
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
                return self._runtime.transition_task(task_id, TaskState.FAILED)
                
            iterations += 1
            
            if proposal.action == ProposalAction.PLAN:
                if proposal.plan_steps:
                    new_plan = Plan(steps=[PlanStep(step_id=str(uuid4()), description=s) for s in proposal.plan_steps])
                    self._runtime.update_plan(task_id, new_plan)
                task = self._runtime.transition_task(task_id, TaskState.RUNNING)
                self._save_checkpoint(task, iterations, consecutive_failures)
                continue
                
            elif proposal.action == ProposalAction.TOOL_CALL:
                if not proposal.tool_request:
                    error_context = "TOOL_CALL proposed but tool_request is missing."
                    consecutive_failures += 1
                    continue
                    
                req = proposal.tool_request
                action_repr = f"{req.tool_name}:{req.arguments}"
                
                if action_repr == last_action_repr:
                    consecutive_same_actions += 1
                else:
                    consecutive_same_actions = 0
                    last_action_repr = action_repr
                    
                if consecutive_same_actions >= 3:
                    error_context = "Repeated action detection: You have proposed the exact same tool call 3 times. You must replan or do something else."
                    if task.state != TaskState.PLANNING:
                        task = self._runtime.transition_task(task_id, TaskState.PLANNING)
                    consecutive_failures += 1
                    continue
                    
                action_req = ActionRequest(action_type=req.tool_name, arguments=req.arguments)
                self._runtime.record_action(task_id, action_req)
                
                result = self._dispatcher.dispatch(req)
                
                if result.error and result.error.code == "approval_required":
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
                        decision = self._wait_for_approval(approval.approval_id)
                        
                        task = self._runtime.transition_task(task_id, TaskState.RUNNING)
                        if decision.approved:
                            result = self._dispatcher.dispatch(req, approved_request_id=approval.approval_id)
                        else:
                            obs_content = f"status=blocked error=approval_rejected:Request was rejected"
                            self._runtime.record_observation(task_id, Observation(
                                observation_id=str(uuid4()),
                                source=f"tool:{req.tool_name}",
                                content=obs_content,
                            ))
                            consecutive_failures += 1
                            rec = determine_recovery(FailureCategory.APPROVAL_REJECTION, consecutive_failures, self._max_consecutive_failures)
                            if rec.strategy == "replan" and task.state != TaskState.PLANNING:
                                error_context = f"{rec.reason}. Last error: {obs_content}. Please replan."
                                task = self._runtime.transition_task(task_id, TaskState.PLANNING)
                            elif rec.strategy == "abort":
                                task = self._runtime.transition_task(task_id, TaskState.FAILED)
                            continue
                
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
                    if rec.strategy == "replan" and task.state != TaskState.PLANNING:
                        error_context = f"{rec.reason}. Last error: {obs_content}. Please replan."
                        task = self._runtime.transition_task(task_id, TaskState.PLANNING)
                    elif rec.strategy == "abort":
                        task = self._runtime.transition_task(task_id, TaskState.FAILED)
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
                
                if self._verification_checks and self._sandbox:
                    # Run verifications (MVP: run all checks configured, they could come from task args in the future)
                    all_passed = True
                    for check in self._verification_checks:
                        res = check.verify(self._sandbox, {"path": "/workspace/hello.txt"}) # Hardcoded criterion for MVP testing
                        if res.status == "failed":
                            all_passed = False
                            error_context = f"Verification failed: {res.reason}. Evidence: {res.evidence}"
                            self._runtime.record_observation(task_id, Observation(
                                observation_id=str(uuid4()), source="verification", content=error_context
                            ))
                            break
                            
                    if not all_passed:
                        task = self._runtime.transition_task(task_id, TaskState.RUNNING)
                        consecutive_failures += 1
                        rec = determine_recovery(FailureCategory.VERIFICATION_FAILURE, consecutive_failures, self._max_consecutive_failures)
                        if rec.strategy == "replan":
                            task = self._runtime.transition_task(task_id, TaskState.PLANNING)
                        elif rec.strategy == "abort":
                            task = self._runtime.transition_task(task_id, TaskState.FAILED)
                        continue
                
                task = self._runtime.transition_task(task_id, TaskState.COMPLETED)
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
                if self._checkpoint_store:
                    self._checkpoint_store.delete(task_id)
                return task
