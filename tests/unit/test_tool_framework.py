"""Unit tests for M2's registry, policy gate, and controlled dispatcher."""

import unittest

from control_plane.domain import ToolRequest, ToolResultStatus
from control_plane.policy import AllowListedPolicyGate
from control_plane.tools import DuplicateToolError, ToolDispatcher, ToolNotFoundError, ToolRegistry
from tests.unit.fake_tools import FailingTool, RecordingTool


class ToolRegistryTests(unittest.TestCase):
    def test_registers_tool_and_exposes_metadata_not_implementation(self) -> None:
        registry = ToolRegistry()
        tool = RecordingTool()

        registry.register(tool)

        metadata = registry.get_metadata("fake_read_tool")
        self.assertEqual(metadata.name, "fake_read_tool")
        self.assertFalse(hasattr(metadata, "_execute"))
        self.assertFalse(hasattr(tool, "execute"))
        self.assertFalse(hasattr(registry, "execute"))
        self.assertFalse(hasattr(registry, "get_tool"))
        self.assertEqual(registry.available_tools(), (metadata,))

    def test_rejects_duplicate_registration(self) -> None:
        registry = ToolRegistry()
        registry.register(RecordingTool())

        with self.assertRaises(DuplicateToolError):
            registry.register(RecordingTool())

    def test_rejects_unknown_tool_lookup(self) -> None:
        with self.assertRaises(ToolNotFoundError):
            ToolRegistry().get_metadata("missing")


class ToolDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.tool = RecordingTool()
        self.registry.register(self.tool)
        self.dispatcher = ToolDispatcher(
            self.registry,
            AllowListedPolicyGate(frozenset({"test.read"})),
        )

    def test_executes_registered_allowed_tool_through_dispatcher(self) -> None:
        result = self.dispatcher.dispatch(
            ToolRequest("fake_read_tool", "test.read", {"value": "hello"})
        )

        self.assertEqual(result.status, ToolResultStatus.SUCCESS)
        self.assertEqual(result.output, {"echo": "hello"})
        self.assertEqual(self.tool.execution_count, 1)

    def test_blocks_unknown_tool_without_execution(self) -> None:
        result = self.dispatcher.dispatch(
            ToolRequest("not_registered", "test.read", {"value": "hello"})
        )

        self.assertEqual(result.status, ToolResultStatus.FAILURE)
        self.assertEqual(result.error.code, "unknown_tool")
        self.assertEqual(self.tool.execution_count, 0)

    def test_blocks_unauthorized_request_before_execution(self) -> None:
        result = self.dispatcher.dispatch(
            ToolRequest("fake_read_tool", "test.write", {"value": "hello"})
        )

        self.assertEqual(result.status, ToolResultStatus.BLOCKED)
        self.assertEqual(result.error.code, "policy_blocked")
        self.assertEqual(self.tool.execution_count, 0)

    def test_rejects_capability_mismatch_before_execution(self) -> None:
        dispatcher = ToolDispatcher(
            self.registry,
            AllowListedPolicyGate(frozenset({"test.other"})),
        )

        result = dispatcher.dispatch(
            ToolRequest("fake_read_tool", "test.other", {"value": "hello"})
        )

        self.assertEqual(result.status, ToolResultStatus.INVALID_REQUEST)
        self.assertEqual(result.error.code, "capability_mismatch")
        self.assertEqual(self.tool.execution_count, 0)

    def test_rejects_malformed_request_before_policy_or_execution(self) -> None:
        result = self.dispatcher.dispatch(
            ToolRequest("fake_read_tool", "test.read", {"value": "hello"}, request_id="")
        )

        self.assertEqual(result.status, ToolResultStatus.INVALID_REQUEST)
        self.assertEqual(result.error.code, "invalid_request_id")
        self.assertEqual(self.tool.execution_count, 0)

    def test_rejects_missing_schema_argument_without_execution(self) -> None:
        result = self.dispatcher.dispatch(ToolRequest("fake_read_tool", "test.read", {}))

        self.assertEqual(result.status, ToolResultStatus.INVALID_REQUEST)
        self.assertEqual(result.error.code, "missing_arguments")
        self.assertEqual(self.tool.execution_count, 0)

    def test_returns_structured_result_when_tool_fails(self) -> None:
        registry = ToolRegistry()
        failing_tool = FailingTool()
        registry.register(failing_tool)
        dispatcher = ToolDispatcher(
            registry,
            AllowListedPolicyGate(frozenset({"test.read"})),
        )

        result = dispatcher.dispatch(
            ToolRequest("fake_read_tool", "test.read", {"value": "hello"})
        )

        self.assertEqual(result.status, ToolResultStatus.FAILURE)
        self.assertEqual(result.error.code, "tool_execution_failed")
        self.assertEqual(failing_tool.execution_count, 1)


if __name__ == "__main__":
    unittest.main()
