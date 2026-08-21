import shutil
from pathlib import Path
from datetime import datetime, timezone
from control_plane.domain.models import Task, TaskState, Plan, PlanStep, ActionRecord, ActionRequest, Observation
from control_plane.runtime.checkpoint import JsonFileCheckpointStore, TaskCheckpoint

def test_checkpoint_save_load_delete(tmp_path: Path):
    store = JsonFileCheckpointStore(str(tmp_path / "checkpoints"))
    
    task = Task(
        task_id="task-123",
        goal="Test goal",
        state=TaskState.RUNNING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        plan=Plan(steps=[PlanStep("step-1", "Step 1")], current_step_index=1),
        actions=[ActionRecord("act-1", ActionRequest("test_tool", {"a": 1}), datetime.now(timezone.utc))],
        observations=[Observation("obs-1", "test", "content", {}, datetime.now(timezone.utc))]
    )
    
    checkpoint = TaskCheckpoint(
        task=task,
        plan=task.plan,
        action_history=task.actions,
        observations=task.observations,
        iteration_count=5,
        consecutive_failures=1,
        sandbox_id="sandbox-456",
        created_at=datetime.now(timezone.utc)
    )
    
    store.save("task-123", checkpoint)
    
    loaded = store.load("task-123")
    assert loaded is not None
    assert loaded.iteration_count == 5
    assert loaded.sandbox_id == "sandbox-456"
    assert loaded.task.task_id == "task-123"
    assert len(loaded.task.plan.steps) == 1
    assert len(loaded.task.actions) == 1
    assert loaded.task.actions[0].request.action_type == "test_tool"
    assert len(loaded.task.observations) == 1
    assert loaded.task.observations[0].content == "content"
    
    store.delete("task-123")
    assert store.load("task-123") is None
