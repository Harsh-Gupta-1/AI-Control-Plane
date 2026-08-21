import os
from pathlib import Path
from control_plane.cli import main
from control_plane.domain import TaskState

def test_cli_fake_mode(tmp_path: Path):
    """Test the CLI executes cleanly in fake mode without Docker."""
    trace_out = tmp_path / "trace.jsonl"
    
    # Run CLI
    main([
        "--goal", "test goal",
        "--trace-out", str(trace_out),
        "--llm", "fake",
        "--auto-approve"
    ])
    
    # Assert trace file exists and is populated
    assert trace_out.exists()
    assert trace_out.stat().st_size > 0
    
    # Read trace and verify it contains completion event
    content = trace_out.read_text()
    assert "task_completed" in content or "task_failed" in content
