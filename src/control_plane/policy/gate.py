"""Deny-by-default authorization for structured tool requests."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from control_plane.domain import ToolRequest


class PolicyDecision(str, Enum):
    """The policy gate's possible outcomes."""

    ALLOW = "allow"       # Execute immediately
    APPROVE = "approve"   # Requires human approval before execution
    BLOCK = "block"       # Never execute


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


POLICY_RULES: dict[str, PolicyDecision] = {
    # Filesystem
    "filesystem.read": PolicyDecision.ALLOW,
    "filesystem.write": PolicyDecision.APPROVE,
    "filesystem.delete": PolicyDecision.APPROVE,
    
    # Terminal
    "terminal.execute": PolicyDecision.APPROVE,
    
    # Browser
    "browser.navigate": PolicyDecision.ALLOW,
    "browser.interact": PolicyDecision.APPROVE,
    "browser.read": PolicyDecision.ALLOW,
    "browser.download": PolicyDecision.APPROVE,
}


class CapabilityPolicyGate:
    """Full capability-based policy evaluation."""
    
    def __init__(self, rules: dict[str, PolicyDecision] | None = None) -> None:
        self._rules = rules or dict(POLICY_RULES)
    
    def evaluate(self, request: ToolRequest) -> PolicyResult:
        decision = self._rules.get(request.capability, PolicyDecision.BLOCK)
        return PolicyResult(
            decision=decision,
            reason=f"capability '{request.capability}' is {decision.value}",
        )
