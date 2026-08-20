"""Unit tests for the M1 in-memory task runtime."""

import unittest

from control_plane.domain import ActionRequest, Observation, TaskState
from control_plane.runtime import InvalidTaskTransition, TaskRuntime


class TaskRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = TaskRuntime()

    def test_create_task_creates_pending_task(self) -> None:
        task = self.runtime.create_task("Prepare a sandboxed report")

        self.assertTrue(task.task_id)
        self.assertEqual(task.goal, "Prepare a sandboxed report")
        self.assertEqual(task.state, TaskState.PENDING)
        self.assertEqual(task.actions, [])
        self.assertEqual(task.observations, [])
        self.assertEqual(self.runtime.get_task(task.task_id), task)

    def test_valid_transitions_are_applied(self) -> None:
        task = self.runtime.create_task("Complete a controlled task")

        running = self.runtime.transition_task(task.task_id, TaskState.RUNNING)
        completed = self.runtime.transition_task(task.task_id, TaskState.COMPLETED)

        self.assertEqual(running.state, TaskState.RUNNING)
        self.assertEqual(completed.state, TaskState.COMPLETED)
        self.assertEqual(self.runtime.get_task(task.task_id).state, TaskState.COMPLETED)

    def test_invalid_transition_is_rejected(self) -> None:
        task = self.runtime.create_task("Do not skip lifecycle states")

        with self.assertRaises(InvalidTaskTransition):
            self.runtime.transition_task(task.task_id, TaskState.COMPLETED)

        self.assertEqual(self.runtime.get_task(task.task_id).state, TaskState.PENDING)

    def test_actions_are_recorded_on_the_canonical_task(self) -> None:
        task = self.runtime.create_task("Record an action")
        request = ActionRequest("future_tool", {"target": "example"})

        action = self.runtime.record_action(task.task_id, request)
        stored_task = self.runtime.get_task(task.task_id)

        self.assertTrue(action.action_id)
        self.assertEqual(action.request, request)
        self.assertEqual(stored_task.actions, [action])
        self.assertIsNot(stored_task.actions[0], action)

    def test_observations_are_recorded_on_the_canonical_task(self) -> None:
        task = self.runtime.create_task("Record an observation")
        observation = Observation(
            observation_id="observation-1",
            source="test",
            content="Expected state observed",
            data={"matched": True},
        )

        recorded = self.runtime.record_observation(task.task_id, observation)
        stored_task = self.runtime.get_task(task.task_id)

        self.assertIsNotNone(recorded.recorded_at)
        self.assertEqual(stored_task.observations, [recorded])
        self.assertIsNot(stored_task.observations[0], recorded)


if __name__ == "__main__":
    unittest.main()
