# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-11-09

World-class remediation after an adversarial audit (was scored 3/10, FIX).

### Security
- Replaced `shell=True` with argv-only execution (`shell=False`); shell
  metacharacters used as shell syntax are rejected (quote-aware scan).
- Jail now uses `Path.is_relative_to` (sibling-prefix `jail-evil` escape
  fixed) and is actually enforced on path arguments during execution.
- Child environment scrubbed to PATH / HOME / LANG; parent secrets are
  no longer inherited.
- Blocked attempts are written to the audit log before raising.
- Bare `python` removed from the default allowlist; `python3 -c` and
  `python3 script.py` require `allow_code_exec` / `--allow-code-exec`.

### Fixed
- Dry-run no longer reports success: output is labelled
  "not executed (dry-run)" and the loop outcome stays unsuccessful.
- `suggest_fix` no longer crashes on unbalanced quotes.
- CLI no longer leaks a temp jail directory per run.
- Self-debug multi-step fixes (`touch x && cat x`) are executed as
  separate argv steps — the `&&` never reaches a shell.

### Changed
- Benchmark runs the shipped configuration (allowlist on) over 12
  fixtures including held-out failures the fixer does not cover:
  without debug 25%, with self-debug 58% (was: 100% on 8 fixer-covered
  fixtures with the allowlist disabled — not comparable).
- README wording corrected from "sandboxed" to "policy-gated
  execution", with residual risks stated plainly.
- Added an adversarial bypass test suite (11 payloads, all blocked and
  audited). Two pre-existing tests were adapted where they enshrined
  audited bugs (dry-run success string; timeout test now opts into
  code execution explicitly).

## [0.1.0] - 2026-11-09

### Added
- Initial public release: core engine, CLI, offline demo, tests, benchmarks, CI.
