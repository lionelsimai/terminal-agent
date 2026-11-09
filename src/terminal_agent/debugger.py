"""Self-debug loop: run -> capture error -> heuristic fix -> retry."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from terminal_agent.errors import BlockedCommandError
from terminal_agent.executor import ExecResult, SandboxedExecutor


def suggest_fix(command: str, stderr: str) -> str | None:
    """Return a corrected command for common failures, else None.

    Heuristics (deterministic, testable, no LLM required):
    - ``python`` not found / bare python -> ``python3``
    - ``cat``/``head``/``tail`` on a missing file -> create it, then retry
    - missing directory for ``mkdir`` without -p is already idempotent-safe
    - typo ``ehco`` -> ``echo``, ``sl`` -> ``ls``, ``cta`` -> ``cat``
    - missing file for other readers -> ``touch`` it first via ``&&``
    """
    low = stderr.lower()
    tokens = shlex.split(command) if command.strip() else []
    if not tokens:
        return None
    typo = {"ehco": "echo", "sl": "ls", "cta": "cat", "prnt": "printf"}
    if tokens[0] in typo:
        return shlex.join([typo[tokens[0]], *tokens[1:]])
    if tokens[0] == "python":
        # Prefer python3 whenever the failing executable is bare python.
        return shlex.join(["python3", *tokens[1:]])
    missing = re.search(r"(?:no such file or directory|not found)[:\s]*([^\n]*)", low)
    if "no such file" in low and tokens[0] in {"cat", "head", "tail"} and len(tokens) >= 2:
        target = tokens[-1]
        return f"touch {shlex.quote(target)} && {command}"
    if missing and tokens[0] == "ls" and len(tokens) >= 2:
        target = tokens[-1]
        return f"mkdir -p {shlex.quote(target)} && {command}"
    return None


@dataclass
class DebugOutcome:
    """Outcome of the self-debug loop."""

    success: bool
    attempts: int
    final_command: str
    history: list[ExecResult] = field(default_factory=list)

    @property
    def final(self) -> ExecResult | None:
        """Last execution result, if any."""
        return self.history[-1] if self.history else None


class SelfDebugLoop:
    """Retry a failing command with heuristic fixes up to ``max_retries``."""

    def __init__(self, executor: SandboxedExecutor, max_retries: int = 3) -> None:
        self.executor = executor
        self.max_retries = max_retries

    def run(self, command: str, dry_run: bool = False) -> DebugOutcome:
        """Run, fix and retry until success or retries are exhausted."""
        history: list[ExecResult] = []
        current = command
        for attempt in range(1, self.max_retries + 2):
            try:
                result = self.executor.run(current, attempt=attempt, dry_run=dry_run)
            except BlockedCommandError as exc:
                # A policy block on a typo'd command is exactly what the
                # fixer is for: synthesise a failed result and try a fix.
                # Genuinely dangerous commands have no fix and will break.
                result = ExecResult(current, 127, "", f"command not found: {exc}", 0.0)
            history.append(result)
            if result.ok or dry_run:
                return DebugOutcome(True, attempt, current, history)
            fix = suggest_fix(current, result.stderr or result.stdout)
            if fix is None or fix == current:
                break
            current = fix
        last_ok = bool(history and history[-1].ok)
        return DebugOutcome(last_ok, len(history), current, history)
