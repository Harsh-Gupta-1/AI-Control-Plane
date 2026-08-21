import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Any

from control_plane.domain.models import Task, Plan, ActionRecord, Observation

@dataclass
class TaskCheckpoint:
    task: Task
    plan: Plan | None
    action_history: list[ActionRecord]
    observations: list[Observation]
    iteration_count: int
    consecutive_failures: int
    sandbox_id: str | None
    created_at: datetime

class CheckpointStore(Protocol):
    def save(self, task_id: str, checkpoint: TaskCheckpoint) -> None: ...
    def load(self, task_id: str) -> TaskCheckpoint | None: ...
    def delete(self, task_id: str) -> None: ...

def _serialize_datetime(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None

def _deserialize_datetime(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None

def _serialize_task(task: Task) -> dict[str, Any]:
    # Simplified for MVP, we might need a better JSON encoder
    data = asdict(task)
    data["created_at"] = _serialize_datetime(task.created_at)
    data["updated_at"] = _serialize_datetime(task.updated_at)
    
    if data["plan"]:
        pass # dataclass asdict handles it, but check nested datetimes
        
    for action in data["actions"]:
        action["recorded_at"] = _serialize_datetime(action["recorded_at"])
        
    for obs in data["observations"]:
        obs["recorded_at"] = _serialize_datetime(obs["recorded_at"])
        
    return data
    
def _deserialize_task(data: dict[str, Any]) -> Task:
    # Need to reconstruct dataclasses from dictionaries
    from control_plane.domain.models import ActionRequest, TaskState, PlanStep
    
    plan_data = data.get("plan")
    plan = None
    if plan_data:
        steps = [PlanStep(**s) for s in plan_data.get("steps", [])]
        plan = Plan(steps=steps, current_step_index=plan_data.get("current_step_index", 0))
        
    actions = []
    for a in data.get("actions", []):
        req = ActionRequest(**a["request"])
        actions.append(ActionRecord(
            action_id=a["action_id"],
            request=req,
            recorded_at=_deserialize_datetime(a["recorded_at"]) or datetime.now(timezone.utc)
        ))
        
    observations = []
    for o in data.get("observations", []):
        observations.append(Observation(
            observation_id=o["observation_id"],
            source=o["source"],
            content=o["content"],
            data=o.get("data", {}),
            recorded_at=_deserialize_datetime(o["recorded_at"])
        ))
        
    return Task(
        task_id=data["task_id"],
        goal=data["goal"],
        state=TaskState(data["state"]),
        created_at=_deserialize_datetime(data["created_at"]) or datetime.now(timezone.utc),
        updated_at=_deserialize_datetime(data["updated_at"]) or datetime.now(timezone.utc),
        plan=plan,
        actions=actions,
        observations=observations,
    )

def _serialize_checkpoint(checkpoint: TaskCheckpoint) -> dict[str, Any]:
    data = asdict(checkpoint)
    data["task"] = _serialize_task(checkpoint.task)
    data["created_at"] = _serialize_datetime(checkpoint.created_at)
    
    # plan, action_history, and observations are actually inside task. 
    # For MVP, we can just serialize them again or use task's.
    if data["plan"]:
        pass
    
    for action in data["action_history"]:
        action["recorded_at"] = _serialize_datetime(action["recorded_at"])
        
    for obs in data["observations"]:
        obs["recorded_at"] = _serialize_datetime(obs["recorded_at"])
        
    return data

def _deserialize_checkpoint(data: dict[str, Any]) -> TaskCheckpoint:
    from control_plane.domain.models import PlanStep, ActionRequest
    
    task = _deserialize_task(data["task"])
    
    plan_data = data.get("plan")
    plan = None
    if plan_data:
        steps = [PlanStep(**s) for s in plan_data.get("steps", [])]
        plan = Plan(steps=steps, current_step_index=plan_data.get("current_step_index", 0))
        
    action_history = []
    for a in data.get("action_history", []):
        req = ActionRequest(**a["request"])
        action_history.append(ActionRecord(
            action_id=a["action_id"],
            request=req,
            recorded_at=_deserialize_datetime(a["recorded_at"]) or datetime.now(timezone.utc)
        ))
        
    observations = []
    for o in data.get("observations", []):
        observations.append(Observation(
            observation_id=o["observation_id"],
            source=o["source"],
            content=o["content"],
            data=o.get("data", {}),
            recorded_at=_deserialize_datetime(o["recorded_at"])
        ))

    return TaskCheckpoint(
        task=task,
        plan=plan,
        action_history=action_history,
        observations=observations,
        iteration_count=data["iteration_count"],
        consecutive_failures=data["consecutive_failures"],
        sandbox_id=data["sandbox_id"],
        created_at=_deserialize_datetime(data["created_at"]) or datetime.now(timezone.utc),
    )

class JsonFileCheckpointStore(CheckpointStore):
    """Stores checkpoints as JSON files in a local directory."""
    
    def __init__(self, checkpoint_dir: str = ".checkpoints") -> None:
        self._dir = Path(checkpoint_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, task_id: str, checkpoint: TaskCheckpoint) -> None:
        path = self._dir / f"{task_id}.json"
        data = _serialize_checkpoint(checkpoint)
        path.write_text(json.dumps(data, indent=2))
    
    def load(self, task_id: str) -> TaskCheckpoint | None:
        path = self._dir / f"{task_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return _deserialize_checkpoint(data)
    
    def delete(self, task_id: str) -> None:
        path = self._dir / f"{task_id}.json"
        path.unlink(missing_ok=True)
