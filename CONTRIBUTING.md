# Contributing

Thanks for your interest! Contributions are welcome.

## Setup
```bash
git clone https://github.com/lionelsimai/terminal-agent.git
cd terminal-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks before a PR
```bash
ruff check src tests benchmarks
python -m pytest -q
```

## Style
- Fully typed, docstrings on public APIs, no hardcoded secrets (use env vars).
- Keep the offline demo working — no real API keys in tests or examples.
- Add a test for every behaviour change and update CHANGELOG.md.

## Pull requests
Use the PR template, describe the problem and the fix, and paste test output.
