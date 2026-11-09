# Architecture

## Components
- `executor.SandboxedExecutor` — policy check (allowlist/blocklist), cwd jail, timeout, subprocess.
- `debugger.SelfDebugLoop` — run, inspect stderr, apply deterministic heuristic fix, retry.
- `audit.AuditLogger` — append-only JSONL plus in-memory entries.
- `cli` — `run` and `demo` subcommands.

## Safety model
Deny by default: allowlist first, blocklist always, jail containment via resolved paths,
per-command timeout, dry-run that never executes. Every attempt is audited.

## Data flow
Task -> policy -> subprocess (cwd=jail) -> result -> [fail? heuristic fix -> retry] -> audit.
