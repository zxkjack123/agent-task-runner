"""Unit tests for the dsh SDK backend (PM #2665, T1.1).

All tests inject a fake ``deepseek_harness`` module via sys.modules — zero real
SDK imports, zero API calls. Lazy-import semantics (D3) are asserted by
testing the ImportError path.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from loop_kit import orchestrator


@dataclass
class FakeRunResult:
    session_id: str
    final_response: str
    finish_reason: str | None
    events: list[dict[str, Any]]
    notifications: list[Any]


class FakeHarness:
    instances: list[FakeHarness] = []  # noqa: RUF012 (test registry, reset per test)

    def __init__(self, result: FakeRunResult, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.result = result
        self.closed = False
        self.run_input: str | None = None
        self.run_session_id: str | None = None
        FakeHarness.instances.append(self)

    def run(self, input: str, *, session_id: str | None = None, on_notification: Any = None) -> FakeRunResult:
        self.run_input = input
        self.run_session_id = session_id
        return self.result

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeHarness:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class FakeHarnessError(Exception):
    pass


@pytest.fixture(autouse=True)
def _reset_fake_harness_instances() -> None:
    FakeHarness.instances = []


def _install_fake_module(monkeypatch: pytest.MonkeyPatch, result: FakeRunResult) -> None:
    module = types.ModuleType("deepseek_harness")
    module.DeepSeekHarness = lambda **kwargs: FakeHarness(result, **kwargs)  # type: ignore[attr-defined]
    errors_module = types.ModuleType("deepseek_harness.errors")
    errors_module.HarnessError = FakeHarnessError  # type: ignore[attr-defined]
    module.errors = errors_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepseek_harness", module)
    monkeypatch.setitem(sys.modules, "deepseek_harness.errors", errors_module)


def _ok_result() -> FakeRunResult:
    return FakeRunResult(
        session_id="sess-1",
        final_response="OK",
        finish_reason="completed",
        events=[
            {"type": "assistant/message", "data": {"message": {"content": [{"text": "hello world"}]}}},
            {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
        ],
        notifications=[],
    )


def test_dsh_registered_after_register_backend() -> None:
    assert "dsh" in orchestrator._available_backends()
    assert "codex" in orchestrator._available_backends()
    assert "claude" in orchestrator._available_backends()
    assert "opencode" in orchestrator._available_backends()


def test_dsh_run_fn_returns_stdout_and_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, _ok_result())
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    summaries: list[str] = []

    _stdout, _stderr, returncode, timed_out, session_id = orchestrator._run_dsh_sdk_dispatch(
        "build fib",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=summaries.append,
        actual_cwd=Path("/tmp"),
    )

    assert _stdout == "OK"
    assert _stderr == ""
    assert returncode == 0
    assert timed_out is False
    assert session_id == "sess-1"
    # Event summaries flowed through the callback.
    assert any("Message: hello" in s for s in summaries)
    assert any("Turn ended: completed" in s for s in summaries)
    # Harness closed after use.
    assert FakeHarness.instances[0].closed is True


def test_dsh_run_fn_error_finish_reason_returns_rc1(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(
        monkeypatch,
        FakeRunResult("sess-2", "", "error", [], []),
    )
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)

    _stdout, _stderr, returncode, timed_out, session_id = orchestrator._run_dsh_sdk_dispatch(
        "build fib",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
    )

    assert returncode == 1
    assert timed_out is False
    assert session_id == "sess-2"


def test_dsh_run_fn_passes_resume_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, _ok_result())
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)

    orchestrator._run_dsh_sdk_dispatch(
        "continue",
        role="worker",
        timeout_sec=30,
        resume_session_id="resume-42",
        summary_callback=None,
        actual_cwd=Path("/tmp"),
    )

    assert FakeHarness.instances[0].run_session_id == "resume-42"


def test_dsh_run_fn_import_error_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate SDK not installed even though it IS in this venv: a None entry
    # in sys.modules makes import raise ImportError (Python semantics).
    monkeypatch.setitem(sys.modules, "deepseek_harness", None)
    monkeypatch.setitem(sys.modules, "deepseek_harness.errors", None)
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)

    _stdout, _stderr, returncode, timed_out, session_id = orchestrator._run_dsh_sdk_dispatch(
        "hi",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
    )

    assert returncode == 1
    assert timed_out is False
    assert session_id is None
    assert "not installed" in _stderr


def test_dsh_run_fn_harness_error_returns_rc1(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("deepseek_harness")
    errors_module = types.ModuleType("deepseek_harness.errors")
    errors_module.HarnessError = FakeHarnessError  # type: ignore[attr-defined]
    module.errors = errors_module  # type: ignore[attr-defined]

    def _raising_harness(**kwargs: Any) -> FakeHarness:
        raise FakeHarnessError("boom")

    module.DeepSeekHarness = _raising_harness  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepseek_harness", module)
    monkeypatch.setitem(sys.modules, "deepseek_harness.errors", errors_module)
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)

    _stdout, _stderr, returncode, timed_out, _session_id = orchestrator._run_dsh_sdk_dispatch(
        "hi",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
    )

    assert returncode == 1
    assert "dsh HarnessError: FakeHarnessError: boom" in _stderr
    assert timed_out is False


def test_dsh_parse_event_cli_shape() -> None:
    summary = orchestrator._dsh_parse_event("worker", "dsh", "final answer text\n")
    assert summary is not None and "final answer text" in summary
    assert orchestrator._dsh_parse_event("worker", "dsh", "   \n") is None
