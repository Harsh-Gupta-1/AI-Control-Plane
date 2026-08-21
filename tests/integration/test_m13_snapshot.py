"""Integration tests for M13 Sandbox Snapshot / Rollback."""

import pytest
from control_plane.sandbox.docker_sandbox import DockerSandbox
from control_plane.sandbox.contracts import SandboxState, SandboxError

@pytest.fixture
def sandbox():
    """Provides an isolated sandbox for testing, ensuring cleanup."""
    box = DockerSandbox()
    box.start()
    yield box
    if box.inspect() != SandboxState.DESTROYED:
        box.stop()
        box.destroy()

def test_snapshot_and_rollback(sandbox: DockerSandbox):
    """M13: Test snapshot and rollback restores the sandbox filesystem state."""
    
    # 1. Write an initial file
    cmd1 = ["sh", "-c", "echo 'initial_state' > /workspace/data.txt"]
    res1 = sandbox.execute(cmd1, timeout_seconds=5)
    assert res1.exit_code == 0
    
    # 2. Verify file content
    cmd2 = ["cat", "/workspace/data.txt"]
    res2 = sandbox.execute(cmd2, timeout_seconds=5)
    assert res2.exit_code == 0
    assert "initial_state" in res2.stdout
    
    # 3. Snapshot the state
    snapshot_id = sandbox.snapshot()
    assert snapshot_id is not None
    assert len(snapshot_id) > 0
    
    # 4. Modify the file
    cmd3 = ["sh", "-c", "echo 'modified_state' > /workspace/data.txt"]
    res3 = sandbox.execute(cmd3, timeout_seconds=5)
    assert res3.exit_code == 0
    
    # 5. Verify the modification
    res4 = sandbox.execute(cmd2, timeout_seconds=5)
    assert res4.exit_code == 0
    assert "modified_state" in res4.stdout
    
    # 6. Rollback to snapshot
    sandbox.rollback(snapshot_id)
    
    # 7. Verify the file reverted to initial state
    res5 = sandbox.execute(cmd2, timeout_seconds=5)
    assert res5.exit_code == 0
    assert "initial_state" in res5.stdout

def test_rollback_invalid_snapshot(sandbox: DockerSandbox):
    """M13: Test rolling back to an invalid snapshot raises SandboxError."""
    with pytest.raises(SandboxError, match="Snapshot invalid_snap not found"):
        sandbox.rollback("invalid_snap")
