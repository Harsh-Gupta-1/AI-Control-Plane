from control_plane.verification.contracts import VerificationStatus
from control_plane.verification.checks import FileExistsCheck, FileContentCheck, CommandSuccessCheck
from control_plane.sandbox.contracts import SandboxResult
from tests.unit.fake_sandbox import FakeSandbox

def test_file_exists_check_verified():
    sandbox = FakeSandbox([SandboxResult(0, "", "", False, False)])
    
    check = FileExistsCheck()
    result = check.verify(sandbox, {"path": "/workspace/test.txt"})
    
    assert result.status == VerificationStatus.VERIFIED

def test_file_exists_check_failed():
    sandbox = FakeSandbox([SandboxResult(1, "", "", False, False)])
    
    check = FileExistsCheck()
    result = check.verify(sandbox, {"path": "/workspace/test.txt"})
    
    assert result.status == VerificationStatus.FAILED

def test_file_content_check_verified():
    sandbox = FakeSandbox([SandboxResult(0, "hello world", "", False, False)])
    
    check = FileContentCheck()
    result = check.verify(sandbox, {"path": "/workspace/test.txt", "contains": "world"})
    
    assert result.status == VerificationStatus.VERIFIED

def test_file_content_check_failed_mismatch():
    sandbox = FakeSandbox([SandboxResult(0, "hello world", "", False, False)])
    
    check = FileContentCheck()
    result = check.verify(sandbox, {"path": "/workspace/test.txt", "contains": "mars"})
    
    assert result.status == VerificationStatus.FAILED

def test_command_success_check_verified():
    sandbox = FakeSandbox([SandboxResult(0, "1", "", False, False)])
    
    check = CommandSuccessCheck()
    result = check.verify(sandbox, {"command": "echo 1"})
    
    assert result.status == VerificationStatus.VERIFIED
