"""E2E smoke test suite for the loop-kit PM → Worker → Reviewer lifecycle.

Run with: uv run --group dev pytest tests/test_e2e_smoke.py -v -s

These tests require the opencode backend available on PATH. Tests are
marked with pytest.mark.e2e and can be skipped with --deselect.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

LOOP_KIT_ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = LOOP_KIT_ROOT / ".loop" / "tests" / "e2e"
E2E_TASKS_DIR = LOOP_KIT_ROOT / ".loop" / "tasks"

pytestmark = pytest.mark.e2e


def _has_backend(backend: str) -> bool:
    """Check if a backend executable is available."""
    import shutil
    return shutil.which(backend) is not None


def _clean_loop_state() -> None:
    """Remove stale bus files, lock, archives, and worktrees."""
    import shutil
    loop_dir = LOOP_KIT_ROOT / ".loop"
    for name in [
        "work_report.json", "review_report.json", "review_request.json",
        "fix_list.json", "state.json", "summary.json", "task_packet.json",
        "lock",
    ]:
        p = loop_dir / name
        if p.exists():
            p.unlink(missing_ok=True)
    archive_dir = loop_dir / "archive"
    if archive_dir.exists():
        shutil.rmtree(archive_dir, ignore_errors=True)
    # Remove any lingering worktrees from previous runs
    for e2e_id in ["E2E-1PLUS1", "E2E-CHANGES-REQUIRED", "E2E-MULTI-LANE", "E2E-NOOP-SUCCESS"]:
        wt_dir = loop_dir / "worktrees" / e2e_id
        if wt_dir.exists():
            shutil.rmtree(wt_dir, ignore_errors=True)
        branch = f"refs/heads/loop/{e2e_id}"
        subprocess.run(["git", "update-ref", "-d", branch], capture_output=True, cwd=str(LOOP_KIT_ROOT))
    subprocess.run(["git", "worktree", "prune"], capture_output=True, cwd=str(LOOP_KIT_ROOT))


def _run_loop(
    task_path: str,
    *,
    max_rounds: int = 3,
    timeout: int = 300,
    dispatch_timeout: int = 900,
    artifact_timeout: int = 600,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run the loop with the given task card."""
    cmd = [
        sys.executable, "-m", "loop_kit", "run",
        "--task", task_path,
        "--auto-dispatch",
        "--max-rounds", str(max_rounds),
        "--timeout", str(timeout),
        "--dispatch-timeout", str(dispatch_timeout),
        "--artifact-timeout", str(artifact_timeout),
        "--allow-dirty",
        "--worker-noop-as-success",
        "--max-parallel-workers", "1",
        "--worker-backend", "opencode",
        "--reviewer-backend", "opencode",
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + dispatch_timeout * 2 + 120,
        cwd=str(LOOP_KIT_ROOT),
        env=env,
    )


def _read_loop_state() -> dict | None:
    """Read the current loop state."""
    state_file = LOOP_KIT_ROOT / ".loop" / "state.json"
    if not state_file.exists():
        return None
    return json.loads(state_file.read_text(encoding="utf-8"))


def _read_summary() -> dict | None:
    """Read the current loop summary."""
    summary_file = LOOP_KIT_ROOT / ".loop" / "summary.json"
    if not summary_file.exists():
        return None
    return json.loads(summary_file.read_text(encoding="utf-8"))


def _task_path(task_id: str) -> str:
    return str(E2E_DIR / f"{task_id}_task_card.json")


class TestE2EApproved:
    """Happy path: Worker creates file, Reviewer approves."""

    def test_approved_single_round(self):
        """E2E-APPROVED: 1+1=2 task passes worker → reviewer → approved."""
        if not _has_backend("opencode"):
            pytest.skip("opencode backend not available")

        _clean_loop_state()
        # Ensure answer.py doesn't already exist (clean from prior runs)
        answer = LOOP_KIT_ROOT / "answer.py"
        if answer.exists():
            answer.unlink()

        task_path = _task_path("E2E-1PLUS1")
        # Try both locations
        if not Path(task_path).exists():
            task_path = str(LOOP_KIT_ROOT / ".loop" / "tasks" / "E2E-1PLUS1_task_card.json")
        if not Path(task_path).exists():
            pytest.skip(f"Task card not found: {task_path}")

        # Create a fresh task card since git tracks it
        task_data = json.loads(Path(task_path).read_text(encoding="utf-8"))
        bus_card = LOOP_KIT_ROOT / ".loop" / "task_card.json"
        bus_card.parent.mkdir(parents=True, exist_ok=True)
        bus_card.write_text(json.dumps(task_data, indent=2), encoding="utf-8")

        result = _run_loop(task_path)

        state = _read_loop_state()
        summary = _read_summary()

        assert result.returncode == 0, f"Loop failed:\nSTDOUT: {result.stdout[-500:]}\nSTDERR: {result.stderr[-500:]}"
        assert state is not None, "No state.json produced"
        assert state["state"] == "done", f"Expected done, got {state.get('state')}"
        assert state.get("outcome") == "approved", f"Expected approved, got {state.get('outcome')}"

        # Verify the artifact was created
        answer = LOOP_KIT_ROOT / "answer.py"
        assert answer.exists(), "answer.py was not created"


class TestE2EChangesRequired:
    """Multi-round retry: Worker gets rejected, fixes, re-submits."""

    def test_changes_required_multi_round(self):
        """E2E-CHANGES-REQUIRED: reviewer rejects, worker fixes, approved."""
        if not _has_backend("opencode"):
            pytest.skip("opencode backend not available")

        _clean_loop_state()
        greet = LOOP_KIT_ROOT / "greet.py"
        if greet.exists():
            greet.unlink()

        task_path = _task_path("E2E-CHANGES-REQUIRED")
        if not Path(task_path).exists():
            pytest.skip(f"Task card not found: {task_path}")

        task_data = json.loads(Path(task_path).read_text(encoding="utf-8"))
        bus_card = LOOP_KIT_ROOT / ".loop" / "task_card.json"
        bus_card.write_text(json.dumps(task_data, indent=2), encoding="utf-8")

        result = _run_loop(task_path, max_rounds=5)

        state = _read_loop_state()
        summary = _read_summary()

        assert result.returncode == 0, f"Loop failed:\nSTDOUT: {result.stdout[-500:]}\nSTDERR: {result.stderr[-500:]}"
        assert state is not None
        assert state["state"] == "done"
        assert state.get("outcome") == "approved"

        # Verify greet.py was created
        greet = LOOP_KIT_ROOT / "greet.py"
        assert greet.exists(), "greet.py was not created"


class TestE2ENoopSuccess:
    """No-op worker: task already satisfied, succeeds without changes."""

    def test_noop_success_when_file_already_correct(self):
        """E2E-NOOP-SUCCESS: worker finds greet.py correct, succeeds."""
        if not _has_backend("opencode"):
            pytest.skip("opencode backend not available")

        _clean_loop_state()
        greet = LOOP_KIT_ROOT / "greet.py"
        if not greet.exists():
            pytest.skip("greet.py not available (run E2E-CHANGES-REQUIRED first)")

        task_path = _task_path("E2E-NOOP-SUCCESS")
        if not Path(task_path).exists():
            pytest.skip(f"Task card not found: {task_path}")

        task_data = json.loads(Path(task_path).read_text(encoding="utf-8"))
        bus_card = LOOP_KIT_ROOT / ".loop" / "task_card.json"
        bus_card.write_text(json.dumps(task_data, indent=2), encoding="utf-8")

        result = _run_loop(task_path)

        state = _read_loop_state()

        assert result.returncode == 0
        assert state is not None
        assert state["state"] == "done"
        assert state.get("outcome") == "no_change_success"
