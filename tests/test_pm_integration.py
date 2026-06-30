"""Tests for PM integration improvements (Phase 1-5 of P0-P3 plan)."""

import json
import sys
from pathlib import Path

import pytest

import loop_kit.orchestrator as orchestrator

from loop_kit.orchestrator import (
    _configure_loop_paths,
    _resolve_paths,
    _copy_outcome_file,
    _execute_verification_check,
    _extract_knowledge_from_round,
    _load_preflight_policy,
    _apply_preflight_to_prompt,
    _persist_knowledge_updates,
)


def _setup_loop_dir(monkeypatch, tmp_path: Path) -> Path:
    loop_dir = tmp_path / ".loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
    orchestrator._configure_loop_paths(loop_dir)
    return loop_dir


class TestFailWithStateWritesSummary:
    """Phase 1 (P0): _fail_with_state produces summary.json."""

    def test_fail_with_state_writes_summary(self, tmp_path: Path, monkeypatch) -> None:
        _setup_loop_dir(monkeypatch, tmp_path)
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _: False)
        state = {
            "state": orchestrator.STATE_AWAITING_WORK,
            "round": 1,
            "task_id": "T-999",
            "run_id": "run-test",
            "base_sha": "abc123",
            "head_sha": "def456",
            "round_details": [],
        }
        resolved = _resolve_paths()
        resolved.summary.unlink(missing_ok=True)

        with pytest.raises(SystemExit):
            orchestrator._fail_with_state(
                state,
                outcome="test_failure",
                message="deliberate failure for test",
                exit_code=orchestrator.EXIT_GENERAL_ERROR,
                paths=resolved,
            )

        assert resolved.summary.exists(), "summary.json was not written by _fail_with_state"
        data = json.loads(resolved.summary.read_text(encoding="utf-8"))
        assert data["outcome"] == "test_failure"
        assert data["exit_code"] == orchestrator.EXIT_GENERAL_ERROR
        assert "deliberate" in str(data.get("review_blocking", []))


class TestCmdStatusJson:
    """Phase 2 (P1): cmd_status --json produces valid JSON."""

    def test_status_json_output(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _setup_loop_dir(monkeypatch, tmp_path)
        orchestrator.cmd_status(json_output=True, outcome_only=False, paths=_resolve_paths())
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "state" in data
        assert "round" in data
        assert "task_id" in data
        assert "bus_files" in data

    def test_status_json_outcome_only_terminal(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _setup_loop_dir(monkeypatch, tmp_path)
        state = {
            "state": orchestrator.STATE_DONE,
            "round": 1,
            "task_id": "T-998",
            "run_id": "run-test",
            "outcome": "approved",
            "base_sha": "abc",
            "head_sha": "def",
        }
        orchestrator._save_state(state, paths=_resolve_paths())
        orchestrator.cmd_status(json_output=True, outcome_only=True, paths=_resolve_paths())
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"outcome": "approved"}


class TestVerificationExecution:
    """Phase 3 (P2): _execute_verification_check safe execution."""

    def test_verification_pass(self) -> None:
        result = _execute_verification_check({
            "command": "python -c 'print(42)'",
            "expected_output": "42",
            "timeout_sec": 5,
        })
        assert result["passed"] is True
        assert "42" in result["output"]
        assert result["exit_code"] == 0

    def test_verification_fail_wrong_output(self) -> None:
        result = _execute_verification_check({
            "command": "python -c 'print(42)'",
            "expected_output": "WRONG",
            "timeout_sec": 5,
        })
        assert result["passed"] is False

    def test_verification_timeout(self) -> None:
        result = _execute_verification_check({
            "command": "python -c 'import time; time.sleep(10)'",
            "timeout_sec": 1,
        })
        assert result["passed"] is False
        assert "timed out" in result["output"].lower()

    def test_verification_error(self) -> None:
        result = _execute_verification_check({
            "command": "no_such_command_xyzzy",
            "timeout_sec": 5,
        })
        assert result["passed"] is False
        assert result["exit_code"] != 0

    def test_verification_empty_command(self) -> None:
        result = _execute_verification_check({"command": ""})
        assert result["passed"] is False
        assert "(no command)" in result["output"]


class TestPreflightPolicy:
    """Phase 4 (P2): preflight policy loading and prompt generation."""

    def test_load_preflight_json(self, tmp_path: Path, monkeypatch) -> None:
        loop_dir = _setup_loop_dir(monkeypatch, tmp_path)
        (loop_dir / "preflight.json").write_text(json.dumps({
            "forbidden_patterns": ["sudo"],
            "max_file_size_mb": 10,
        }), encoding="utf-8")
        policy = _load_preflight_policy(paths=_resolve_paths())
        assert policy.get("forbidden_patterns") == ["sudo"]
        assert policy.get("max_file_size_mb") == 10

    def test_apply_preflight_to_prompt(self) -> None:
        policy = {
            "forbidden_patterns": ["sudo", "rm -rf"],
            "max_file_size_mb": 5,
            "require_tests": True,
        }
        text = _apply_preflight_to_prompt(policy)
        assert "NEVER use the following patterns" in text
        assert "sudo" in text
        assert "5 MB" in text
        assert "pytest" in text

    def test_empty_policy_returns_empty_string(self) -> None:
        assert _apply_preflight_to_prompt({}) == ""

    def test_load_preflight_missing_returns_empty(self, tmp_path: Path, monkeypatch) -> None:
        loop_dir = _setup_loop_dir(monkeypatch, tmp_path)
        # Ensure no preflight file exists
        for ext in (".yaml", ".json"):
            p = loop_dir / f"preflight{ext}"
            if p.exists():
                p.unlink()
        policy = _load_preflight_policy(paths=_resolve_paths())
        assert policy == {}


class TestKnowledgeExtraction:
    """Phase 5 (P3): knowledge extraction from work/review reports."""

    def test_extract_patterns_from_notes(self) -> None:
        work = {
            "notes": "Created a new CLI parser. Used argparse for handling. Fixed a bug in config loading.",
            "files_changed": ["cli.py", "config.py"],
        }
        result = _extract_knowledge_from_round(work, None)
        patterns = result.get("patterns", [])
        assert len(patterns) >= 2

    def test_extract_pitfalls_from_review(self) -> None:
        work = {"notes": "Wrote some code.", "files_changed": ["main.py"]}
        review = {
            "decision": "changes_required",
            "blocking_issues": [
                {"description": "Missing type annotations on public functions"},
                {"detail": "Forgot to handle edge case"},
            ],
            "non_blocking_suggestions": ["Consider adding docstrings"],
        }
        result = _extract_knowledge_from_round(work, review)
        pitfalls = result.get("pitfalls", [])
        assert len(pitfalls) >= 2

    def test_extract_facts_from_notes(self) -> None:
        work = {
            "notes": "Fixed the login handler to handle expired tokens.",
            "files_changed": ["auth.py"],
        }
        result = _extract_knowledge_from_round(work, None)
        facts = result.get("facts", [])
        assert len(facts) >= 1

    def test_persist_knowledge_updates(self, tmp_path: Path, monkeypatch) -> None:
        _setup_loop_dir(monkeypatch, tmp_path)
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _: False)
        from datetime import datetime, timezone

        now = datetime.now(tz=timezone.utc)
        monkeypatch.setattr(orchestrator._normalize_pattern_entry,
                           "__defaults__", None)
        # Mock _normalize_pattern_entry to accept simpler args
        orig = orchestrator._normalize_pattern_entry

        def mock_normalize(entry, *, now_utc=None, source_version=""):
            return ({"pattern": str(entry.get("pattern", "")), "category": str(entry.get("category", "auto")), "confidence": 0.5, "last_verified": "2025-01-01T00:00:00Z"}, True, False)
        monkeypatch.setattr(orchestrator, "_normalize_pattern_entry", mock_normalize)
        monkeypatch.setattr(orchestrator, "_sync_knowledge_sqlite_index", lambda **kw: {"row_count": 1, "deduped": 0, "fts_available": False})
        monkeypatch.setattr(orchestrator, "_dedupe_pattern_entries", lambda entries: entries)
        monkeypatch.setattr(orchestrator, "_write_patterns_jsonl", lambda entries, paths=None: None)
        monkeypatch.setattr(orchestrator, "_sync_knowledge_sqlite_index", lambda **kw: {"row_count": 1, "deduped": 0, "fts_available": False})
        updates = {
            "pitfalls": ["Test pitfall: always validate input"],
            "patterns": ["Test pattern: use context managers"],
        }
        resolved = _resolve_paths()
        _persist_knowledge_updates(updates, paths=resolved)
        pitfalls_text = resolved.pitfalls.read_text(encoding="utf-8")
        assert "validate input" in pitfalls_text


class TestOutcomeFileCli:
    """Phase 1 (P0): --outcome-file copies summary.json."""

    def test_copy_outcome_file(self, tmp_path: Path, monkeypatch) -> None:
        _setup_loop_dir(monkeypatch, tmp_path)
        resolved = _resolve_paths()
        resolved.summary.write_text(json.dumps({"outcome": "approved"}), encoding="utf-8")
        dest = tmp_path / "out" / "result.json"
        _copy_outcome_file(str(dest), paths=resolved)
        assert dest.exists()
        data = json.loads(dest.read_text(encoding="utf-8"))
        assert data["outcome"] == "approved"

    def test_copy_outcome_file_no_source(self, tmp_path: Path, monkeypatch, capsys) -> None:
        _setup_loop_dir(monkeypatch, tmp_path)
        resolved = _resolve_paths()
        resolved.summary.unlink(missing_ok=True)
        dest = tmp_path / "missing.json"
        _copy_outcome_file(str(dest), paths=resolved)
        assert not dest.exists()
        captured = capsys.readouterr()
        assert "summary.json not found" in captured.out + captured.err

    def test_copy_outcome_file_none_skips(self, tmp_path: Path, monkeypatch) -> None:
        _setup_loop_dir(monkeypatch, tmp_path)
        _copy_outcome_file(None, paths=_resolve_paths())
        # Should not raise, no side effects
