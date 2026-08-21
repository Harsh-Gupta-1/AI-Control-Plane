import pytest
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from control_plane.tracing.contracts import (
    TraceEvent,
    TraceEventType,
    JsonFileTraceSink
)

def test_trace_event_serialization():
    event = TraceEvent(
        event_id="evt-1",
        event_type=TraceEventType.TASK_CREATED,
        task_id="task-1",
        payload={"key": "value"}
    )
    from control_plane.tracing.contracts import _serialize_event
    data = _serialize_event(event)
    assert data["event_id"] == "evt-1"
    assert data["event_type"] == "task_created"
    assert data["task_id"] == "task-1"
    assert data["payload"] == {"key": "value"}
    assert "timestamp" in data
    assert isinstance(data["timestamp"], str)

def test_json_file_trace_sink(tmp_path: Path):
    path = tmp_path / "traces.jsonl"
    sink = JsonFileTraceSink(path)
    
    event1 = TraceEvent(
        event_id="evt-1",
        event_type=TraceEventType.TASK_CREATED,
        task_id="task-1"
    )
    event2 = TraceEvent(
        event_id="evt-2",
        event_type=TraceEventType.PLAN_PROPOSED,
        task_id="task-1",
        payload={"plan_steps": ["step1"]}
    )
    
    sink.emit(event1)
    sink.emit(event2)
    
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    
    data1 = json.loads(lines[0])
    assert data1["event_id"] == "evt-1"
    
    data2 = json.loads(lines[1])
    assert data2["event_id"] == "evt-2"
    assert data2["payload"]["plan_steps"] == ["step1"]
