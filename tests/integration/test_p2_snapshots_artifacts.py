import os
import pytest
from control_plane.sandbox.manager import ComputerManager

@pytest.fixture
def manager():
    mgr = ComputerManager(storage_path=".control_plane/test_p2_computers.json")
    yield mgr
    
    # Cleanup all computers
    for c in mgr.list_computers():
        mgr.destroy_computer(c.id)
    if os.path.exists(".control_plane/test_p2_computers.json"):
        os.remove(".control_plane/test_p2_computers.json")


def test_snapshot_and_rollback(manager):
    # 1. Create a computer
    comp = manager.create_computer()
    sandbox = manager.start_computer(comp.id)
    
    # 2. Write a file
    res = sandbox.execute(["sh", "-c", "echo 'v1' > /workspace/data.txt"], timeout_seconds=10)
    assert res.exit_code == 0
    
    # 3. Snapshot
    snap_id = manager.snapshot_computer(comp.id)
    assert snap_id is not None
    
    # 4. Modify file
    sandbox.execute(["sh", "-c", "echo 'v2' > /workspace/data.txt"], timeout_seconds=10)
    res = sandbox.execute(["cat", "/workspace/data.txt"], timeout_seconds=10)
    assert "v2" in res.stdout
    
    # 5. Rollback
    manager.rollback_computer(comp.id, snap_id)
    
    # 6. Verify rollback
    sandbox2 = manager.get_sandbox(comp.id)
    res2 = sandbox2.execute(["cat", "/workspace/data.txt"], timeout_seconds=10)
    assert "v1" in res2.stdout
    assert "v2" not in res2.stdout

def test_extract_artifact(manager, tmp_path):
    comp = manager.create_computer()
    sandbox = manager.start_computer(comp.id)
    
    sandbox.execute(["sh", "-c", "echo 'artifact_content' > /workspace/artifact.txt"], timeout_seconds=10)
    
    out_dir = tmp_path / "extracted"
    out_dir.mkdir()
    
    manager.extract_artifact(comp.id, "/workspace/artifact.txt", str(out_dir))
    
    # Docker get_archive usually preserves the file name inside the tar
    extracted_file = out_dir / "artifact.txt"
    assert extracted_file.exists()
    assert extracted_file.read_text().strip() == "artifact_content"
