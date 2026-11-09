"""Benchmark: self-debug success rate on fixture tasks.

Run: python benchmarks/bench.py

Both arms run the SHIPPED configuration (default allowlist, policy gate
on). The fixture set deliberately mixes:
- healthy tasks (should pass in both arms),
- tasks the heuristic fixer covers (typos, bare python, missing files),
- held-out failures the fixer does NOT cover (missing-file reads via
  grep/wc/sort, a shell substitution, an absolute path outside the
  jail) — these must fail in both arms, and they keep the headline
  number honest.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from terminal_agent.debugger import SelfDebugLoop
from terminal_agent.executor import SandboxedExecutor

FIXTURES: list[str] = [
    # healthy
    "echo ok", "echo second", "true",
    # fixer-covered failures
    "python --version", "ehco typo-fixed", "cat ghost.txt", "ls newdir",
    # held-out failures (fixer has no pattern for these)
    "grep needle absent.txt", "wc -l absent.txt", "sort absent.txt",
    "echo $HOME", "cat /etc/hostname",
]


def main() -> int:
    """Run the benchmark and print the headline metric."""
    with tempfile.TemporaryDirectory() as tmp:
        jail = Path(tmp)
        plain = SandboxedExecutor(jail=jail)  # shipped config
        plain_ok = 0
        for task in FIXTURES:
            try:
                plain_ok += int(plain.run(task).ok)
            except Exception:  # blocked/failed plain runs count as 0
                plain_ok += 0
        loop = SelfDebugLoop(SandboxedExecutor(jail=jail), max_retries=3)
        debug_ok = sum(int(loop.run(t).success) for t in FIXTURES)
    total = len(FIXTURES)
    print(f"fixture_tasks: {total}")
    print(f"without_debug: {plain_ok}/{total} = {plain_ok / total:.0%}")
    print(f"with_self_debug: {debug_ok}/{total} = {debug_ok / total:.0%}")
    print(f"self_debug_success_rate: {debug_ok / total:.2f}")
    print("fixtures include held-out failures the fixer does not cover;")
    print("target: Top 10 on Terminal-Bench (local fixtures are a proxy only)")
    return 0 if debug_ok > plain_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
