from pathlib import Path
from control_plane.sandbox.docker_sandbox import DockerSandbox
from control_plane.verification.checks import FileExistsCheck, CommandSuccessCheck
from control_plane.verification.contracts import VerificationStatus
import pytest
import os

@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="Docker not available in standard runner")
def test_integration_verification():
    sandbox = DockerSandbox(image="ubuntu:22.04")
    sandbox.start()
    try:
        # Create a file
        sandbox.execute(["sh", "-c", "echo 'hello' > /workspace/test.txt"], timeout_seconds=5)
        
        # Verify file exists
        check1 = FileExistsCheck()
        res1 = check1.verify(sandbox, {"path": "/workspace/test.txt"})
        assert res1.status == VerificationStatus.VERIFIED
        
        # Verify non-existent file
        res2 = check1.verify(sandbox, {"path": "/workspace/nonexistent.txt"})
        assert res2.status == VerificationStatus.FAILED
        
        # Verify command success
        check2 = CommandSuccessCheck()
        res3 = check2.verify(sandbox, {"command": "ls /workspace"})
        assert res3.status == VerificationStatus.VERIFIED
    finally:
        sandbox.stop()
        sandbox.destroy()
