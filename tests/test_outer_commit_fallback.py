"""Unit tests for the outer-commit fallback helpers (PM #3369).

Style mirrors tests/test_dsh_backend.py: import via the orchestrator facade,
monkeypatch for env/git boundaries, no real git operations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from loop_kit import orchestrator

# ── env switch ──────────────────────────────────────────────────────────


def test_enabled_default_true_and_env_zero_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOOP_OUTER_COMMIT_FALLBACK", raising=False)
    assert orchestrator._outer_commit_fallback_enabled() is True
    monkeypatch.setenv("LOOP_OUTER_COMMIT_FALLBACK", "0")
    assert orchestrator._outer_commit_fallback_enabled() is False
    monkeypatch.setenv("LOOP_OUTER_COMMIT_FALLBACK", "1")
    assert orchestrator._outer_commit_fallback_enabled() is True


# ── serial whitelist ────────────────────────────────────────────────────


def test_serial_whitelist_from_lanes_union() -> None:
    card = {"lanes": [{"owner_paths": ["a/fib.py", "a/"]}, {"owner_paths": ["b/", "b/x.py"]}]}
    assert orchestrator._serial_outer_commit_whitelist(card) == ["a/fib.py", "a/", "b/", "b/x.py"]


def test_serial_whitelist_from_in_scope() -> None:
    card = {"in_scope": ["coupling/fib.py", "coupling/"]}
    assert orchestrator._serial_outer_commit_whitelist(card) == ["coupling/fib.py", "coupling/"]


def test_serial_whitelist_filters_glob_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    # CT caution #3369-1: glob-style in_scope entries must be filtered out —
    # _owner_paths_overlap only matches literal prefixes.
    card = {"in_scope": ["src/**", "coupling/fib.py"]}
    assert orchestrator._serial_outer_commit_whitelist(card) == ["coupling/fib.py"]


def test_serial_whitelist_empty() -> None:
    assert orchestrator._serial_outer_commit_whitelist({}) == []
    assert orchestrator._serial_outer_commit_whitelist({"in_scope": "not-a-list"}) == []


# ── dirty split ─────────────────────────────────────────────────────────


def _fake_git_at_status(lines: list[str]) -> Any:
    def fake(cwd: Path, *args: str, timeout: float | None = None) -> str:
        if list(args) == ["status", "--porcelain"]:
            return "\n".join(lines) + "\n"
        raise AssertionError(f"unexpected _git_at call: {args}")

    return fake


def test_dirty_split_includes_untracked_in_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_git_at", _fake_git_at_status(["?? coupling/fib.py"]))
    in_scope, out = orchestrator._worktree_dirty_split(Path("/wt"), ["coupling/"])
    assert in_scope == ["coupling/fib.py"]
    assert out == []


def test_dirty_split_reports_tracked_out_of_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_git_at", _fake_git_at_status([" M src/loop_kit/_core.py"]))
    in_scope, out = orchestrator._worktree_dirty_split(Path("/wt"), ["coupling/"])
    assert in_scope == []
    assert out == ["src/loop_kit/_core.py"]


def test_dirty_split_ignores_untracked_out_of_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_git_at", _fake_git_at_status(["?? data/scratch.txt"]))
    in_scope, out = orchestrator._worktree_dirty_split(Path("/wt"), ["coupling/"])
    assert in_scope == []
    assert out == []


def test_dirty_split_filters_loop_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_git_at", _fake_git_at_status(["?? .loop/events.jsonl"]))
    in_scope, out = orchestrator._worktree_dirty_split(Path("/wt"), [".loop/"])
    assert in_scope == []
    assert out == []


# ── core fallback ───────────────────────────────────────────────────────


def _install_fallback_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_lines: list[str],
    commit_fail: bool = False,
) -> dict[str, list]:
    calls: dict[str, list] = {"add": [], "commit": [], "revparse": []}
    # /wt is not a real repo in unit tests — stub the root check alongside git.
    monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda path: True)

    def fake_git(cwd: Path, *args: str, timeout: float | None = None) -> str:
        argv = list(args)
        if argv == ["status", "--porcelain"]:
            return "\n".join(status_lines) + "\n"
        if argv[0] == "add":
            calls["add"].append(argv[1:])
            return ""
        if argv[0] == "commit":
            calls["commit"].append(argv)
            if commit_fail:
                raise RuntimeError("simulated commit failure")
            return ""
        if argv == ["rev-parse", "HEAD"]:
            calls["revparse"].append(argv)
            return "feedbeef\n"
        raise AssertionError(f"unexpected _git_at call: {argv}")

    monkeypatch.setattr(orchestrator, "_git_at", fake_git)
    return calls


def _fallback_kwargs(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "worktree": Path("/wt"),
        "whitelist": ["coupling/"],
        "files_changed": ["coupling/fib.py"],
        "task_id": "t1",
        "round_num": 1,
        "lane_id": "lane_x",
    }
    if overrides:
        base.update(overrides)
    return base


def test_fallback_positive_commit_and_head_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(monkeypatch, status_lines=["?? coupling/fib.py"])
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result == "feedbeef"
    assert calls["add"] == [["--", "coupling/fib.py"]]
    assert len(calls["commit"]) == 1
    assert "[outer-commit]" in calls["commit"][0][2]
    assert "task t1 round 1 lane lane_x" in calls["commit"][0][2]


def test_fallback_negative_true_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(monkeypatch, status_lines=[])
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result is None
    assert calls["commit"] == []


def test_fallback_negative_fc_outside_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(monkeypatch, status_lines=["?? coupling/fib.py"])
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs({"files_changed": ["evil/../etc/passwd"]}))
    assert result is None
    assert calls["commit"] == []


def test_fallback_negative_dirty_not_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(monkeypatch, status_lines=["?? coupling/other.py"])
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result is None
    assert calls["commit"] == []


def test_fallback_negative_out_of_scope_tracked_dirty_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(
        monkeypatch,
        status_lines=["?? coupling/fib.py", " M src/loop_kit/_core.py"],
    )
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result is None
    assert calls["commit"] == []


def test_fallback_negative_no_dirty_in_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(monkeypatch, status_lines=["?? data/scratch.txt"])
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result is None
    assert calls["commit"] == []


def test_fallback_tolerates_untracked_out_of_scope_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(
        monkeypatch,
        status_lines=["?? coupling/fib.py", "?? data/scratch.txt"],
    )
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result == "feedbeef"
    assert calls["add"] == [["--", "coupling/fib.py"]]


def test_fallback_commit_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fallback_git(monkeypatch, status_lines=["?? coupling/fib.py"], commit_fail=True)
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result is None


def test_fallback_never_acquires_repo_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel: list[str] = []
    monkeypatch.setattr(orchestrator, "_acquire_repo_lock", lambda **kwargs: sentinel.append("called") or None)
    _install_fallback_git(monkeypatch, status_lines=["?? coupling/fib.py"])
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert sentinel == []


def test_fallback_env_zero_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fallback_git(monkeypatch, status_lines=["?? coupling/fib.py"])
    monkeypatch.setenv("LOOP_OUTER_COMMIT_FALLBACK", "0")
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs())
    assert result is None
    assert calls["commit"] == []


def test_fallback_normalizes_declared_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # CT caution #3369-2: "./" prefixes and trailing slashes normalize to
    # porcelain form so declared paths still match measured dirt.
    calls = _install_fallback_git(monkeypatch, status_lines=["?? coupling/fib.py"])
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    result = orchestrator._try_outer_commit_fallback(**_fallback_kwargs({"files_changed": ["./coupling/fib.py"]}))
    assert result == "feedbeef"
    assert calls["add"] == [["--", "coupling/fib.py"]]


# ── lane wrapper (PM #3369 T3.1) ─────────────────────────────────────────


def _fake_lane() -> dict:
    return {"lane_id": "lane_x", "owner_paths": ["coupling/"]}


def _fake_handle() -> Any:
    class _H:
        path = Path("/wt")

    return _H()


def test_lane_fallback_triggers_when_head_equals_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "_try_outer_commit_fallback",
        lambda **kwargs: "sha123",
    )
    work = {"head_sha": "base", "files_changed": ["coupling/fib.py"]}
    result = orchestrator._lane_outer_commit_fallback(
        work, _fake_lane(), _fake_handle(), base_sha="base", task_id="t", round_num=1
    )
    assert result == "sha123"


def test_lane_fallback_triggers_when_head_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "_try_outer_commit_fallback",
        lambda **kwargs: "sha456",
    )
    work = {"head_sha": "", "files_changed": ["coupling/fib.py"]}
    result = orchestrator._lane_outer_commit_fallback(
        work, _fake_lane(), _fake_handle(), base_sha="base", task_id="t", round_num=1
    )
    assert result == "sha456"


def test_lane_fallback_skips_when_head_advanced(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    def _core(**kwargs: Any) -> str:
        called.append(True)
        return "sha"

    monkeypatch.setattr(orchestrator, "_try_outer_commit_fallback", _core)
    work = {"head_sha": "advanced", "files_changed": ["coupling/fib.py"]}
    result = orchestrator._lane_outer_commit_fallback(
        work, _fake_lane(), _fake_handle(), base_sha="base", task_id="t", round_num=1
    )
    assert result is None
    assert called == []


def test_lane_fallback_callsite_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _core(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "sha789"

    monkeypatch.setattr(orchestrator, "_try_outer_commit_fallback", _core)
    work = {"head_sha": "base", "files_changed": ["coupling/fib.py"]}
    orchestrator._lane_outer_commit_fallback(
        work, _fake_lane(), _fake_handle(), base_sha="base", task_id="t7", round_num=3
    )
    assert captured["worktree"] == Path("/wt")
    assert captured["whitelist"] == ["coupling/"]
    assert captured["files_changed"] == ["coupling/fib.py"]
    assert captured["task_id"] == "t7"
    assert captured["round_num"] == 3
    assert captured["lane_id"] == "lane_x"
