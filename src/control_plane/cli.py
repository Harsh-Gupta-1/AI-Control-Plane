"""Command-line interface for the AI Computer Control Plane."""

import argparse
import sys
import json
from pathlib import Path

from control_plane.domain import Task, TaskState
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.tools.registry import ToolRegistry
from control_plane.policy.gate import CapabilityPolicyGate
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.approval.in_memory import InMemoryApprovalStore, DefaultApprovalAuthorizer
from control_plane.runtime.agent_loop import AgentLoop
from control_plane.tracing.contracts import TraceSink, TraceEvent, TraceEventType, JsonFileTraceSink

# Import Fakes
from tests.unit.fake_sandbox import FakeSandbox
from control_plane.tools import Tool, ToolInputSchema, ToolMetadata
from control_plane.domain import ToolRequest, ToolResult, ToolResultStatus

class FastFakeTool(Tool):
    def __init__(self, name: str, capability: str, sandbox=None) -> None:
        self._metadata = ToolMetadata(
            name=name,
            description="Fake tool for testing",
            capability=capability,
            input_schema=ToolInputSchema(required_arguments=frozenset()),
        )
        self.sandbox = sandbox

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def _execute(self, request: ToolRequest) -> ToolResult:
        return ToolResult(
            request_id=request.request_id,
            status=ToolResultStatus.SUCCESS,
            output={"fake_success": True},
        )

class FakeLLMProvider:
    """A fake LLM provider that yields a canned sequence for the CLI demo."""
    def __init__(self):
        self._step = 0
        
    def propose(self, context) -> 'LLMProposal':
        from control_plane.llm.contracts import LLMProposal, ProposalAction
        from control_plane.domain.models import ToolRequest
        from uuid import uuid4
        self._step += 1
        
        if self._step == 1:
            return LLMProposal(
                action=ProposalAction.PLAN,
                plan_steps=["Create a file", "Read the file"],
                reasoning="I need to create and read a file."
            )
        elif self._step == 2:
            return LLMProposal(
                action=ProposalAction.TOOL_CALL,
                tool_request=ToolRequest(
                    tool_name="write_file",
                    capability="filesystem.write",
                    arguments={"path": "/workspace/notes.txt", "content": "hello"},
                    request_id=str(uuid4())
                ),
                reasoning="Creating the file."
            )
        elif self._step == 3:
            return LLMProposal(
                action=ProposalAction.TOOL_CALL,
                tool_request=ToolRequest(
                    tool_name="read_file",
                    capability="filesystem.read",
                    arguments={"path": "/workspace/notes.txt"},
                    request_id=str(uuid4())
                ),
                reasoning="Reading the file."
            )
        else:
            return LLMProposal(
                action=ProposalAction.COMPLETE,
                completion_reason="File created and read successfully.",
                reasoning="Task is done."
            )

class TeeTraceSink(TraceSink):
    """Writes traces to a file and formats them cleanly to stdout."""
    
    def __init__(self, file_sink: JsonFileTraceSink, is_demo_mode: bool):
        self.file_sink = file_sink
        self.is_demo_mode = is_demo_mode
        
    def emit(self, event: TraceEvent) -> None:
        # First, delegate to the file sink
        self.file_sink.emit(event)
        
        # Then, print a readable summary to stdout
        type_to_label = {
            TraceEventType.TASK_CREATED: "TASK",
            TraceEventType.PLAN_PROPOSED: "PLAN",
            TraceEventType.ACTION_PROPOSED: "ACTION",
            TraceEventType.POLICY_EVALUATED: "POLICY",
            TraceEventType.APPROVAL_REQUESTED: "APPROVAL",
            TraceEventType.APPROVAL_RESOLVED: "APPROVAL",
            TraceEventType.TOOL_INVOKED: "TOOL",
            TraceEventType.TOOL_RESULT: "TOOL",
            TraceEventType.VERIFICATION_STARTED: "VERIFY",
            TraceEventType.VERIFICATION_RESULT: "VERIFY",
            TraceEventType.TASK_COMPLETED: "COMPLETE",
            TraceEventType.TASK_FAILED: "FAILED",
        }
        
        label = type_to_label.get(event.event_type, event.event_type.name)
        label_str = f"[{label}]".ljust(12)
        
        payload_str = ""
        if event.event_type == TraceEventType.PLAN_PROPOSED:
            num_steps = len(event.payload.get("steps", []))
            payload_str = f"{num_steps} steps proposed"
        elif event.event_type == TraceEventType.ACTION_PROPOSED:
            tool = event.payload.get("tool_name", "")
            args = event.payload.get("arguments", {})
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            payload_str = f"{tool}({args_str})"
        elif event.event_type == TraceEventType.POLICY_EVALUATED:
            tool = event.payload.get("tool_name", "")
            decision = event.payload.get("decision", "")
            payload_str = f"{tool} -> policy={decision}"
        elif event.event_type == TraceEventType.APPROVAL_RESOLVED:
            decision = event.payload.get("decision", "")
            if self.is_demo_mode:
                payload_str = f"{decision.lower()} (demo mode)"
            else:
                payload_str = f"{decision.lower()}"
        elif event.event_type == TraceEventType.TOOL_RESULT:
            tool = event.payload.get("tool_name", "")
            status = event.payload.get("status", "")
            payload_str = f"{tool} -> {status}"
        elif event.event_type == TraceEventType.VERIFICATION_RESULT:
            result = event.payload.get("status", "")
            payload_str = f"Verification -> {result}"
        elif event.event_type == TraceEventType.TASK_COMPLETED:
            payload_str = "Task finished successfully"
        elif event.event_type == TraceEventType.TASK_FAILED:
            payload_str = f"Task failed: {event.payload.get('error', '')}"
        elif event.event_type == TraceEventType.TASK_CREATED:
            payload_str = f"Goal: {event.payload.get('goal', '')}"
            
        if payload_str:
            print(f"{label_str} {payload_str}")

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
        
    parser = argparse.ArgumentParser(description="AI Computer Control Plane CLI")
    parser.add_argument("--goal", type=str, required=True, help="The task goal string.")
    parser.add_argument("--trace-out", type=str, default="trace.jsonl", help="Path to write the JSON-lines trace.")
    parser.add_argument("--real-sandbox", action="store_true", help="Use real DockerSandbox instead of FakeSandbox.")
    parser.add_argument("--llm", type=str, choices=["fake", "ollama"], default="fake", help="LLM provider to use.")
    parser.add_argument("--model", type=str, default="qwen2.5-coder:7b", help="Model to use if --llm ollama (default: qwen2.5-coder:7b).")
    parser.add_argument("--auto-approve", action="store_true", help="Automatically approve actions (default in fake mode).")
    parser.add_argument("--no-auto-approve", action="store_true", help="Disable automatic approval.")
    
    args = parser.parse_args(argv)
    
    # Determine auto-approve default based on mode
    auto_approve = args.auto_approve
    if args.llm == "fake" and not args.no_auto_approve:
        auto_approve = True

    # 1. Setup Sandbox
    if args.real_sandbox:
        try:
            from control_plane.sandbox.docker_sandbox import DockerSandbox
            import docker
            docker.from_env() # test connection
            sandbox = DockerSandbox()
            sandbox.start()
        except Exception as e:
            print(f"Error initializing Docker sandbox: {e}")
            sys.exit(1)
    else:
        sandbox = FakeSandbox([])
        sandbox.start()

    try:
        # 2. Setup Tools
        registry = ToolRegistry()
        if not args.real_sandbox:
            # We use fake tools for fake sandbox
            registry.register(FastFakeTool("write_file", "filesystem.write", sandbox))
            registry.register(FastFakeTool("read_file", "filesystem.read", sandbox))
        else:
            # We would register real tools here if requested, 
            # but for demo we can just stick to simple filesystem tools.
            from control_plane.tools.filesystem import FilesystemWriteTool, FilesystemReadTool
            registry.register(FilesystemWriteTool(sandbox))
            registry.register(FilesystemReadTool(sandbox))

        # 3. Setup Policy & Dispatcher
        policy_gate = CapabilityPolicyGate()
        dispatcher = ToolDispatcher(registry, policy_gate)

        # 4. Setup Approval
        class DemoApprovalStore(InMemoryApprovalStore):
            def wait_for_resolution(self, approval_id, timeout_seconds):
                if auto_approve:
                    from control_plane.domain.models import ApprovalDecision
                    self.resolve(ApprovalDecision(approval_id, True))
                return super().wait_for_resolution(approval_id, timeout_seconds)
                
        approval_store = DemoApprovalStore()
        authorizer = DefaultApprovalAuthorizer(approval_store)

        # 5. Setup LLM
        if args.llm == "fake":
            llm_provider = FakeLLMProvider()
        else:
            from control_plane.llm.ollama_provider import OllamaProvider
            llm_provider = OllamaProvider(base_url="http://localhost:11434", model=args.model)

        # 6. Setup Tracing
        trace_path = Path(args.trace_out)
        json_sink = JsonFileTraceSink(trace_path)
        trace_sink = TeeTraceSink(json_sink, is_demo_mode=auto_approve)

        # 7. Create Task & Loop
        runtime = TaskRuntime()
        task = runtime.create_task(args.goal)
        
        loop = AgentLoop(
            runtime=runtime,
            llm=llm_provider,
            dispatcher=dispatcher,
            approval_store=approval_store,
            sandbox=sandbox,
            trace_sink=trace_sink
        )

        # 8. Run
        task = loop.run(task.task_id)

        print(f"\nTask State: {task.state.name}")
        print(f"Trace written to: {trace_path.absolute()}")
        
    finally:
        sandbox.stop()
        sandbox.destroy()

if __name__ == "__main__":
    main()
