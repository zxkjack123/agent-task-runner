"""E2E smoke test suite for the loop-kit PM → Worker → Reviewer lifecycle.

Run with: uv run --group dev pytest tests/test_e2e_smoke.py -v -s
    or:   uv run --group dev pytest -m e2e -v

These tests require the opencode backend available on PATH. Each test builds a
function-scoped temporary git repository (tmp_path) and runs the loop inside it,
so the real repository's history and working tree are never touched.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_SRC = PACKAGE_ROOT / ".loop" / "templates"
E2E_TASK_CARDS_SRC = PACKAGE_ROOT / ".loop" / "tests" / "e2e"

_E2E_TASK_IDS = [
    "E2E-1PLUS1",
    "E2E-CHANGES-REQUIRED",
    "E2E-MULTI-LANE",
    "E2E-NOOP-SUCCESS",
]

GREET_PY_CORRECT = """#!/usr/bin/env python3
import sys

def main():
    if len(sys.argv) > 1:
        print(f"Hello, {sys.argv[1]}!")
    else:
        print("Hello, World!")

if __name__ == "__main__":
    main()
"""

pytestmark = pytest.mark.e2e


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command inside the temporary repository."""
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(repo))


def _has_backend(backend: str) -> bool:
    """Check if a backend executable is available."""
    return shutil.which(backend) is not None


@pytest.fixture
def e2e_repo(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """Build a minimal temporary git repository with loop templates and e2e task cards.

    Steps: git init -b master (fallback for older git), local user config, an
    empty base commit (loop requires a non-unborn HEAD), .loop directory
    skeleton, then a copy of the worker/reviewer prompt templates and the 4 e2e
    task cards from the real repository.

    Optional parametrization: ``@pytest.mark.parametrize("e2e_repo", [{"file": "content"}], indirect=True)``
    pre-seeds files into the repository root via an "e2e seed" commit.
    """
    repo = tmp_path / "e2e_repo"
    repo.mkdir(parents=True, exist_ok=True)

    init = _git(repo, "init", "-b", "master")
    if init.returncode != 0:
        _git(repo, "init")
        _git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
    _git(repo, "config", "user.email", "e2e@test.local")
    _git(repo, "config", "user.name", "e2e-runner")
    base = _git(repo, "commit", "--allow-empty", "-m", "e2e base")
    assert base.returncode == 0, f"failed to create base commit: {base.stderr}"

    templates_dir = repo / ".loop" / "templates"
    cards_dir = repo / ".loop" / "tests" / "e2e"
    tasks_dir = repo / ".loop" / "tasks"
    for directory in (templates_dir, cards_dir, tasks_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for name in ("worker_prompt.txt", "reviewer_prompt.txt"):
        shutil.copy2(TEMPLATES_SRC / name, templates_dir / name)
    for task_id in _E2E_TASK_IDS:
        card_name = f"{task_id}_task_card.json"
        shutil.copy2(E2E_TASK_CARDS_SRC / card_name, cards_dir / card_name)

    seed_files = getattr(request, "param", None)
    if seed_files:
        for rel_path, content in seed_files.items():
            target = repo / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        add = _git(repo, "add", "--", *seed_files.keys())
        assert add.returncode == 0, f"git add failed: {add.stderr}"
        seed = _git(repo, "commit", "-m", "e2e seed")
        assert seed.returncode == 0, f"seed commit failed: {seed.stderr}"

    return repo


def _clean_loop_state(repo: Path) -> None:
    """Remove stale bus files, archives, loop branches, and worktrees in repo."""
    loop_dir = repo / ".loop"
    for name in [
        "work_report.json",
        "review_report.json",
        "review_request.json",
        "fix_list.json",
        "state.json",
        "summary.json",
        "task_packet.json",
        "lock",
    ]:
        p = loop_dir / name
        if p.exists():
            p.unlink(missing_ok=True)
    archive_dir = loop_dir / "archive"
    if archive_dir.exists():
        shutil.rmtree(archive_dir, ignore_errors=True)
    # Remove any lingering worktrees from previous runs
    worktrees_root = loop_dir / "worktrees"
    if worktrees_root.exists():
        shutil.rmtree(worktrees_root, ignore_errors=True)
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/loop/")
    for ref in refs.stdout.splitlines():
        ref_name = ref.strip()
        if ref_name:
            _git(repo, "update-ref", "-d", ref_name)
    _git(repo, "worktree", "prune")


def _install_opencode_dir_wrapper(repo: Path, env: dict[str, str]) -> None:
    """Pin dispatched opencode sessions to their subprocess cwd via PATH wrapper.

    The opencode CLI ignores the subprocess cwd unless invoked with ``--dir``;
    without it, ``opencode run`` may anchor the worker/reviewer session to the
    real repository (e.g. by attaching to an already-running server). The loop's
    dispatch command has no ``--dir`` flag, so we prepend a wrapper named
    ``opencode`` to PATH that injects ``--dir "$PWD"`` right after ``run`` and
    execs the real binary. The wrapper lives outside the repository (next to it
    under tmp_path), so the repository's git state is unaffected.
    """
    real_opencode = shutil.which("opencode")
    if real_opencode is None:
        return
    wrapper_dir = repo.parent / "opencode_wrapper_bin"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper = wrapper_dir / "opencode"
    if not wrapper.exists():
        wrapper.write_text(
            "#!/bin/bash\n"
            f'REAL="{real_opencode}"\n'
            'if [ "${1:-}" = "run" ]; then\n'
            '    exec "$REAL" run --dir "$PWD" "${@:2}"\n'
            "fi\n"
            'exec "$REAL" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    env["PATH"] = f"{wrapper_dir}{os.pathsep}{env['PATH']}"


def _run_loop(
    repo: Path,
    task_path: str,
    *,
    max_rounds: int = 3,
    timeout: int = 300,
    dispatch_timeout: int = 900,
    artifact_timeout: int = 600,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run the loop with the given task card inside the temporary repository."""
    cmd = [
        sys.executable,
        "-m",
        "loop_kit",
        "run",
        "--loop-dir",
        str(repo / ".loop"),
        "--task",
        task_path,
        "--auto-dispatch",
        "--max-rounds",
        str(max_rounds),
        "--timeout",
        str(timeout),
        "--dispatch-timeout",
        str(dispatch_timeout),
        "--artifact-timeout",
        str(artifact_timeout),
        "--allow-dirty",
        "--worker-noop-as-success",
        "--max-parallel-workers",
        "1",
        "--worker-backend",
        "opencode",
        "--reviewer-backend",
        "opencode",
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    # If the tests run inside an opencode session (OPENCODE=1 + OPENCODE_PID),
    # a nested `opencode run` would attach to the already-running server that is
    # bound to the real repository root, ignoring the subprocess cwd. Strip these
    # so the worker/reviewer dispatch starts a fresh server anchored at the
    # temporary repository.
    env.pop("OPENCODE", None)
    env.pop("OPENCODE_PID", None)
    _install_opencode_dir_wrapper(repo, env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + dispatch_timeout * 2 + 120,
        cwd=str(repo),
        env=env,
    )


def _read_loop_state(repo: Path) -> dict | None:
    """Read the current loop state from the temporary repository."""
    state_file = repo / ".loop" / "state.json"
    if not state_file.exists():
        return None
    return json.loads(state_file.read_text(encoding="utf-8"))


def _read_summary(repo: Path) -> dict | None:
    """Read the current loop summary from the temporary repository."""
    summary_file = repo / ".loop" / "summary.json"
    if not summary_file.exists():
        return None
    return json.loads(summary_file.read_text(encoding="utf-8"))


def _task_path(repo: Path, task_id: str) -> str:
    return str(repo / ".loop" / "tests" / "e2e" / f"{task_id}_task_card.json")


def _write_bus_card(repo: Path, task_path: str) -> None:
    """Copy the task card content onto the loop bus (task_card.json)."""
    task_data = json.loads(Path(task_path).read_text(encoding="utf-8"))
    bus_card = repo / ".loop" / "task_card.json"
    bus_card.write_text(json.dumps(task_data, indent=2), encoding="utf-8")


class TestE2EApproved:
    """Happy path: Worker creates file, Reviewer approves."""

    def test_approved_single_round(self, e2e_repo: Path):
        """E2E-APPROVED: 1+1=2 task passes worker → reviewer → approved."""
        if not _has_backend("opencode"):
            pytest.skip("opencode backend not available")

        _clean_loop_state(e2e_repo)

        task_path = _task_path(e2e_repo, "E2E-1PLUS1")
        _write_bus_card(e2e_repo, task_path)

        result = _run_loop(e2e_repo, task_path)

        state = _read_loop_state(e2e_repo)

        assert result.returncode == 0, f"Loop failed:\nSTDOUT: {result.stdout[-500:]}\nSTDERR: {result.stderr[-500:]}"
        assert state is not None, "No state.json produced"
        assert state["state"] == "done", f"Expected done, got {state.get('state')}"
        assert state.get("outcome") == "approved", f"Expected approved, got {state.get('outcome')}"

        # Verify the artifact was created inside the temporary repository
        answer = e2e_repo / "answer.py"
        assert answer.exists(), "answer.py was not created"


class TestE2EChangesRequired:
    """Multi-round retry: Worker gets rejected, fixes, re-submits."""

    def test_changes_required_multi_round(self, e2e_repo: Path):
        """E2E-CHANGES-REQUIRED: reviewer rejects, worker fixes, approved."""
        if not _has_backend("opencode"):
            pytest.skip("opencode backend not available")

        _clean_loop_state(e2e_repo)

        task_path = _task_path(e2e_repo, "E2E-CHANGES-REQUIRED")
        _write_bus_card(e2e_repo, task_path)

        result = _run_loop(e2e_repo, task_path, max_rounds=5)

        state = _read_loop_state(e2e_repo)

        assert result.returncode == 0, f"Loop failed:\nSTDOUT: {result.stdout[-500:]}\nSTDERR: {result.stderr[-500:]}"
        assert state is not None
        assert state["state"] == "done"
        assert state.get("outcome") == "approved"

        # Verify greet.py was created inside the temporary repository
        greet = e2e_repo / "greet.py"
        assert greet.exists(), "greet.py was not created"


class TestE2ENoopSuccess:
    """No-op worker: task already satisfied, succeeds without changes."""

    @pytest.mark.parametrize("e2e_repo", [{"greet.py": GREET_PY_CORRECT}], indirect=True)
    def test_noop_success_when_file_already_correct(self, e2e_repo: Path):
        """E2E-NOOP-SUCCESS: worker finds greet.py correct, succeeds."""
        if not _has_backend("opencode"):
            pytest.skip("opencode backend not available")

        _clean_loop_state(e2e_repo)

        task_path = _task_path(e2e_repo, "E2E-NOOP-SUCCESS")
        _write_bus_card(e2e_repo, task_path)

        result = _run_loop(e2e_repo, task_path)

        state = _read_loop_state(e2e_repo)

        assert result.returncode == 0
        assert state is not None
        assert state["state"] == "done"
        assert state.get("outcome") == "no_change_success"
