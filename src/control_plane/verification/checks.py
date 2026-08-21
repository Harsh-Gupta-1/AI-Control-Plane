from control_plane.verification.contracts import VerificationResult, VerificationStatus, VerificationCheck
from control_plane.sandbox.contracts import Sandbox

class FileExistsCheck(VerificationCheck):
    """Verify a file exists at a specified path inside the sandbox."""
    def verify(self, sandbox: Sandbox, criteria: dict) -> VerificationResult:
        path = criteria.get("path")
        if not path:
            return VerificationResult(VerificationStatus.INCONCLUSIVE, [], "missing 'path' in criteria")
            
        result = sandbox.execute(["test", "-f", path], timeout_seconds=5)
        if result.exit_code == 0:
            return VerificationResult(VerificationStatus.VERIFIED, [f"file exists: {path}"], "file found")
        return VerificationResult(VerificationStatus.FAILED, [f"file missing: {path}"], "file not found")

class FileContentCheck(VerificationCheck):
    """Verify a file contains expected content."""
    def verify(self, sandbox: Sandbox, criteria: dict) -> VerificationResult:
        path = criteria.get("path")
        expected = criteria.get("contains")
        if not path or not expected:
            return VerificationResult(VerificationStatus.INCONCLUSIVE, [], "missing 'path' or 'contains' in criteria")
            
        result = sandbox.execute(["cat", path], timeout_seconds=5, max_output_bytes=65536)
        if result.exit_code != 0:
            return VerificationResult(VerificationStatus.FAILED, [f"could not read file: {path}"], "read failed")
            
        if expected in result.stdout:
            return VerificationResult(VerificationStatus.VERIFIED, [f"content matched in {path}"], "content matches")
        return VerificationResult(VerificationStatus.FAILED, [f"content mismatch in {path}"], "content mismatch")

class CommandSuccessCheck(VerificationCheck):
    """Verify a command exits successfully."""
    def verify(self, sandbox: Sandbox, criteria: dict) -> VerificationResult:
        command = criteria.get("command")
        if not command:
            return VerificationResult(VerificationStatus.INCONCLUSIVE, [], "missing 'command' in criteria")
            
        timeout = criteria.get("timeout", 10)
        result = sandbox.execute(command if isinstance(command, list) else ["sh", "-c", command], timeout_seconds=timeout)
        if result.exit_code == 0:
            return VerificationResult(VerificationStatus.VERIFIED, [f"command succeeded: {command}"], "command succeeded")
        return VerificationResult(VerificationStatus.FAILED, [f"command failed: {command}"], f"exit code {result.exit_code}")
