"""Sandboxed shell executor: allowlist/blocklist, timeout, cwd jail."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from terminal_agent.errors import BlockedCommandError, JailEscapeError

DEFAULT_BLOCKED: tuple[str, ...] = (
    "sudo", "su ", "rm -rf /", "rm -rf ~", "mkfs", "dd if=", ":(){",
    "chmod -r 777 /", "curl | sh", "wget | sh", "> /dev/sd", "shutdown",
    "reboot", "halt", "poweroff", "kill -9 1",
)
DEFAULT_ALLOWED: tuple[str, ...] = (
    "echo", "ls", "cat", "pwd", "python3", "python", "printf", "head",
    "tail", "grep", "wc", "touch", "mkdir", "date", "whoami", "true",
    "false", "test", "basename", "dirname", "sort", "uniq", "tr", "cut",
)


@dataclass
class ExecResult:
    """Result of one execution."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        """True when the command exited 0."""
        return self.exit_code == 0


class SandboxedExecutor:
    """Execute shell commands inside a jail with policy checks.

    Args:
        jail: Directory the process is confined to (created if missing).
        timeout_s: Per-command timeout in seconds.
        allowlist: If given, only these executables may run.
        blocklist: Substrings that always block a command.
        audit: Optional AuditLogger.
    """

    def __init__(
        self,
        jail: Path,
        timeout_s: float = 10.0,
        allowlist: tuple[str, ...] | None = DEFAULT_ALLOWED,
        blocklist: tuple[str, ...] = DEFAULT_BLOCKED,
        audit: object | None = None,
    ) -> None:
        self.jail = Path(jail).resolve()
        self.jail.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.allowlist = allowlist
        self.blocklist = blocklist
        self.audit = audit

    def check_policy(self, command: str) -> None:
        """Raise BlockedCommandError if the command violates policy."""
        lowered = command.lower()
        for pat in self.blocklist:
            if pat in lowered:
                raise BlockedCommandError(command, f"matches blocklist pattern {pat!r}")
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            raise BlockedCommandError(command, f"unparseable: {exc}") from exc
        if not tokens:
            raise BlockedCommandError(command, "empty command")
        if self.allowlist is not None and tokens[0] not in self.allowlist:
            raise BlockedCommandError(command, f"{tokens[0]!r} not in allowlist")
        if ".." in tokens and any(t == "cd" for t in tokens):
            raise JailEscapeError(f"cd with .. may escape jail: {command!r}")

    def resolve_in_jail(self, rel: str | Path) -> Path:
        """Resolve a path and guarantee it stays inside the jail."""
        target = (self.jail / rel).resolve()
        if not str(target).startswith(str(self.jail)):
            raise JailEscapeError(f"path {rel!r} escapes jail {self.jail}")
        return target

    def run(self, command: str, attempt: int = 1, dry_run: bool = False) -> ExecResult:
        """Run one command, honouring policy, timeout, jail and dry-run."""
        import time

        from terminal_agent.audit import AuditEntry

        self.check_policy(command)
        if dry_run:
            result = ExecResult(command, 0, "[dry-run] not executed", "", 0.0, True)
        else:
            start = time.monotonic()
            env = {**os.environ, "TERMINAL_AGENT_JAIL": str(self.jail)}
            try:
                proc = subprocess.run(
                    command, shell=True, cwd=self.jail, capture_output=True,
                    text=True, timeout=self.timeout_s, env=env, check=False,
                )
                result = ExecResult(
                    command, proc.returncode, proc.stdout, proc.stderr,
                    time.monotonic() - start,
                )
            except subprocess.TimeoutExpired:
                result = ExecResult(
                    command, 124, "", f"timeout after {self.timeout_s}s",
                    time.monotonic() - start,
                )
        if self.audit is not None:
            self.audit.log(AuditEntry(  # type: ignore[attr-defined]
                command=command, exit_code=result.exit_code,
                duration_s=round(result.duration_s, 4), attempt=attempt,
                dry_run=dry_run, stdout_preview=result.stdout[:200],
                stderr_preview=result.stderr[:200],
            ))
        return result
