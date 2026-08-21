from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from control_plane.domain import ToolRequest

@dataclass
class AgentContext:
    """Bounded structured context provided to the LLM."""
    task_goal: str
    plan_summary: str | None = None
    current_step: str | None = None
    completed_actions: list[dict] = field(default_factory=list)
    recent_observations: list[dict] = field(default_factory=list)
    available_tools: list[dict] = field(default_factory=list)
    allowed_capabilities: frozenset[str] | None = None
    error_context: str | None = None

class ProposalAction(str, Enum):
    """What the LLM proposes to do next."""
    PLAN = "plan"
    TOOL_CALL = "tool_call"
    COMPLETE = "complete"
    GIVE_UP = "give_up"

@dataclass
class LLMProposal:
    """Structured output from the LLM."""
    action: ProposalAction
    tool_request: ToolRequest | None = None
    plan_steps: list[str] | None = None
    reasoning: str = ""
    completion_reason: str | None = None

class LLMError(Exception):
    """Base exception for LLM provider failures."""

class LLMProvider(Protocol):
    """Provider-neutral interface for LLM interaction."""
    
    def propose(self, context: AgentContext) -> LLMProposal:
        """Given bounded task context, return a structured proposal.
        
        Raises LLMError on provider failure.
        """
        ...
