"""Self-debug loop: run -> capture error -> heuristic fix -> retry."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from terminal_agent.errors import BlockedCommandError, JailEscapeError
from terminal_agent.executor import ExecResult, SandboxedExecutor


def suggest_fix(command: str, stderr: str) -> str | None:
    """Return a corrected command for common failures, else None.

    Heuristics (deterministic, testable, no LLM required):
    - ``python`` not found / bare python -> ``python3``
    - ``cat``/``head``/``tail`` on a missing file -> create it, then retry
    - typo ``ehco`` -> ``echo``, ``sl`` -> ``ls``, ``cta`` -> ``cat``
    - ``ls`` on a missing directory -> ``mkdir -p`` it, then retry

    Multi-step fixes are joined with ``&&`` as a *plan notation only*;
    the loop splits them and executes each step separately (no shell).
    Unparseable commands (e.g. unbalanced quotes) yield None, never a
    crash.
    """
    low = stderr.lower()
    try:
        tokens = shlex.split(command) if command.strip() else []
    except ValueError:
        return None
    if not tokens:
        return None
    typo = {"ehco": "echo", "sl": "ls", "cta": "cat", "prnt": "printf"}
    if tokens[0] in typo:
        return shlex.join([typo[tokens[0]], *tokens[1:]])
    if tokens[0] == "python":
        # Prefer python3 whenever the failing executable is bare python.
        return shlex.join(["python3", *tokens[1:]])
    if "no such file" in low and tokens[0] in {"cat", "head", "tail"} and len(tokens) >= 2:
        target = tokens[-1]
        return f"touch {shlex.quote(target)} && {command}"
    missing = re.search(r"(?:no such file or directory|not found)[:\s]*([^\n]*)", low)
    if missing and tokens[0] == "ls" and len(tokens) >= 2:
        target = tokens[-1]
        return f"mkdir -p {shlex.quote(target)} && {command}"
    return None


def _split_steps(fix: str) -> list[str]:
    """Split a fix plan into individually executable steps."""
    return [step.strip() for step in fix.split(" && ") if step.strip()]


@dataclass
class DebugOutcome:
    """Outcome of the self-debug loop."""

    success: bool
    attempts: int
    final_command: str
    history: list[ExecResult] = field(default_factory=list)
    dry_run: bool = False

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
        """Run, fix and retry until success or retries are exhausted.

        In dry-run mode nothing is executed: the command is only
        policy-validated and the outcome's ``success`` stays False —
        a dry run never claims a task succeeded.
        """
        if dry_run:
            try:
                result = self.executor.run(command, attempt=1, dry_run=True)
                return DebugOutcome(False, 1, command, [result], dry_run=True)
            except (BlockedCommandError, JailEscapeError) as exc:
                failed = ExecResult(command, 126, "", str(exc), 0.0)
                return DebugOutcome(False, 1, command, [failed], dry_run=True)
        history: list[ExecResult] = []
        queue: list[str] = [command]
        current = command
        while queue and len(history) <= self.max_retries:
            current = queue.pop(0)
            attempt = len(history) + 1
            try:
                result = self.executor.run(current, attempt=attempt)
            except JailEscapeError as exc:
                # A jail escape is a hard stop: no heuristic may "fix" it.
                history.append(ExecResult(current, 126, "", str(exc), 0.0))
                break
            except BlockedCommandError as exc:
                # A policy block on a typo'd command is exactly what the
                # fixer is for: synthesise a failed result and try a fix.
                # Genuinely dangerous commands have no fix and will break.
                result = ExecResult(current, 127, "", f"command not found: {exc}", 0.0)
            history.append(result)
            if result.ok:
                continue
            if len(history) > self.max_retries:
                break
            fix = suggest_fix(current, result.stderr or result.stdout)
            if fix is None:
                break
            steps = _split_steps(fix)
            if steps == [current]:
                break
            queue = steps + queue
        success = bool(history) and not queue and history[-1].ok
        return DebugOutcome(success, len(history), current, history)
