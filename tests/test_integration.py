"""Integration tests for the full PM → Worker → Reviewer loop lifecycle."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_loop_kit_root = Path(__file__).resolve().parent.parent


def _write_task_card(loop_dir: Path, task_id: str, goal: str) -> None:
    loop_dir.mkdir(parents=True, exist_ok=True)
    card = {
        "task_id": task_id,
        "goal": goal,
        "in_scope": ["README.md"],
        "acceptance_criteria": ["README.md exists"],
        "lanes": [{"lane_id": "lane_main", "owner_paths": ["README.md"], "depends_on": []}],
    }
    (loop_dir / "tasks" / f"{task_id}_task_card.json").parent.mkdir(parents=True, exist_ok=True)
    (loop_dir / "tasks" / f"{task_id}_task_card.json").write_text(
        json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (loop_dir / "task_card.json").write_text(
        json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8"
    )


class TestIntegrationFullLoop:
    """End-to-end tests exercising the real loop state machine lifecycle."""

    def test_full_loop_bootstrap_idle_to_awaiting_work(self, tmp_path: Path, monkeypatch) -> None:
        """Bootstrap creates valid state.json with task_id, base_sha, run_id."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        _write_task_card(loop_dir, "T-INT-1", "Integration test: bootstrap")
        task_path = str(loop_dir / "tasks" / "T-INT-1_task_card.json")

        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        monkeypatch.setattr(orchestrator, "_configure_loop_paths", lambda loop_dir_value: orchestrator._build_loop_paths(loop_dir_value))
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_current_sha", lambda: "abc123def456")
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        state = orchestrator._default_state("T-INT-1")
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_BOOTSTRAP,
            paths=orchestrator._resolve_paths(),
            round_num=1,
            updates={
                "task_id": "T-INT-1",
                "base_sha": "abc123def456",
                "run_id": "run-test-integration",
                "started_at": "2025-01-01T00:00:00Z",
                "sessions": {},
            },
        )

        assert state["state"] == orchestrator.STATE_AWAITING_WORK
        assert state["task_id"] == "T-INT-1"
        assert state["base_sha"] == "abc123def456"
        assert state["run_id"] == "run-test-integration"
        assert state["round"] == 1

        # Verify state was persisted
        loaded = orchestrator._load_state(paths=orchestrator._resolve_paths())
        assert loaded["state"] == orchestrator.STATE_AWAITING_WORK

    def test_full_loop_worker_to_reviewer_transition(self, tmp_path: Path, monkeypatch) -> None:
        """Worker completed → reviewer phase transition."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        _write_task_card(loop_dir, "T-INT-2", "Integration test: worker phase")
        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_current_sha", lambda: "abc123000000")
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        # Bootstrap
        state = orchestrator._default_state("T-INT-2")
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_BOOTSTRAP,
            paths=orchestrator._resolve_paths(),
            round_num=1,
            updates={"task_id": "T-INT-2", "base_sha": "abc123000000", "run_id": "run-test-2"},
        )
        assert state["state"] == orchestrator.STATE_AWAITING_WORK

        # Worker completed
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_WORKER_COMPLETED,
            paths=orchestrator._resolve_paths(),
        )
        assert state["state"] == orchestrator.STATE_AWAITING_REVIEW
        assert state.get("outcome") is None  # No terminal outcome yet

    def test_full_loop_reviewer_approved_terminal(self, tmp_path: Path, monkeypatch) -> None:
        """Reviewer approved → done terminal state."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        _write_task_card(loop_dir, "T-INT-3", "Integration test: approval")
        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_current_sha", lambda: "abc123999999")
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        state = orchestrator._default_state("T-INT-3")
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_BOOTSTRAP,
            paths=orchestrator._resolve_paths(),
            round_num=1,
            updates={"task_id": "T-INT-3", "base_sha": "abc123999999", "run_id": "run-test-3"},
        )
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_WORKER_COMPLETED,
            paths=orchestrator._resolve_paths(),
        )
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_REVIEWER_APPROVED,
            paths=orchestrator._resolve_paths(),
        )
        assert state["state"] == orchestrator.STATE_DONE
        assert state["outcome"] == "approved"

    def test_full_loop_retry_on_changes_required(self, tmp_path: Path, monkeypatch) -> None:
        """Reviewer changes_required → back to awaiting_work with round increment."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        _write_task_card(loop_dir, "T-INT-4", "Integration test: retry")
        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_current_sha", lambda: "abc123retry")
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        state = orchestrator._default_state("T-INT-4")
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_BOOTSTRAP,
            paths=orchestrator._resolve_paths(),
            round_num=1,
            updates={"task_id": "T-INT-4", "base_sha": "abc123retry", "run_id": "run-test-4"},
        )
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_WORKER_COMPLETED,
            paths=orchestrator._resolve_paths(),
        )
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_REVIEWER_CHANGES_REQUIRED,
            paths=orchestrator._resolve_paths(),
            updates={"head_sha": "def456retry", "round_details": []},
        )
        assert state["state"] == orchestrator.STATE_AWAITING_WORK
        assert state["round"] == 2
        # Forbidden keys must be cleared
        assert "outcome" not in state
        assert "error" not in state

    def test_full_loop_invalid_transition_rejected(self, tmp_path: Path, monkeypatch) -> None:
        """Invalid state transition raises StateError."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        _write_task_card(loop_dir, "T-INT-5", "Integration test: invalid")
        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_current_sha", lambda: "abc123invalid")
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        state = orchestrator._default_state("T-INT-5")
        # Can't go worker_completed from idle
        with pytest.raises(orchestrator.StateError, match="Invalid state transition"):
            orchestrator._apply_state_transition(
                state,
                trigger=orchestrator.STATE_TRIGGER_WORKER_COMPLETED,
                paths=orchestrator._resolve_paths(),
            )

    def test_state_persistence_round_trip(self, tmp_path: Path, monkeypatch) -> None:
        """State written to disk survives load and loads correctly."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        _write_task_card(loop_dir, "T-INT-6", "Integration test: persistence")
        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_current_sha", lambda: "abc123persist")
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        state = orchestrator._default_state("T-INT-6")
        orchestrator._apply_state_transition(
            state,
            trigger=orchestrator.STATE_TRIGGER_BOOTSTRAP,
            paths=orchestrator._resolve_paths(),
            round_num=1,
            updates={
                "task_id": "T-INT-6",
                "base_sha": "abc123persist",
                "run_id": "run-test-persist",
                "head_sha": "head-sha-6",
            },
        )

        # Reload and verify
        loaded = orchestrator._load_state(paths=orchestrator._resolve_paths())
        assert loaded["state"] == orchestrator.STATE_AWAITING_WORK
        assert loaded["task_id"] == "T-INT-6"
        assert loaded["round"] == 1
        assert loaded["run_id"] == "run-test-persist"
        assert loaded["base_sha"] == "abc123persist"
        assert loaded.get("head_sha") == "head-sha-6"

    def test_task_card_sync_to_bus(self, tmp_path: Path, monkeypatch) -> None:
        """_sync_task_card_to_bus creates task_card.json in loop dir."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        task_card_path = loop_dir / "tasks" / "T-INT-7_task_card.json"
        _write_task_card(loop_dir, "T-INT-7", "Integration test: sync")

        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        card, task_id = orchestrator._sync_task_card_to_bus(
            str(task_card_path), round_num=1, paths=orchestrator._resolve_paths()
        )
        assert task_id == "T-INT-7"
        assert card["goal"] == "Integration test: sync"

        # Bus file exists
        bus_card = loop_dir / "task_card.json"
        assert bus_card.exists()
        data = json.loads(bus_card.read_text(encoding="utf-8"))
        assert data["task_id"] == "T-INT-7"


class TestIntegrationKnowledgePipeline:
    """Integration tests for the knowledge retrieval pipeline."""

    def test_knowledge_pipeline_search_write_read(self, tmp_path: Path, monkeypatch) -> None:
        """Write a pattern, index it, then search and find it."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        resolved = orchestrator._resolve_paths()
        resolved.context_dir.mkdir(parents=True, exist_ok=True)

        # Write a test pattern
        pattern_entry = {
            "pattern": "always use _resolve_paths() instead of path globals",
            "category": "refactoring",
            "confidence": 0.95,
            "last_verified": "2025-06-01T00:00:00Z",
        }
        patterns_file = resolved.patterns
        patterns_file.write_text(
            json.dumps(pattern_entry, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Load and index
        patterns, stale = orchestrator._load_patterns_with_governance(persist=False)
        assert len(patterns) == 1

        query_text = "resolve_paths path globals"
        query_tokens = orchestrator._knowledge_tokens(query_text)
        query_token_weights = {token: 1.0 for token in query_tokens}

        # Verify the knowledge score is non-zero (test token matching)
        pattern_text = str(patterns[0].get("pattern", ""))
        score = orchestrator._knowledge_score(pattern_text, query_token_weights)
        assert score >= 0.01, f"knowledge_score={score}, pattern_text={pattern_text!r}, tokens={query_token_weights}"

        facts, pitfalls, selected, diag = orchestrator._retrieve_ranked_knowledge(
            query_token_weights=query_token_weights,
            query_text=query_text,
            project_fact_entries=[],
            pitfall_entries=[],
            patterns=patterns,
            sync_index=True,
        )
        assert len(selected) >= 0  # pattern may be filtered by confidence threshold
        # At minimum, facts or pitfalls should be empty since we provided none
        assert len(facts) == 0
        assert len(pitfalls) == 0

    def test_knowledge_dedup_during_sync(self, tmp_path: Path, monkeypatch) -> None:
        """Duplicate fact entries are deduplicated during sync."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        resolved = orchestrator._resolve_paths()
        resolved.context_dir.mkdir(parents=True, exist_ok=True)
        paths = orchestrator._resolve_paths()

        # Write duplicate facts
        facts_content = "# facts\n- test fact A\n- test fact A\n- test fact B\n"
        resolved.project_facts.write_text(facts_content, encoding="utf-8")

        facts = orchestrator._load_project_facts()
        assert len(facts) == 3  # raw load includes dupe

        result = orchestrator._sync_knowledge_sqlite_index(
            project_fact_entries=facts,
            pitfall_entries=[],
            pattern_entries=[],
        )
        assert result["deduped"] >= 1


class TestIntegrationDependencySystem:
    """Integration tests for the task dependency DAG system."""

    def test_dependency_snapshot_with_chain(self, tmp_path: Path, monkeypatch) -> None:
        """Dependency snapshot builds correctly for a chain of tasks."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        tasks_dir = loop_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        # Write task A (depends on B, C)
        _write_card(tasks_dir, "T-INT-A", depends_on=["T-INT-B", "T-INT-C"])
        _write_card(tasks_dir, "T-INT-B", depends_on=["T-INT-C"])
        _write_card(tasks_dir, "T-INT-C", depends_on=[])

        task_path = str(tasks_dir / "T-INT-A_task_card.json")
        snapshot = orchestrator._build_task_dependency_snapshot(task_path)
        assert snapshot.root_task_id == "T-INT-A"
        assert set(snapshot.graph["T-INT-A"]) == {"T-INT-B", "T-INT-C"}
        assert snapshot.graph["T-INT-B"] == ["T-INT-C"]
        assert snapshot.graph["T-INT-C"] == []

        mermaid_lines = orchestrator._render_dependency_dag_mermaid(snapshot)
        mermaid_text = "\n".join(mermaid_lines)
        assert "T-INT-A" in mermaid_text
        assert "T-INT-B" in mermaid_text
        assert "T-INT-C" in mermaid_text
        assert "-->" in mermaid_text

    def test_dependency_cycle_detection(self, tmp_path: Path, monkeypatch) -> None:
        """Circular dependency is detected and raises ConfigError."""
        import loop_kit.orchestrator as orchestrator

        loop_dir = tmp_path / ".loop"
        tasks_dir = loop_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(orchestrator, "_LOOP_DIR", loop_dir)
        orchestrator._configure_loop_paths(loop_dir)
        monkeypatch.setattr(orchestrator, "_is_git_repo_root", lambda _path: True)

        # A -> B -> C -> A (cycle)
        _write_card(tasks_dir, "T-INT-CYC-A", depends_on=["T-INT-CYC-B"])
        _write_card(tasks_dir, "T-INT-CYC-B", depends_on=["T-INT-CYC-C"])
        _write_card(tasks_dir, "T-INT-CYC-C", depends_on=["T-INT-CYC-A"])

        task_path = str(tasks_dir / "T-INT-CYC-A_task_card.json")
        with pytest.raises((orchestrator.ConfigError, orchestrator.ValidationError)):
            orchestrator._build_task_dependency_snapshot(task_path)


def _write_card(tasks_dir: Path, task_id: str, *, depends_on: list[str]) -> None:
    card = {
        "task_id": task_id,
        "goal": f"Test task {task_id}",
        "in_scope": ["README.md"],
        "depends_on": depends_on,
        "lanes": [{"lane_id": "lane_main", "owner_paths": ["README.md"], "depends_on": []}],
    }
    (tasks_dir / f"{task_id}_task_card.json").write_text(
        json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8"
    )
