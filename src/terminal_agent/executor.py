"""Policy-gated executor: argv-only execution, no shell.

Security model (policy-gating, NOT a sandbox — see README Limitations):
- Commands are parsed with shlex and executed via subprocess with
  ``shell=False``. There is no shell to interpret metacharacters.
- Shell metacharacters outside quotes (``; & | $ ` > <`` and newlines)
  are rejected outright, so a command string can never smuggle a second
  command, substitution, pipe or redirect.
- The child environment is scrubbed to a minimal set (PATH, HOME=jail,
  LANG) — parent secrets in os.environ are never inherited.
- Path-like arguments are resolved and must stay inside the jail
  (``Path.is_relative_to`` — a sibling like ``jail-evil`` does NOT pass).
- Every attempt is audited, including BLOCKED ones.
- ``python3`` stays on the default allowlist for interpreter checks, but
  code-execution forms (``-c``, ``*.py`` scripts) require
  ``allow_code_exec=True``. Bare ``python`` is not allowlisted at all.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from terminal_agent.errors import BlockedCommandError, JailEscapeError

DEFAULT_BLOCKED: tuple[str, ...] = (
    "sudo", "su ", "rm -rf /", "rm -rf ~", "mkfs", "dd if=", ":(){",
    "chmod -r 777 /", "shutdown", "reboot", "halt", "poweroff", "kill -9 1",
)
DEFAULT_ALLOWED: tuple[str, ...] = (
    "echo", "ls", "cat", "pwd", "python3", "printf", "head",
    "tail", "grep", "wc", "touch", "mkdir", "date", "whoami", "true",
    "false", "test", "basename", "dirname", "sort", "uniq", "tr", "cut",
)
#: Programs whose invocation can execute arbitrary code.
CODE_EXEC_PROGRAMS: tuple[str, ...] = ("python3", "python")


def find_shell_metachar(command: str) -> str | None:
    """Return the first shell metacharacter used *as shell syntax*.

    Quote-aware: characters inside single quotes are literal data (and
    there is no shell to reinterpret them anyway); ``$`` and backticks
    inside double quotes still count, as a shell would expand them.
    Newlines are always rejected.
    """
    in_single = False
    in_double = False
    i = 0
    while i < len(command):
        ch = command[i]
        if ch in "\n\r":
            return ch
        if ch == "\\" and not in_single:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif in_double and ch in "`$":
            return ch
        elif not in_single and not in_double and ch in ";&|<>`$":
            return ch
        i += 1
    return None


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
    """Execute commands under a strict policy gate inside a jail directory.

    This is policy-gating, not OS-level isolation: an allowlisted program
    can still do whatever that program can do inside the jail. Use a
    container/VM when you need a hard boundary.

    Args:
        jail: Working directory the process is confined to (created).
        timeout_s: Per-command timeout in seconds.
        allowlist: If given, only these executables may run.
        blocklist: Substrings that always block a command.
        audit: Optional AuditLogger; blocked attempts are logged too.
        allow_code_exec: Permit code-execution forms (``python3 -c``,
            ``python3 script.py``). Default False.
    """

    def __init__(
        self,
        jail: Path,
        timeout_s: float = 10.0,
        allowlist: tuple[str, ...] | None = DEFAULT_ALLOWED,
        blocklist: tuple[str, ...] = DEFAULT_BLOCKED,
        audit: object | None = None,
        allow_code_exec: bool = False,
    ) -> None:
        self.jail = Path(jail).resolve()
        self.jail.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.allowlist = allowlist
        self.blocklist = blocklist
        self.audit = audit
        self.allow_code_exec = allow_code_exec

    # -- policy ---------------------------------------------------------

    def check_policy(self, command: str) -> list[str]:
        """Validate a command; return its argv tokens or raise.

        Raises:
            BlockedCommandError: metacharacters, blocklist, allowlist,
                code-exec gating, empty/unparseable commands.
            JailEscapeError: a path argument would escape the jail.
        """
        if not command.strip():
            raise BlockedCommandError(command, "empty command")
        meta = find_shell_metachar(command)
        if meta is not None:
            raise BlockedCommandError(
                command, f"shell metacharacter {meta!r} is not allowed (no shell is used)"
            )
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
        if tokens[0] in CODE_EXEC_PROGRAMS and not self.allow_code_exec:
            args = tokens[1:]
            if "-c" in args or any(a.endswith(".py") for a in args):
                raise BlockedCommandError(
                    command,
                    "code execution via python3 -c / script requires allow_code_exec",
                )
        for token in tokens[1:]:
            self._check_path_token(token, command)
        return tokens

    def _check_path_token(self, token: str, command: str) -> None:
        """Reject path-like arguments that resolve outside the jail."""
        if token == "..":
            raise JailEscapeError(f"path '..' escapes jail in {command!r}")
        path = Path(token)
        if path.is_absolute():
            if not path.resolve().is_relative_to(self.jail):
                raise JailEscapeError(f"absolute path {token!r} is outside the jail")
        elif "/" in token:
            target = (self.jail / token).resolve()
            if not target.is_relative_to(self.jail):
                raise JailEscapeError(f"path {token!r} escapes jail {self.jail}")

    def resolve_in_jail(self, rel: str | Path) -> Path:
        """Resolve a path and guarantee it stays inside the jail."""
        target = (self.jail / rel).resolve()
        if not target.is_relative_to(self.jail):
            raise JailEscapeError(f"path {rel!r} escapes jail {self.jail}")
        return target

    # -- execution --------------------------------------------------------

    def _audit(self, command: str, exit_code: int, duration_s: float, attempt: int,
               dry_run: bool, stdout: str, stderr: str, blocked: bool = False) -> None:
        if self.audit is None:
            return
        from terminal_agent.audit import AuditEntry

        self.audit.log(AuditEntry(  # type: ignore[attr-defined]
            command=command, exit_code=exit_code,
            duration_s=round(duration_s, 4), attempt=attempt,
            dry_run=dry_run, stdout_preview=stdout[:200],
            stderr_preview=stderr[:200], blocked=blocked,
        ))

    def _scrubbed_env(self) -> dict[str, str]:
        """Minimal child environment — parent secrets are not inherited."""
        return {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self.jail),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TERMINAL_AGENT_JAIL": str(self.jail),
        }

    def run(self, command: str, attempt: int = 1, dry_run: bool = False) -> ExecResult:
        """Run one command, honouring policy, timeout, jail and dry-run.

        Blocked commands are written to the audit log *before* the
        exception propagates, so the log records attacks, not just runs.
        """
        try:
            tokens = self.check_policy(command)
        except (BlockedCommandError, JailEscapeError) as exc:
            self._audit(command, -1, 0.0, attempt, dry_run, "", str(exc), blocked=True)
            raise
        if dry_run:
            result = ExecResult(command, 0, "[dry-run] not executed", "", 0.0, True)
            self._audit(command, 0, 0.0, attempt, True, result.stdout, "", blocked=False)
            return result
        start = time.monotonic()
        try:
            proc = subprocess.run(
                tokens, shell=False, cwd=self.jail, capture_output=True,
                text=True, timeout=self.timeout_s, env=self._scrubbed_env(),
                check=False,
            )
            result = ExecResult(
                command, proc.returncode, proc.stdout, proc.stderr,
                time.monotonic() - start,
            )
        except FileNotFoundError:
            result = ExecResult(
                command, 127, "", f"command not found: {tokens[0]}",
                time.monotonic() - start,
            )
        except subprocess.TimeoutExpired:
            result = ExecResult(
                command, 124, "", f"timeout after {self.timeout_s}s",
                time.monotonic() - start,
            )
        self._audit(command, result.exit_code, result.duration_s, attempt,
                    dry_run, result.stdout, result.stderr)
        return result
