"""Append-only JSONL audit logging."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AuditEntry:
    """One audited execution."""

    command: str
    exit_code: int
    duration_s: float
    attempt: int = 1
    dry_run: bool = False
    blocked: bool = False
    timestamp: float = field(default_factory=time.time)
    stdout_preview: str = ""
    stderr_preview: str = ""


class AuditLogger:
    """Writes audit entries as JSON lines; in-memory when no path is given."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.entries: list[AuditEntry] = []

    def log(self, entry: AuditEntry) -> None:
        """Record an entry in memory and, if configured, on disk."""
        self.entries.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(entry)) + "\n")

    def read_file(self) -> list[dict[str, object]]:
        """Read back entries from the JSONL file (empty if none)."""
        if self.path is None or not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
