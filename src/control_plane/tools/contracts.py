"""Generic contracts for structured tools.

Tool execution is intentionally exposed as a protected hook. The dispatcher is
the supported caller; concrete tools must not offer a second public path.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from control_plane.domain import ToolRequest, ToolResult


@dataclass(frozen=True)
class ToolInputSchema:
    """The minimal request shape enforced before a tool is invoked."""

    required_arguments: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ToolMetadata:
    """Public, non-executable description of a registered tool."""

    name: str
    description: str
    capability: str
    input_schema: ToolInputSchema = field(default_factory=ToolInputSchema)


class Tool(ABC):
    """A registered capability implementation.

    Registries expose metadata, not tool instances. ``_execute`` is a protected
    dispatcher hook rather than a public application API.
    """

    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        """Return the registered tool's immutable metadata."""

    @abstractmethod
    def _execute(self, request: ToolRequest) -> ToolResult:
        """Execute a validated, authorized request from ``ToolDispatcher``."""
