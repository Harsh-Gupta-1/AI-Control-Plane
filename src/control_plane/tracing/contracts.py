import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone
from typing import Any, Protocol
from pathlib import Path
from uuid import uuid4

class TraceEventType(str, Enum):
    TASK_CREATED = "task_created"
    PLAN_PROPOSED = "plan_proposed"
    PLAN_ACCEPTED = "plan_accepted"
    ACTION_PROPOSED = "action_proposed"
    POLICY_EVALUATED = "policy_evaluated"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    TOOL_INVOKED = "tool_invoked"
    TOOL_RESULT = "tool_result"
    OBSERVATION_RECORDED = "observation_recorded"
    REPLAN_TRIGGERED = "replan_triggered"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_RESULT = "verification_result"
    RECOVERY_ATTEMPTED = "recovery_attempted"
    TASK_STATE_CHANGED = "task_state_changed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    CHECKPOINT_SAVED = "checkpoint_saved"

@dataclass
class TraceEvent:
    event_id: str
    event_type: TraceEventType
    task_id: str
    action_id: str | None = None
    parent_event_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)

class TraceSink(Protocol):
    """Append-only destination for trace events."""
    def emit(self, event: TraceEvent) -> None: ...

def _serialize_event(event: TraceEvent) -> dict[str, Any]:
    data = asdict(event)
    data["event_type"] = event.event_type.value
    data["timestamp"] = event.timestamp.isoformat()
    return data

class JsonFileTraceSink(TraceSink):
    """Writes trace events as JSON-lines to a file."""
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
    
    def emit(self, event: TraceEvent) -> None:
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(_serialize_event(event)) + "\n")
        except Exception:
            pass  # Tracing must never break execution
