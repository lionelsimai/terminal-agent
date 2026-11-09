"""Offline demo: run with `python examples/demo.py`."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from terminal_agent.cli import main

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as _tmp:
        raise SystemExit(main(["demo"]))
