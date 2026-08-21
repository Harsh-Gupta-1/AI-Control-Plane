from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from control_plane.sandbox.contracts import Sandbox

class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"

@dataclass
class VerificationResult:
    status: VerificationStatus
    evidence: list[str]
    reason: str

class VerificationCheck(Protocol):
    """A single verification check against sandbox state."""
    def verify(self, sandbox: Sandbox, criteria: dict[str, Any]) -> VerificationResult: ...
