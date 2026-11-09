"""Command-line interface for terminal-agent."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from terminal_agent.audit import AuditLogger
from terminal_agent.debugger import SelfDebugLoop
from terminal_agent.executor import SandboxedExecutor

DEMO_TASKS: list[str] = [
    "echo hello from terminal-agent",
    "python --version",
    "ehco self-debug works",
    "cat notes.txt",
]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="terminal-agent", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run a task (shell command) with self-debug")
    run_p.add_argument("task")
    run_p.add_argument("--max-retries", type=int, default=3)
    run_p.add_argument("--timeout", type=float, default=10.0)
    run_p.add_argument("--jail", default=None)
    run_p.add_argument("--audit-log", default=None)
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--allow-code-exec", action="store_true",
                       help="Allow python3 -c / script execution (arbitrary code)")
    sub.add_parser("demo", help="Run the offline demo tasks")
    return parser


def _run_one(task: str, jail: Path, retries: int, timeout: float,
             audit_path: str | None, dry_run: bool, allow_code_exec: bool = False) -> int:
    audit = AuditLogger(Path(audit_path) if audit_path else None)
    executor = SandboxedExecutor(jail=jail, timeout_s=timeout, audit=audit,
                                 allow_code_exec=allow_code_exec)
    outcome = SelfDebugLoop(executor, max_retries=retries).run(task, dry_run=dry_run)
    final = outcome.final
    print(f"task: {task}")
    print(f"final_command: {outcome.final_command}")
    if dry_run:
        print(f"attempts: {outcome.attempts} success: not executed (dry-run)")
    else:
        print(f"attempts: {outcome.attempts} success: {outcome.success}")
    if final is not None:
        if final.stdout.strip():
            print(f"stdout: {final.stdout.strip()}")
        if final.stderr.strip():
            print(f"stderr: {final.stderr.strip()}")
    print(f"audit_entries: {len(audit.entries)}")
    if dry_run:
        # Exit 0 means "policy-valid and would be attempted", never success.
        return 0 if (final is not None and final.dry_run) else 1
    return 0 if outcome.success else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    if args.cmd == "demo":
        with tempfile.TemporaryDirectory() as tmp:
            jail = Path(tmp)
            audit = AuditLogger()
            executor = SandboxedExecutor(jail=jail, audit=audit)
            loop = SelfDebugLoop(executor, max_retries=3)
            ok = 0
            for task in DEMO_TASKS:
                outcome = loop.run(task)
                status = "PASS" if outcome.success else "FAIL"
                ok += int(outcome.success)
                out = outcome.final.stdout.strip() if outcome.final else ""
                print(f"[{status}] {task!r} -> {outcome.final_command!r} attempts={outcome.attempts} output={out!r}")
            print(f"demo: {ok}/{len(DEMO_TASKS)} tasks succeeded")
            print(json.dumps({"succeeded": ok, "total": len(DEMO_TASKS)}))
            return 0 if ok == len(DEMO_TASKS) else 1
    if args.jail:
        return _run_one(args.task, Path(args.jail), args.max_retries, args.timeout,
                        args.audit_log, args.dry_run, args.allow_code_exec)
    # No explicit jail: use a TemporaryDirectory so nothing leaks on disk.
    with tempfile.TemporaryDirectory(prefix="ta-jail-") as tmp:
        return _run_one(args.task, Path(tmp), args.max_retries, args.timeout,
                        args.audit_log, args.dry_run, args.allow_code_exec)


if __name__ == "__main__":
    sys.exit(main())
