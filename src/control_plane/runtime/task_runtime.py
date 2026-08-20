"""In-memory canonical task state management for M1."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from control_plane.domain import (
    ActionRecord,
    ActionRequest,
    Observation,
    Plan,
    Task,
    TaskState,
)


class TaskNotFoundError(KeyError):
    """Raised when a task identifier is not owned by this runtime."""


class InvalidTaskTransition(ValueError):
    """Raised when a requested lifecycle transition is not legal."""


_ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.RUNNING, TaskState.CANCELLED}),
    TaskState.RUNNING: frozenset(
        {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class TaskRuntime:
    """Owns in-memory task state and applies deterministic lifecycle rules."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def create_task(self, goal: str, *, plan: Plan | None = None) -> Task:
        """Create a pending task and return a detached snapshot."""
        if not goal.strip():
            raise ValueError("task goal must not be empty")

        now = _utc_now()
        task = Task(
            task_id=str(uuid4()),
            goal=goal,
            state=TaskState.PENDING,
            created_at=now,
            updated_at=now,
            plan=deepcopy(plan),
        )
        self._tasks[task.task_id] = task
        return deepcopy(task)

    def get_task(self, task_id: str) -> Task:
        """Return a detached snapshot of the current canonical task state."""
        return deepcopy(self._get_canonical_task(task_id))

    def transition_task(self, task_id: str, new_state: TaskState) -> Task:
        """Transition a task if and only if the transition is legal."""
        task = self._get_canonical_task(task_id)
        if new_state not in _ALLOWED_TRANSITIONS[task.state]:
            raise InvalidTaskTransition(
                f"cannot transition task {task_id} from {task.state.value} "
                f"to {new_state.value}"
            )

        task.state = new_state
        task.updated_at = _utc_now()
        return deepcopy(task)

    def record_action(self, task_id: str, request: ActionRequest) -> ActionRecord:
        """Record a structured action request for a non-terminal task."""
        task = self._get_canonical_task(task_id)
        self._require_active(task)

        record = ActionRecord(
            action_id=str(uuid4()),
            request=deepcopy(request),
            recorded_at=_utc_now(),
        )
        task.actions.append(record)
        task.updated_at = record.recorded_at
        return deepcopy(record)

    def record_observation(self, task_id: str, observation: Observation) -> Observation:
        """Record an observation for a non-terminal task."""
        task = self._get_canonical_task(task_id)
        self._require_active(task)

        recorded = deepcopy(observation)
        if recorded.recorded_at is None:
            recorded.recorded_at = _utc_now()
        task.observations.append(recorded)
        task.updated_at = recorded.recorded_at
        return deepcopy(recorded)

    def _get_canonical_task(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFoundError(task_id) from error

    @staticmethod
    def _require_active(task: Task) -> None:
        if task.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            raise InvalidTaskTransition(
                f"cannot record activity for terminal task {task.task_id}"
            )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
