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
            reason = event.payload.get("reason", "")
            payload_str = f"Task finished successfully. {reason}"
        elif event.event_type == TraceEventType.TASK_FAILED:
            payload_str = f"Task failed: {event.payload.get('error', '')}"
        elif event.event_type == TraceEventType.TASK_CREATED:
            payload_str = f"Goal: {event.payload.get('goal', '')}"
            
        if payload_str:
            print(f"{label_str} {payload_str}")

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
        
    if len(argv) > 0 and argv[0] not in ["computer", "-h", "--help"] and argv[0].startswith("--"):
        # Legacy mode: it's a run command, let's insert 'run'
        argv = ["run"] + argv
        
    parser = argparse.ArgumentParser(description="AI Computer Control Plane CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Run a task")
    run_parser.add_argument("--goal", type=str, required=True, help="The task goal string.")
    run_parser.add_argument("--trace-out", type=str, default="trace.jsonl", help="Path to write the JSON-lines trace.")
    run_parser.add_argument("--real-sandbox", action="store_true", help="Use real DockerSandbox instead of FakeSandbox.")
    run_parser.add_argument("--llm", type=str, choices=["fake", "ollama", "groq"], default="ollama", help="LLM provider to use.")
    run_parser.add_argument("--model", type=str, default="qwen2.5-coder:7b", help="Model to use (default: qwen2.5-coder:7b for ollama, qwen/qwen3.6-27b for groq).")
    run_parser.add_argument("--groq-key", type=str, help="Groq API key if using --llm groq")
    run_parser.add_argument("--auto-approve", action="store_true", help="Automatically approve actions (default in fake mode).")
    run_parser.add_argument("--no-auto-approve", action="store_true", help="Disable automatic approval.")
    run_parser.add_argument("--shared-dir", type=str, help="Host directory to mount into the sandbox at /shared.")
    run_parser.add_argument("--computer-id", type=str, help="Attach to an existing persistent computer session.")
    run_parser.add_argument("--destroy-on-exit", action="store_true", help="Destroy the computer after task finishes.")
    
    # Subcommand: computer
    comp_parser = subparsers.add_parser("computer", help="Manage persistent computers")
    comp_subparsers = comp_parser.add_subparsers(dest="comp_cmd", help="Computer command")
    
    comp_subparsers.add_parser("list", help="List all computers")
    create_parser = comp_subparsers.add_parser("create", help="Create a new computer")
    create_parser.add_argument("--shared-dir", type=str, help="Host directory to mount into the sandbox at /shared.")
    
    start_parser = comp_subparsers.add_parser("start", help="Start a computer")
    start_parser.add_argument("id", type=str, help="Computer ID")
    
    stop_parser = comp_subparsers.add_parser("stop", help="Stop a computer")
    stop_parser.add_argument("id", type=str, help="Computer ID")
    
    destroy_parser = comp_subparsers.add_parser("destroy", help="Destroy a computer")
    destroy_parser.add_argument("id", type=str, help="Computer ID")
    
    snapshot_parser = comp_subparsers.add_parser("snapshot", help="Snapshot a computer")
    snapshot_parser.add_argument("id", type=str, help="Computer ID")
    
    rollback_parser = comp_subparsers.add_parser("rollback", help="Rollback a computer")
    rollback_parser.add_argument("id", type=str, help="Computer ID")
    rollback_parser.add_argument("snapshot_id", type=str, help="Snapshot ID")
    
    extract_parser = comp_subparsers.add_parser("extract", help="Extract an artifact from a computer")
    extract_parser.add_argument("id", type=str, help="Computer ID")
    extract_parser.add_argument("remote_path", type=str, help="Path inside the sandbox")
    extract_parser.add_argument("local_path", type=str, help="Destination path on host")
    
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        sys.exit(1)
        
    from control_plane.sandbox.manager import ComputerManager
    manager = ComputerManager()
    
    if args.command == "computer":
        if not args.comp_cmd:
            comp_parser.print_help()
            sys.exit(1)
        if args.comp_cmd == "list":
            comps = manager.list_computers()
            if not comps:
                print("No computers found.")
            else:
                for c in comps:
                    print(f"ID: {c.id} | Status: {c.status.value} | Created: {c.created_at}")
        elif args.comp_cmd == "create":
            c = manager.create_computer(shared_dir=args.shared_dir)
            print(f"Created computer: {c.id}")
        elif args.comp_cmd == "start":
            manager.start_computer(args.id)
            print(f"Started computer: {args.id}")
        elif args.comp_cmd == "stop":
            manager.stop_computer(args.id)
            print(f"Stopped computer: {args.id}")
        elif args.comp_cmd == "destroy":
            manager.destroy_computer(args.id)
            print(f"Destroyed computer: {args.id}")
        elif args.comp_cmd == "snapshot":
            snap_id = manager.snapshot_computer(args.id)
            print(f"Created snapshot: {snap_id} for computer {args.id}")
        elif args.comp_cmd == "rollback":
            manager.rollback_computer(args.id, args.snapshot_id)
            print(f"Rolled back computer {args.id} to snapshot {args.snapshot_id}")
        elif args.comp_cmd == "extract":
            manager.extract_artifact(args.id, args.remote_path, args.local_path)
            print(f"Extracted {args.remote_path} to {args.local_path}")
        sys.exit(0)
    
    # Run command logic below...
    # Determine auto-approve default based on mode
    auto_approve = args.auto_approve
    if args.llm == "fake" and not args.no_auto_approve:
        auto_approve = True

    # 1. Setup Sandbox
    computer_id = None
    if args.real_sandbox:
        try:
            if args.computer_id:
                computer_id = args.computer_id
                sandbox = manager.get_sandbox(computer_id)
                # Ensure it's running
                from control_plane.domain.models import ComputerStatus
                if manager.get_computer(computer_id).status != ComputerStatus.RUNNING:
                    manager.start_computer(computer_id)
            else:
                # Create a temporary computer for this run
                comp = manager.create_computer(shared_dir=args.shared_dir)
                computer_id = comp.id
                sandbox = manager.start_computer(computer_id)
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
            from control_plane.tools.filesystem import WriteFileTool, ReadFileTool
            from control_plane.tools.terminal import (
                ExecuteCommandTool,
                ExecuteBackgroundCommandTool,
                GetBackgroundCommandStatusTool,
                StopBackgroundCommandTool,
            )
            registry.register(WriteFileTool(sandbox))
            registry.register(ReadFileTool(sandbox))
            registry.register(ExecuteCommandTool(sandbox))
            registry.register(ExecuteBackgroundCommandTool(sandbox))
            registry.register(GetBackgroundCommandStatusTool(sandbox))
            registry.register(StopBackgroundCommandTool(sandbox))

        # 3. Setup Approval
        class DemoApprovalStore(InMemoryApprovalStore):
            def wait_for_resolution(self, approval_id, timeout_seconds):
                from control_plane.domain.models import ApprovalDecision
                if auto_approve:
                    self.resolve(ApprovalDecision(approval_id, True))
                else:
                    ans = input(f"\n[?] Policy Gate: Approve this action? (y/N): ")
                    self.resolve(ApprovalDecision(approval_id, ans.strip().lower() == 'y'))
                return super().wait_for_resolution(approval_id, timeout_seconds)
                
        approval_store = DemoApprovalStore()
        authorizer = DefaultApprovalAuthorizer(approval_store)

        # 4. Setup Policy & Dispatcher
        policy_gate = CapabilityPolicyGate()
        dispatcher = ToolDispatcher(registry, policy_gate, authorizer)

        # 5. Setup LLM
        if args.llm == "fake":
            llm_provider = FakeLLMProvider()
        elif args.llm == "groq":
            from control_plane.llm.groq_provider import GroqProvider
            if not args.groq_key:
                print("Error: --groq-key is required when using --llm groq")
                return 1
            model_name = args.model if args.model != "qwen2.5-coder:7b" else "qwen/qwen3.6-27b"
            llm_provider = GroqProvider(api_key=args.groq_key, model=model_name)
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
        if args.real_sandbox and computer_id:
            if args.destroy_on_exit:
                manager.destroy_computer(computer_id)
            # otherwise, leave it running or stop it?
            # By default, leave it as is so it's persistent!
        elif not args.real_sandbox:
            sandbox.stop()
            sandbox.destroy()

if __name__ == "__main__":
    main()
