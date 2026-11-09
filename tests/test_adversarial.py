"""Adversarial bypass suite: classic shell-escape payloads must all be
blocked by the policy gate AND recorded in the audit log as blocked."""
from __future__ import annotations

from pathlib import Path

import pytest

from terminal_agent.audit import AuditLogger
from terminal_agent.debugger import SelfDebugLoop, suggest_fix
from terminal_agent.errors import BlockedCommandError, JailEscapeError
from terminal_agent.executor import SandboxedExecutor

BYPASS_PAYLOADS: list[str] = [
    "echo hi; cat /etc/passwd",
    "echo $(whoami)",
    "echo `whoami`",
    "echo hi | sh",
    "echo hi > /tmp/x",
    "echo a && echo b",
    "echo $HOME",
    "cat ../secret.txt",
    "cat ../../etc/passwd",
    "cat /etc/passwd",
    "cat /etc/hostname",
]


@pytest.fixture()
def audited(tmp_path: Path) -> tuple[SandboxedExecutor, AuditLogger]:
    audit = AuditLogger()
    return SandboxedExecutor(jail=tmp_path / "jail", audit=audit), audit


@pytest.mark.parametrize("payload", BYPASS_PAYLOADS)
def test_bypass_blocked_and_audited(
    audited: tuple[SandboxedExecutor, AuditLogger], payload: str
) -> None:
    executor, audit = audited
    with pytest.raises((BlockedCommandError, JailEscapeError)):
        executor.run(payload)
    blocked = [e for e in audit.entries if e.blocked]
    assert len(blocked) == 1 and blocked[0].command == payload


def test_sibling_prefix_jail_evil(tmp_path: Path) -> None:
    jail = tmp_path / "jail"
    evil = tmp_path / "jail-evil"
    evil.mkdir(parents=True)
    (evil / "secret.txt").write_text("sibling secret")
    executor = SandboxedExecutor(jail=jail)
    with pytest.raises(JailEscapeError):
        executor.resolve_in_jail("../jail-evil/secret.txt")
    with pytest.raises(JailEscapeError):
        executor.run("cat ../jail-evil/secret.txt")


def test_blocked_attempt_in_audit_file(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    audit = AuditLogger(log)
    executor = SandboxedExecutor(jail=tmp_path / "jail", audit=audit)
    with pytest.raises(BlockedCommandError):
        executor.run("sudo ls")
    rows = audit.read_file()
    assert len(rows) == 1 and rows[0]["blocked"] is True


def test_environment_is_scrubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TA_SENTINEL_SECRET", "must-not-leak")
    executor = SandboxedExecutor(jail=tmp_path, allow_code_exec=True)
    r = executor.run("python3 -c 'import os; print(sorted(os.environ))'")
    assert r.ok
    assert "TA_SENTINEL_SECRET" not in r.stdout
    assert "TERMINAL_AGENT_JAIL" in r.stdout


def test_code_exec_gated_by_default(tmp_path: Path) -> None:
    executor = SandboxedExecutor(jail=tmp_path)
    with pytest.raises(BlockedCommandError):
        executor.run("python3 -c 'print(1)'")
    with pytest.raises(BlockedCommandError):
        executor.run("python3 script.py")
    # Interpreter *checks* stay allowed by default.
    assert executor.run("python3 --version").ok
    allowed = SandboxedExecutor(jail=tmp_path, allow_code_exec=True)
    r = allowed.run("python3 -c 'print(42)'")
    assert r.ok and "42" in r.stdout


def test_bare_python_not_allowlisted(tmp_path: Path) -> None:
    executor = SandboxedExecutor(jail=tmp_path)
    with pytest.raises(BlockedCommandError):
        executor.run("python --version")


def test_dry_run_never_reports_success(tmp_path: Path) -> None:
    executor = SandboxedExecutor(jail=tmp_path)
    outcome = SelfDebugLoop(executor).run("false", dry_run=True)
    assert outcome.success is False and outcome.dry_run is True
    assert outcome.final is not None and "not executed" in outcome.final.stdout


def test_suggest_fix_unbalanced_quotes_no_crash() -> None:
    assert suggest_fix("echo 'unterminated", "syntax error") is None
    assert suggest_fix('echo "unterminated', "syntax error") is None


def test_self_debug_cannot_fix_bypass(tmp_path: Path) -> None:
    executor = SandboxedExecutor(jail=tmp_path)
    outcome = SelfDebugLoop(executor, max_retries=3).run("echo hi; cat /etc/passwd")
    assert outcome.success is False
    assert not (tmp_path / "passwd").exists()
    leaked = "".join(r.stdout for r in outcome.history)
    assert "root:" not in leaked  # /etc/passwd content never surfaced
