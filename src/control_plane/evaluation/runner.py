from dataclasses import dataclass
from typing import Optional
import time
from uuid import uuid4

from control_plane.evaluation.tasks import EvalTask
from control_plane.llm.contracts import LLMProvider
from control_plane.policy.gate import PolicyGate
from control_plane.sandbox.docker_sandbox import DockerSandbox
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.tools.registry import ToolRegistry
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.runtime.agent_loop import AgentLoop
from control_plane.tracing.contracts import JsonFileTraceSink

@dataclass
class EvalResult:
    task: EvalTask
    outcome: str
    actual_outcome: str
    tools_used: list[str]
    iterations: int
    duration_seconds: float
    trace_path: str | None
    failure_reason: str | None = None

class EvaluationRunner:
    def __init__(self, sandbox_image: str, llm_provider: LLMProvider, policy_gate: PolicyGate):
        self.sandbox_image = sandbox_image
        self.llm_provider = llm_provider
        self.policy_gate = policy_gate
        self._registry = ToolRegistry() # Assuming default tools will be registered for now

    def run_task(self, task: EvalTask) -> EvalResult:
        sandbox = DockerSandbox(image=self.sandbox_image)
        sandbox.start()
        
        # Setup
        for setup_cmd in task.setup:
            if "command" in setup_cmd:
                sandbox.execute(["sh", "-c", setup_cmd["command"]])
                
        from control_plane.tools.filesystem import WriteFileTool, ReadFileTool, DeleteFileTool
        from control_plane.tools.terminal import (
            ExecuteCommandTool,
            ExecuteBackgroundCommandTool,
            GetBackgroundCommandStatusTool,
            StopBackgroundCommandTool,
        )
        from control_plane.tools.browser import BrowserNavigateTool, BrowserDownloadTool, BrowserExtractTool, BrowserClickTool, BrowserTypeTool
        
        registry = ToolRegistry()
        registry.register(WriteFileTool(sandbox))
        registry.register(ReadFileTool(sandbox))
        registry.register(DeleteFileTool(sandbox))
        registry.register(ExecuteCommandTool(sandbox))
        registry.register(ExecuteBackgroundCommandTool(sandbox))
        registry.register(GetBackgroundCommandStatusTool(sandbox))
        registry.register(StopBackgroundCommandTool(sandbox))
        registry.register(BrowserNavigateTool(sandbox))
        registry.register(BrowserDownloadTool(sandbox))
        registry.register(BrowserExtractTool(sandbox))
        registry.register(BrowserClickTool(sandbox))
        registry.register(BrowserTypeTool(sandbox))
        
        runtime = TaskRuntime()
        dispatcher = ToolDispatcher(registry, self.policy_gate)
        
        trace_path = f"traces/{task.task_id}_{int(time.time())}.jsonl"
        trace_sink = JsonFileTraceSink(trace_path)
        from control_plane.verification.checks import FileExistsCheck, FileContentCheck, CommandSuccessCheck
        
        checks = []
        for crit in task.verification_criteria:
            c_type = crit.get("check")
            if c_type == "file_exists":
                checks.append((FileExistsCheck(), crit))
            elif c_type == "file_content":
                checks.append((FileContentCheck(), crit))
            elif c_type == "command_success":
                checks.append((CommandSuccessCheck(), crit))
        
        loop = AgentLoop(
            runtime=runtime,
            dispatcher=dispatcher,
            llm=self.llm_provider,
            trace_sink=trace_sink,
            sandbox=sandbox,
            verification_checks=checks,
            max_iterations=task.max_iterations
        )
        
        agent_task = runtime.create_task(task.goal)
        
        start_time = time.time()
        final_task = loop.run(agent_task.task_id)
        duration = time.time() - start_time
        
        # Determine tools used
        tools_used = []
        for action in final_task.actions:
            tool_name = action.request.action_type
            if tool_name not in tools_used:
                tools_used.append(tool_name)
                
        # For MVP, assume it passed if final_task.state.value matched expected outcome
        # (Actually, "completed" vs TaskState.COMPLETED.value)
        actual_outcome = final_task.state.value
        
        # Very simple validation of expected tools
        missing_tools = [t for t in task.expected_tools if t not in tools_used]
        
        outcome = "passed"
        reason = None
        if actual_outcome != task.expected_outcome:
            outcome = "failed"
            reason = f"Expected {task.expected_outcome}, got {actual_outcome}"
        elif missing_tools:
            outcome = "failed"
            reason = f"Missing expected tools: {missing_tools}"
            
        sandbox.stop()
        sandbox.destroy()
        
        return EvalResult(
            task=task,
            outcome=outcome,
            actual_outcome=actual_outcome,
            tools_used=tools_used,
            iterations=len(final_task.actions),
            duration_seconds=duration,
            trace_path=trace_path,
            failure_reason=reason
        )

    def run_suite(self, tasks: list[EvalTask]) -> list[EvalResult]:
        results = []
        for task in tasks:
            print(f"Running task {task.task_id}...")
            result = self.run_task(task)
            results.append(result)
        return results

    def print_report(self, results: list[EvalResult]) -> None:
        print("\nEvaluation Report")
        print("=================")
        passed = sum(1 for r in results if r.outcome == "passed")
        total = len(results)
        print(f"Passed: {passed}/{total}\n")
        
        for r in results:
            print(f"[{r.outcome.upper()}] {r.task.task_id}")
            print(f"  Expected: {r.task.expected_outcome} | Actual: {r.actual_outcome}")
            print(f"  Duration: {r.duration_seconds:.2f}s | Iterations: {r.iterations}")
            print(f"  Tools: {', '.join(r.tools_used)}")
            if r.failure_reason:
                print(f"  Reason: {r.failure_reason}")
            if r.trace_path:
                print(f"  Trace: {r.trace_path}")
            print()
