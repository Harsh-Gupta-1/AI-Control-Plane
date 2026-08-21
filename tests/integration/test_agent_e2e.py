import pytest
import docker
import time
from control_plane.sandbox.docker_sandbox import DockerSandbox
from control_plane.domain import TaskState, ToolRequest
from control_plane.llm.contracts import LLMProposal, ProposalAction
from control_plane.llm.fake_provider import FakeLLMProvider
from control_plane.policy.gate import AllowListedPolicyGate
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.runtime.agent_loop import AgentLoop
from control_plane.tools.dispatcher import ToolDispatcher
from control_plane.tools.registry import ToolRegistry
from control_plane.tools.filesystem import WriteFileTool, ReadFileTool

try:
    client = docker.from_env()
    client.ping()
    DOCKER_AVAILABLE = True
except Exception:
    DOCKER_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker is not available")

@pytest.fixture
def sandbox():
    sb = DockerSandbox()
    sb.start()
    yield sb
    sb.stop()
    sb.destroy()

def test_agent_e2e_workflow(sandbox):
    runtime = TaskRuntime()
    registry = ToolRegistry()
    registry.register(WriteFileTool(sandbox))
    registry.register(ReadFileTool(sandbox))
    dispatcher = ToolDispatcher(registry, AllowListedPolicyGate(frozenset({"filesystem.write", "filesystem.read"})))
    
    # FakeLLM proposes: PLAN → write_file tool call → read_file tool call (verify) → COMPLETE
    write_req = ToolRequest(
        tool_name="write_file",
        capability="filesystem.write",
        arguments={"path": "/workspace/hello.txt", "content": "Hello World"}
    )
    
    read_req = ToolRequest(
        tool_name="read_file",
        capability="filesystem.read",
        arguments={"path": "/workspace/hello.txt"}
    )
    
    proposals = [
        LLMProposal(action=ProposalAction.PLAN, plan_steps=["Write file", "Read file", "Done"]),
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=write_req),
        LLMProposal(action=ProposalAction.TOOL_CALL, tool_request=read_req),
        LLMProposal(action=ProposalAction.COMPLETE, completion_reason="Verified")
    ]
    
    llm = FakeLLMProvider(proposals)
    loop = AgentLoop(runtime, dispatcher, llm)
    
    task = runtime.create_task("Create a file at /workspace/hello.txt containing 'Hello World'")
    final_task = loop.run(task.task_id)
    
    assert final_task.state == TaskState.COMPLETED
    
    # Verify file actually exists inside sandbox
    result = sandbox.execute(["cat", "/workspace/hello.txt"], timeout_seconds=5)
    assert result.exit_code == 0
    assert result.stdout.strip() == "Hello World"
