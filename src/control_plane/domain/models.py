"""Core data structures owned by the control plane.

These models intentionally contain no provider, tool, or sandbox dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskState(str, Enum):
    """Lifecycle states for a task managed by the runtime."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PlanStep:
    """A descriptive step in a task plan, with no execution authority."""

    step_id: str
    description: str


@dataclass
class Plan:
    """An ordered, optional plan associated with a task."""

    steps: list[PlanStep] = field(default_factory=list)


@dataclass
class ActionRequest:
    """A structured request recorded by the runtime.

    M1 records requests only. It neither resolves nor executes them.
    """

    action_type: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionRecord:
    """An action request assigned an identity and timestamp by the runtime."""

    action_id: str
    request: ActionRequest
    recorded_at: datetime


@dataclass
class Observation:
    """A structured fact recorded against a task.

    Future tool adapters may produce observations, but the domain model does not
    depend on how the fact was obtained.
    """

    observation_id: str
    source: str
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime | None = None


@dataclass
class Task:
    """Canonical task data held by ``TaskRuntime``."""

    task_id: str
    goal: str
    state: TaskState
    created_at: datetime
    updated_at: datetime
    plan: Plan | None = None
    actions: list[ActionRecord] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
