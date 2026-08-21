"""Core data structures owned by the control plane.

These models intentionally contain no provider, tool, or sandbox dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class TaskState(str, Enum):
    """Lifecycle states for a task managed by the runtime."""

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    VERIFYING = "verifying"
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
    current_step_index: int = 0


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


class ToolResultStatus(str, Enum):
    """Outcome categories returned by the controlled tool dispatcher."""

    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    INVALID_REQUEST = "invalid_request"


@dataclass
class ToolRequest:
    """A request for a named capability through the controlled dispatcher."""

    tool_name: str
    capability: str
    arguments: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class ToolError:
    """Machine-readable failure information for a tool request."""

    code: str
    message: str


@dataclass
class ToolResult:
    """Structured result returned by the dispatcher, never an exception leak."""

    request_id: str
    status: ToolResultStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: ToolError | None = None

    @classmethod
    def failure(
        cls, request_id: str, status: ToolResultStatus, code: str, message: str
    ) -> "ToolResult":
        """Build a non-success result with structured error details."""
        return cls(
            request_id=request_id,
            status=status,
            error=ToolError(code=code, message=message),
        )


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
