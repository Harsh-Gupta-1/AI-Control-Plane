import pytest
import urllib.request
import urllib.error
from control_plane.llm.contracts import AgentContext, ProposalAction
from control_plane.llm.ollama_provider import OllamaProvider

def check_ollama_running():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False

OLLAMA_AVAILABLE = check_ollama_running()
pytestmark = pytest.mark.skipif(not OLLAMA_AVAILABLE, reason="Ollama is not running locally on port 11434")

def test_ollama_propose_simple():
    provider = OllamaProvider(model="qwen2.5:7b")
    ctx = AgentContext(task_goal="Say 'hello world' and then complete.")
    proposal = provider.propose(ctx)
    
    assert proposal.action in [ProposalAction.PLAN, ProposalAction.TOOL_CALL, ProposalAction.COMPLETE, ProposalAction.GIVE_UP]
    
def test_ollama_connection_failure():
    # Point to a wrong port
    provider = OllamaProvider(base_url="http://localhost:11435")
    ctx = AgentContext(task_goal="test")
    
    with pytest.raises(Exception) as exc:
        provider.propose(ctx)
        
    assert "Connection to Ollama failed" in str(exc.value)
