"""Registry for tool metadata and private dispatcher resolution."""

from control_plane.tools.contracts import Tool, ToolMetadata


class DuplicateToolError(ValueError):
    """Raised when a tool name is registered more than once."""


class ToolNotFoundError(KeyError):
    """Raised when metadata is requested for an unknown tool."""


class ToolRegistry:
    """Stores registered tools without providing a public execution route."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool under its unique metadata name."""
        name = tool.metadata.name
        if not name:
            raise ValueError("tool name must not be empty")
        if name in self._tools:
            raise DuplicateToolError(f"tool already registered: {name}")
        self._tools[name] = tool

    def get_metadata(self, name: str) -> ToolMetadata:
        """Return metadata for a tool without exposing its implementation."""
        return self.resolve_tool(name).metadata

    def available_tools(self) -> tuple[ToolMetadata, ...]:
        """Return metadata for all registered tools in registration order."""
        return tuple(tool.metadata for tool in self._tools.values())

    def resolve_tool(self, name: str) -> Tool:
        """Resolve an implementation for use by the controlled dispatcher."""
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(name) from error
