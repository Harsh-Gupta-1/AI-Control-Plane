"""Sandbox interfaces and domain models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class SandboxState(str, Enum):
    """Lifecycle states of the sandbox."""

    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    DESTROYED = "destroyed"


@dataclass
class SandboxResult:
    """The outcome of a sandbox execution operation."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_truncated: bool


class SandboxError(Exception):
    """Base exception for sandbox-related errors."""


class Sandbox(ABC):
    """Abstract interface for an isolated execution environment."""

    @property
    @abstractmethod
    def id(self) -> str:
        """A unique identifier for the sandbox instance."""

    @abstractmethod
    def start(self) -> None:
        """Start the sandbox environment.

        Raises SandboxError if the sandbox cannot be started or is not in a valid state.
        """

    @abstractmethod
    def stop(self) -> None:
        """Stop the running sandbox environment.

        Raises SandboxError if stopping fails.
        """

    @abstractmethod
    def destroy(self) -> None:
        """Destroy the sandbox, completely removing its ephemeral state.

        Raises SandboxError if destruction fails.
        """

    @abstractmethod
    def inspect(self) -> SandboxState:
        """Return the current lifecycle state of the sandbox.

        Raises SandboxError if the state cannot be determined (e.g., if destroyed or missing).
        """

    @abstractmethod
    def execute(self, command: list[str], timeout_seconds: int, max_output_bytes: int = 1048576) -> SandboxResult:
        """Execute a narrow command inside the sandbox.

        Args:
            command: The command and its arguments.
            timeout_seconds: The maximum allowed execution time.
            max_output_bytes: The maximum number of bytes to read from stdout/stderr.

        Returns:
            SandboxResult with bounded outputs, exit code, and timeout status.

        Raises SandboxError if the sandbox is not running or if execution invocation fails.
        """
