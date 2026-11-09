"""Tests for terminal-agent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from terminal_agent.audit import AuditLogger
from terminal_agent.cli import main
from terminal_agent.debugger import SelfDebugLoop, suggest_fix
from terminal_agent.errors import BlockedCommandError, JailEscapeError
from terminal_agent.executor import SandboxedExecutor


@pytest.fixture()
def executor(tmp_path: Path) -> SandboxedExecutor:
    return SandboxedExecutor(jail=tmp_path)


def test_echo_succeeds(executor: SandboxedExecutor) -> None:
    r = executor.run("echo hello")
    assert r.ok and "hello" in r.stdout

def test_blocklist_blocks_sudo(executor: SandboxedExecutor) -> None:
    with pytest.raises(BlockedCommandError):
        executor.run("sudo ls")

def test_blocklist_blocks_rm_rf_root(executor: SandboxedExecutor) -> None:
    with pytest.raises(BlockedCommandError):
        executor.run("rm -rf /")

def test_allowlist_blocks_unknown(executor: SandboxedExecutor) -> None:
    with pytest.raises(BlockedCommandError):
        executor.run("nonexistenttool --help")

def test_timeout(executor: SandboxedExecutor) -> None:
    ex = SandboxedExecutor(jail=executor.jail, timeout_s=0.2, allowlist=("python3",))
    r = ex.run("python3 -c 'import time; time.sleep(2)'")
    assert r.exit_code == 124

def test_jail_resolution(executor: SandboxedExecutor, tmp_path: Path) -> None:
    inside = executor.resolve_in_jail("a/b.txt")
    assert str(inside).startswith(str(tmp_path.resolve()))
    with pytest.raises(JailEscapeError):
        executor.resolve_in_jail("../../etc/passwd")

def test_dry_run_does_not_execute(executor: SandboxedExecutor) -> None:
    r = executor.run("echo should-not-run", dry_run=True)
    assert r.dry_run and "dry-run" in r.stdout

def test_audit_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    audit = AuditLogger(log)
    ex = SandboxedExecutor(jail=tmp_path / "jail", audit=audit)
    ex.run("echo audited")
    rows = audit.read_file()
    assert len(rows) == 1 and rows[0]["command"] == "echo audited"
    json.loads(log.read_text().splitlines()[0])

def test_suggest_fix_typo() -> None:
    assert suggest_fix("ehco hi", "command not found") == "echo hi"

def test_suggest_fix_python() -> None:
    fix = suggest_fix("python --version", "")
    assert fix is not None and fix.startswith("python3")

def test_self_debug_recovers_typo(executor: SandboxedExecutor) -> None:
    # ehco is not in allowlist, so allow it via custom executor
    ex = SandboxedExecutor(jail=executor.jail, allowlist=None)
    outcome = SelfDebugLoop(ex, max_retries=3).run("ehco recovered")
    assert outcome.success and "recovered" in (outcome.final.stdout if outcome.final else "")

def test_self_debug_python_to_python3(executor: SandboxedExecutor) -> None:
    outcome = SelfDebugLoop(executor, max_retries=3).run("python --version")
    assert outcome.success

def test_self_debug_missing_file(executor: SandboxedExecutor) -> None:
    outcome = SelfDebugLoop(executor, max_retries=3).run("cat missing.txt")
    assert outcome.success

def test_edge_empty_command(executor: SandboxedExecutor) -> None:
    with pytest.raises(BlockedCommandError):
        executor.run("   ")

def test_edge_unparseable(executor: SandboxedExecutor) -> None:
    with pytest.raises(BlockedCommandError):
        executor.run("echo 'unterminated")

def test_cli_demo_e2e(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "demo:" in out and "tasks succeeded" in out

def test_cli_run_e2e(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code = main(["run", "echo cli-works", "--jail", str(tmp_path)])
    assert code == 0
    assert "cli-works" in capsys.readouterr().out

def test_cli_dry_run(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["run", "echo x", "--jail", str(tmp_path), "--dry-run"]) == 0
    assert "success: True" in capsys.readouterr().out
