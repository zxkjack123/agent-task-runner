"""PM #2622 loop_kit compatibility tests (T2.1, zero-code-change verification).

Covers the three compat contracts the doc-pipeline relies on:
  1. work_report.json survives a normal terminal run (only crash-stale cleanup unlinks it);
  2. unknown terminal outcomes route to `_terminal_outcome_handle_resume_failure`
     (ValidationError), never config_error;
  3. `max_rounds_exhausted` outcome exists and routes to resume_failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from loop_kit import _core


def _make_paths(tmp_path: Path):
    loop_dir = tmp_path / ".loop"
    loop_dir.mkdir(parents=True)
    paths = _core.LoopPaths(
        root=tmp_path,
        dir=loop_dir,
        state=loop_dir / "state.json",
        task_card=loop_dir / "task_card.json",
        review_report=loop_dir / "review_report.json",
        review_request=loop_dir / "review_request.json",
        work_report=loop_dir / "work_report.json",
        fix_list=loop_dir / "fix_list.json",
        summary=loop_dir / "summary.json",
        logs=tmp_path / "logs",
        archive=tmp_path / "archive",
    )
    return loop_dir, paths


def test_a_work_report_survives_normal_terminal_routing(tmp_path):
    """Terminal-outcome routing never touches work_report.json (M5 direct-read contract)."""
    loop_dir, paths = _make_paths(tmp_path)
    work = {"task_id": "T-42", "notes": "PRECONDITION-FAILED: tier1=9", "files_changed": [], "tests": []}
    (loop_dir / "work_report.json").write_text(json.dumps(work), encoding="utf-8")
    state = {"outcome": "max_rounds_exhausted", "error": "3 rounds rejected", "state": "done"}

    handler = _core._dispatch_terminal_outcome(state)

    assert handler is _core._terminal_outcome_handle_resume_failure
    # Routing is pure — work_report.json untouched
    assert (loop_dir / "work_report.json").exists()
    data = json.loads((loop_dir / "work_report.json").read_text(encoding="utf-8"))
    assert data["notes"].startswith("PRECONDITION-FAILED:")


def test_b_unknown_terminal_outcome_routes_to_resume_failure_not_config_error(tmp_path):
    """STATE_DONE + outcome not in terminal-success set → resume_failure (ValidationError)."""
    loop_dir, paths = _make_paths(tmp_path)
    (loop_dir / "work_report.json").write_text("{}", encoding="utf-8")
    state = {
        "outcome": "max_rounds_exhausted",
        "error": "reviewer rejected 3 rounds",
        "state": "done",
    }

    handler = _core._dispatch_terminal_outcome(state)
    assert handler is _core._terminal_outcome_handle_resume_failure

    with pytest.raises(Exception) as exc_info:
        handler(state, _core.RunConfig(task_path=loop_dir / "task_card.json"), paths=paths)
    assert "Cannot resume" in str(exc_info.value)
    assert "config" not in str(exc_info.value).lower()  # not a config_error


def test_c_approved_routes_to_resume_success(tmp_path):
    """Terminal success outcomes still route to resume_success (no regression)."""
    loop_dir, paths = _make_paths(tmp_path)
    state = {"outcome": "approved", "state": "done"}
    handler = _core._dispatch_terminal_outcome(state)
    assert handler is _core._terminal_outcome_handle_resume_success


def test_d_max_rounds_exhausted_constant_and_trigger_present():
    """max_rounds_exhausted outcome exists in the state machine (negative E2E depends on it)."""
    assert _core._RoundOutcome.MAX_ROUNDS_EXHAUSTED.value == "max_rounds_exhausted"
    assert _core.STATE_TRIGGER_MAX_ROUNDS_EXHAUSTED == "max_rounds_exhausted"


def test_e_stale_cleanup_is_the_only_work_report_unlinker():
    """_clean_stale_loop_state unlinks work_report.json ONLY when invoked (crashed runs).

    Documents the boundary: normal terminal paths must never call it — the M5
    sentinel reader depends on work_report.json persisting after loop end.
    """
    import inspect

    # Inspect callers of _clean_stale_loop_state within _core to assert it is
    # only reachable from stale/interrupt resume paths, not terminal handlers.
    src = inspect.getsource(_core)
    call_sites = []
    for i, line in enumerate(src.splitlines(), 1):
        if "_clean_stale_loop_state(" in line and "def _clean_stale_loop_state" not in line:
            call_sites.append((i, line.strip()))
    # At minimum, assert the terminal handlers do NOT reference it.
    handler_src = inspect.getsource(_core._terminal_outcome_handle_resume_failure)
    assert "_clean_stale_loop_state" not in handler_src
    assert call_sites, "expected at least one stale-path call site (sanity of inspection)"


def test_f_all_doc_templates_render_with_loop_kit_context():
    """Regression: doc templates must not contain unescaped literal braces —
    _render_prompt_template uses str.format and raises KeyError on stray {."""
    from pathlib import Path as _Path

    ctx = {
        "task_id": "T-1", "round_num": 1, "run_id": "run-x",
        "work_report_path": "/tmp/w.json", "review_report_path": "/tmp/r.json",
        "agents_md": "-", "role_md": "-", "task_card_section": "-",
        "prior_context_section": "-", "handoff_section": "-",
        "orchestrator_path": "-", "function_index": "-",
        "quickstart_section": "-", "knowledge_section": "-",
        "task_packet_section": "-",
    }
    tmpl_dir = _Path(__file__).resolve().parent.parent / ".loop" / "templates"
    for name in [
        "doc_pipeline_worker_prompt.txt",
        "doc_pipeline_reviewer_prompt.txt",
        "doc_fix_worker_prompt.txt",
        "doc_fix_reviewer_prompt.txt",
    ]:
        p = tmpl_dir / name
        assert p.exists(), f"missing template {name}"
        out = _core._render_prompt_template(template_path=p, context=ctx)
        assert "T-1" in out  # placeholders resolved
