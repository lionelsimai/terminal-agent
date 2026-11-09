"""Benchmark: self-debug success rate on fixture tasks.

Run: python benchmarks/bench.py
Measures success without debug vs with debug on deliberately broken tasks.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from terminal_agent.debugger import SelfDebugLoop
from terminal_agent.executor import SandboxedExecutor

FIXTURES: list[str] = [
    "echo ok", "python --version", "ehco typo-fixed", "cat ghost.txt",
    "ls newdir", "echo second", "python -c 'print(42)'", "cat another.txt",
]


def main() -> int:
    """Run the benchmark and print the headline metric."""
    with tempfile.TemporaryDirectory() as tmp:
        jail = Path(tmp)
        plain = SandboxedExecutor(jail=jail, allowlist=None)
        plain_ok = 0
        for task in FIXTURES:
            try:
                plain_ok += int(plain.run(task).ok)
            except Exception:  # blocked/failed plain runs count as 0
                plain_ok += 0
        loop = SelfDebugLoop(SandboxedExecutor(jail=jail, allowlist=None), max_retries=3)
        debug_ok = sum(int(loop.run(t).success) for t in FIXTURES)
    total = len(FIXTURES)
    print(f"fixture_tasks: {total}")
    print(f"without_debug: {plain_ok}/{total} = {plain_ok / total:.0%}")
    print(f"with_self_debug: {debug_ok}/{total} = {debug_ok / total:.0%}")
    print(f"self_debug_success_rate: {debug_ok / total:.2f}")
    print("target: Top 10 on Terminal-Bench (proxy: >=80% on local fixtures)")
    return 0 if debug_ok / total >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
