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


def test_dsh_run_fn_env_patches_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    # PM #3364: LOOP_DSH_PATCHES (colon-separated) -> patches kwarg; absent -> empty tuple.
    _install_fake_module(monkeypatch, _ok_result())
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    monkeypatch.setenv(
        "LOOP_DSH_PATCHES",
        "/tmp/a.patch.yml:/tmp/b.patch.yml",
    )

    orchestrator._run_dsh_sdk_dispatch(
        "hi",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
    )
    assert FakeHarness.instances[0].kwargs.get("patches") == ("/tmp/a.patch.yml", "/tmp/b.patch.yml")

    monkeypatch.delenv("LOOP_DSH_PATCHES")
    orchestrator._run_dsh_sdk_dispatch(
        "hi",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
    )
    assert FakeHarness.instances[1].kwargs.get("patches") == ()


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


# ── usage payload extraction (PM #3371 T1.1) ─────────────────────────────


def test_extract_dsh_usage_payload_real_shape() -> None:
    events = [
        {
            "type": "assistant/chunk",
            "data": {
                "chunk": {
                    "type": "usage",
                    "usage": {
                        "inputTokens": 189,
                        "outputTokens": 149,
                        "totalTokens": 8146,
                        "cacheReadTokens": 7808,
                        "reasoningTokens": 67,
                    },
                }
            },
        }
    ]
    payload = orchestrator._extract_dsh_usage_payload(events)
    assert payload == {"input_tokens": 189, "output_tokens": 149, "total_tokens": 8146}


def test_extract_dsh_usage_payload_empty() -> None:
    assert orchestrator._extract_dsh_usage_payload([]) == {}
    assert orchestrator._extract_dsh_usage_payload(None) == {}
    assert orchestrator._extract_dsh_usage_payload([{"type": "assistant/message"}]) == {}
    assert orchestrator._extract_dsh_usage_payload(
        [{"type": "assistant/chunk", "data": {"chunk": {"type": "text"}}}]
    ) == {}


def test_extract_dsh_usage_payload_multi_chunk_max_total() -> None:
    def chunk(total: int | None, i: int, o: int) -> dict:
        usage: dict[str, object] = {"inputTokens": i, "outputTokens": o}
        if total is not None:
            usage["totalTokens"] = total
        return {"type": "assistant/chunk", "data": {"chunk": {"type": "usage", "usage": usage}}}

    events = [chunk(100, 1, 2), chunk(500, 50, 60), chunk(None, 7, 8)]
    payload = orchestrator._extract_dsh_usage_payload(events)
    assert payload == {"input_tokens": 50, "output_tokens": 60, "total_tokens": 500}


# ── usage callback (PM #3371 T1.2) ────────────────────────────────────────


def test_dsh_run_fn_usage_callback_receives_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = _ok_result()
    ok.events.append(
        {
            "type": "assistant/chunk",
            "data": {
                "chunk": {
                    "type": "usage",
                    "usage": {
                        "inputTokens": 189,
                        "outputTokens": 149,
                        "totalTokens": 8146,
                        "cacheReadTokens": 7808,
                        "reasoningTokens": 67,
                    },
                }
            },
        }
    )
    _install_fake_module(monkeypatch, ok)
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    received: list[dict] = []

    stdout, _stderr, returncode, _timed_out, session_id = orchestrator._run_dsh_sdk_dispatch(
        "hi",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
        usage_callback=received.append,
    )
    # 5-tuple contract unchanged
    assert stdout == "OK"
    assert returncode == 0
    assert session_id == "sess-1"
    assert received == [{"input_tokens": 189, "output_tokens": 149, "total_tokens": 8146}]


def test_dsh_run_fn_usage_callback_not_called_without_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, _ok_result())
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    called: list[dict] = []

    orchestrator._run_dsh_sdk_dispatch(
        "hi",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
        usage_callback=called.append,
    )
    assert called == []


# ── loop-level cost event wiring (PM #3371 T1.3) ─────────────────────────


def _fake_inprocess_run_fn(
    stdout: str = "OK",
    returncode: int = 0,
    timed_out: bool = False,
    usage: dict[str, int] | None = None,
    session_id: str | None = "sess-cost",
) -> Any:
    def run_fn(
        prompt: str,
        *,
        role: str,
        timeout_sec: int,
        resume_session_id: str | None,
        summary_callback: Any,
        actual_cwd: Path,
        usage_callback: Any = None,
    ) -> tuple[str, str, int, bool, str | None]:
        if usage_callback is not None and usage:
            usage_callback(usage)
        return (stdout, "", returncode, timed_out, session_id)

    return run_fn


def test_run_auto_dispatch_dsh_complete_carries_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        orchestrator,
        "_require_registered_backend",
        lambda backend: (None, None, None, _fake_inprocess_run_fn(
            usage={"input_tokens": 189, "output_tokens": 149, "total_tokens": 8146}
        )),
    )
    monkeypatch.setattr(
        orchestrator,
        "_require_registered_parse_event",
        lambda backend: orchestrator._dsh_parse_event,
    )
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    monkeypatch.setattr(
        orchestrator,
        "_write_dispatch_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        orchestrator,
        "_feed_event",
        lambda event, *, level="info", data=None, paths=None: events.append((event, dict(data or {}))),
    )

    orchestrator._run_auto_dispatch(
        "worker",
        "dsh",
        "hi",
        30,
        dispatch_retries=0,
    )

    complete = [d for e, d in events if e == orchestrator.FEED_DISPATCH_COMPLETE]
    assert complete, "no dispatch_complete event"
    data = complete[0]
    assert data["backend"] == "dsh"
    assert data["input_tokens"] == 189
    assert data["total_tokens"] == 8146
    # ceil((189*43 + 149*129)/1e6) = ceil((8127 + 19221)/1e6) = ceil(0.027348) = 1
    assert data["cost_cents"] == 1


def test_run_auto_dispatch_dsh_fail_cost_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        orchestrator,
        "_require_registered_backend",
        lambda backend: (None, None, None, _fake_inprocess_run_fn(
            stdout="", returncode=1, timed_out=True, session_id=None
        )),
    )
    monkeypatch.setattr(
        orchestrator,
        "_require_registered_parse_event",
        lambda backend: orchestrator._dsh_parse_event,
    )
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    monkeypatch.setattr(
        orchestrator,
        "_write_dispatch_log",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        orchestrator,
        "_feed_event",
        lambda event, *, level="info", data=None, paths=None: events.append((event, dict(data or {}))),
    )

    with pytest.raises(RuntimeError):
        orchestrator._run_auto_dispatch(
            "worker",
            "dsh",
            "hi",
            30,
            dispatch_retries=0,
        )

    fail = [d for e, d in events if e == orchestrator.FEED_DISPATCH_FAIL]
    assert fail, "no dispatch_fail event"
    assert fail[0].get("cost_cents") == 0


# ── provider fallback chain: resolver (PM #3379 T1.1) ────────────────────


def test_resolve_dsh_channels_default_single_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOOP_DSH_PROVIDER_CHAIN", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk-123")
    channels = orchestrator._resolve_dsh_channels()
    assert channels == [("deepseek", "https://api.deepseek.com/v1", "dk-123")]


def test_resolve_dsh_channels_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_DSH_PROVIDER_CHAIN", "deepseek,360ai")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk-1")
    monkeypatch.setenv("AI360_API_KEY", "ai360-1")
    channels = orchestrator._resolve_dsh_channels()
    assert channels == [
        ("deepseek", "https://api.deepseek.com/v1", "dk-1"),
        ("360ai", "https://api.360.cn/v1", "ai360-1"),
    ]


def test_resolve_dsh_channels_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_DSH_PROVIDER_CHAIN", "deepseek")
    monkeypatch.setenv("LOOP_DSH_BASE_URL_DEEPSEEK", "https://custom.deepseek/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk-2")
    channels = orchestrator._resolve_dsh_channels()
    assert channels[0][1] == "https://custom.deepseek/v1"


def test_resolve_dsh_channels_unknown_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_DSH_PROVIDER_CHAIN", "mystery")
    with pytest.raises(ValueError, match="unknown dsh channel"):
        orchestrator._resolve_dsh_channels()


def test_resolve_dsh_channels_empty_string_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOP_DSH_PROVIDER_CHAIN", "  ")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk-3")
    channels = orchestrator._resolve_dsh_channels()
    assert len(channels) == 1
    assert channels[0][0] == "deepseek"


def test_dsh_run_fn_passes_base_url_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, _ok_result())
    monkeypatch.setattr(orchestrator, "_log", lambda msg: None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk-wired")
    monkeypatch.delenv("LOOP_DSH_PROVIDER_CHAIN", raising=False)

    orchestrator._run_dsh_sdk_dispatch(
        "hi",
        role="worker",
        timeout_sec=30,
        resume_session_id=None,
        summary_callback=None,
        actual_cwd=Path("/tmp"),
    )
    kw = FakeHarness.instances[0].kwargs
    assert kw.get("base_url") == "https://api.deepseek.com/v1"
    assert kw.get("api_key") == "dk-wired"
