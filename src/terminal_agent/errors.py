"""Structured errors for terminal-agent."""

from __future__ import annotations


class TerminalAgentError(Exception):
    """Base error."""


class BlockedCommandError(TerminalAgentError):
    """Raised when a command is blocked by policy."""

    def __init__(self, command: str, reason: str) -> None:
        super().__init__(f"Blocked command {command!r}: {reason}")
        self.command = command
        self.reason = reason


class JailEscapeError(TerminalAgentError):
    """Raised when a path would escape the jail directory."""


class ExecutionTimeoutError(TerminalAgentError):
    """Raised when a command exceeds its timeout."""
