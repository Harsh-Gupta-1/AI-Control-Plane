"""Deny-by-default authorization for structured tool requests."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from control_plane.domain import ToolRequest


class PolicyDecision(str, Enum):
    """The M2 policy gate's possible outcomes."""

    ALLOW = "allow"
    BLOCK = "block"


@dataclass(frozen=True)
class PolicyResult:
    """A deterministic authorization result and its reason."""

    decision: PolicyDecision
    reason: str


class PolicyGate(Protocol):
    """Side-effect-free authorization boundary used by the dispatcher."""

    def evaluate(self, request: ToolRequest) -> PolicyResult:
        """Authorize or block a normalized tool request."""


class AllowListedPolicyGate:
    """Allows only explicitly configured test-safe capabilities."""

    def __init__(self, allowed_capabilities: frozenset[str] = frozenset()) -> None:
        self._allowed_capabilities = allowed_capabilities

    def evaluate(self, request: ToolRequest) -> PolicyResult:
        if request.capability in self._allowed_capabilities:
            return PolicyResult(PolicyDecision.ALLOW, "capability is explicitly allowed")
        return PolicyResult(PolicyDecision.BLOCK, "capability is not allowed")
