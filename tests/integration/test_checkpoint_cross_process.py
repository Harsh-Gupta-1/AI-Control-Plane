import os
import pytest
from control_plane.runtime.task_runtime import TaskRuntime
from control_plane.runtime.checkpoint import JsonFileCheckpointStore
from control_plane.domain.models import TaskState, Plan, PlanStep

def test_cross_process_checkpoint_restore(tmp_path):
    # Simulated Process A
    checkpoint_dir = str(tmp_path / "checkpoints")
    store_a = JsonFileCheckpointStore(checkpoint_dir)
    runtime_a = TaskRuntime()
    
    # Create task and execute
    task_a = runtime_a.create_task("Do something")
    task_a = runtime_a.transition_task(task_a.task_id, TaskState.PLANNING)
    task_a = runtime_a.update_plan(task_a.task_id, Plan(steps=[PlanStep(step_id="step1", description="Step 1")], current_step_index=0))
    task_a = runtime_a.transition_task(task_a.task_id, TaskState.RUNNING)
    
    # Save checkpoint via store directly (AgentLoop normally does this)
    from control_plane.runtime.checkpoint import TaskCheckpoint
    from datetime import datetime, timezone
    
    ckpt = TaskCheckpoint(
        task=task_a,
        plan=task_a.plan,
        action_history=task_a.actions,
        observations=task_a.observations,
        iteration_count=5,
        consecutive_failures=1,
        sandbox_id="sbx-123",
        created_at=datetime.now(timezone.utc)
    )
    store_a.save(task_a.task_id, ckpt)
    
    # Simulate process death
    del runtime_a
    del store_a
    
    # Simulated Process B
    store_b = JsonFileCheckpointStore(checkpoint_dir)
    runtime_b = TaskRuntime()
    
    # Load and restore
    loaded_ckpt = store_b.load(task_a.task_id)
    assert loaded_ckpt is not None
    
    task_b = runtime_b.restore_task(loaded_ckpt.task)
    
    # Verify exact state is restored in runtime canonical state
    canonical_task = runtime_b.get_task(task_a.task_id)
    assert canonical_task.task_id == task_a.task_id
    assert canonical_task.state == TaskState.RUNNING
    assert canonical_task.plan is not None
    assert len(canonical_task.plan.steps) == 1
    assert canonical_task.plan.steps[0].description == "Step 1"
