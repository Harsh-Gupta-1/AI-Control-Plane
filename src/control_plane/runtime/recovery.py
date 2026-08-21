from dataclasses import dataclass
from control_plane.domain.models import FailureCategory

@dataclass
class RecoveryAction:
    strategy: str  # "retry", "replan", "abort", "request_approval"
    reason: str
    delay_seconds: float = 0.0

def determine_recovery(
    failure: FailureCategory,
    consecutive_failures: int,
    max_retries: int = 2,
) -> RecoveryAction:
    """Deterministic recovery decision based on failure type and history."""
    
    if failure == FailureCategory.ITERATION_LIMIT:
        return RecoveryAction("abort", "Max iterations exceeded")
        
    if failure in (FailureCategory.INVALID_INPUT, FailureCategory.POLICY_REJECTION, FailureCategory.APPROVAL_REJECTION):
        return RecoveryAction("replan", f"Cannot retry {failure.value}. LLM must replan.")
        
    if failure == FailureCategory.ENVIRONMENT_FAILURE:
        if consecutive_failures <= 1:
            return RecoveryAction("retry", "Retrying after environment failure", 2.0)
        return RecoveryAction("replan", "Max retries exceeded for environment failure")
        
    if failure == FailureCategory.TIMEOUT:
        if consecutive_failures <= 1:
            return RecoveryAction("retry", "Retrying with longer timeout")
        return RecoveryAction("replan", "Max retries exceeded for timeout")
        
    if failure == FailureCategory.VERIFICATION_FAILURE:
        if consecutive_failures <= max_retries:
            return RecoveryAction("replan", "Verification failed. Replan alternative approach.")
        return RecoveryAction("abort", "Max retries exceeded for verification failure")
        
    if failure in (FailureCategory.TOOL_FAILURE, FailureCategory.LLM_FAILURE):
        if consecutive_failures <= max_retries:
            return RecoveryAction("retry", f"Retrying {failure.value}")
        return RecoveryAction("replan", f"Max retries exceeded for {failure.value}")
        
    return RecoveryAction("abort", f"Unknown failure category: {failure}")
