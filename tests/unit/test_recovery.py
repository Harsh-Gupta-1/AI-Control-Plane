from control_plane.domain.models import FailureCategory
from control_plane.runtime.recovery import determine_recovery

def test_recovery_iteration_limit():
    rec = determine_recovery(FailureCategory.ITERATION_LIMIT, 1)
    assert rec.strategy == "abort"
    assert "iterations exceeded" in rec.reason.lower()

def test_recovery_invalid_input():
    rec = determine_recovery(FailureCategory.INVALID_INPUT, 1)
    assert rec.strategy == "replan"
    assert "replan" in rec.reason.lower()

def test_recovery_environment_failure():
    rec = determine_recovery(FailureCategory.ENVIRONMENT_FAILURE, 1)
    assert rec.strategy == "retry"
    assert rec.delay_seconds == 2.0
    
    rec2 = determine_recovery(FailureCategory.ENVIRONMENT_FAILURE, 2)
    assert rec2.strategy == "replan"

def test_recovery_tool_failure():
    rec = determine_recovery(FailureCategory.TOOL_FAILURE, 1, max_retries=2)
    assert rec.strategy == "retry"
    
    rec2 = determine_recovery(FailureCategory.TOOL_FAILURE, 3, max_retries=2)
    assert rec2.strategy == "replan"

def test_recovery_verification_failure():
    rec = determine_recovery(FailureCategory.VERIFICATION_FAILURE, 1, max_retries=2)
    assert rec.strategy == "replan"
    
    rec2 = determine_recovery(FailureCategory.VERIFICATION_FAILURE, 3, max_retries=2)
    assert rec2.strategy == "abort"
