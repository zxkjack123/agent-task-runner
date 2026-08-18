# Changelog

## [Unreleased] — PM #2622

### Added
- **doc-pipeline & doc-fix prompt templates**（`c6d6e39`/`7b8ff54`/`9b51310`/`d24546c`/`6f1a16f`/`9325f79`）: `.loop/templates/` 双轨镜像 4 个专用模板对（doc_pipeline/doc_fix worker+reviewer，与 project_management `data/loop_templates/templates/` 逐字节一致）；模板 render 回归测试 `tests/test_doc_pipeline_compat.py`（含 loop_kit 兼容性核查：work_report.json 终态保留 / 未知 outcome → resume_failure / max_rounds_exhausted）
- **兼容性约定**: doc_pipeline/doc_fix 循环由 bridge 侧 `--worker-noop-as-success` 驱动（哨兵终态合法零变更）；PRECONDITION-FAILED 哨兵由 PM 侧 M5 消费

## PM #2749 — Lint Debt Cleanup (2026-08-18)

### Lint
- **0 lint errors (104 → 0)**: ruff debt fully cleared. B1 automatic `ruff --fix` (62 fixes) then B2 manual semantic passes: B2a `_core.py`, B2b `__all__` line-wraps (`exceptions`/`paths`/`state`/`file_bus`/`dispatch`/`session`/`config`/`prompts`/`knowledge`/`git_helpers`), B2c test files (`test_pm_integration`/`test_doc_pipeline_compat`/`test_integration`/`test_orchestrator`). `ruff check src/loop_kit tests` → 0 errors.
- **Re-export contract preserved**: every `__all__` wrapped via `ast.literal_eval` round-trip — symbol set and order byte-identical; `from loop_kit.orchestrator import *` smoke passes.
- **Tests**: `pytest` → 615 passed / 0 failed; `py_compile` + import + CLI smoke all exit 0 (V1-V5 gate).

### Stability
- **`.loop/` transient residue purge (disk-only, no git diff)**: stale `.state.json.bak`, `events.jsonl` archive/cached dirs, orphan lock with dead PID removed; e2e fixtures + tracked assets retained. Runtime-recreated dirs regenerate normally on next loop run.

## v0.4.0 (2026-07-03)

### Architecture (T-703, T-721, T-722)
- **LoopPaths migration**: All module-level path globals eliminated; every function obtains paths via `_resolve_paths()` or explicit `paths` parameter
- **Table-driven state machine**: `_POST_ROUND_DISPATCH`, `_TERMINAL_OUTCOME_HANDLERS`, `_STATE_HANDLERS` replace if-else chains; `_RoundOutcome` enum
- **Modularization**: orchestrator.py split into facade + focused sub-modules (state, dispatch, session, config, paths, file_bus, prompts, exceptions, knowledge, git_helpers)

### Features (T-720, T-724, T-704, T-706, T-710, T-723, T-707, T-709)
- **Phase 1 quick wins**: git diff validation/truncation, report schema strictness, config unknown key detection, atomic pattern dedup
- **Keyword knowledge retrieval**: expanded token sources, frequency weighting, token budget cap, recency fallback
- **Knowledge governance**: dedup on sync, auto-prune stale entries (>90d), stale counts in cmd_status
- **Concurrent lock safety**: PID tracking in lock file, orphan lock cleanup on startup
- **Knowledge CLI**: `loop knowledge search/stats/reindex`
- **Dependency DAG**: `loop dep graph` (Mermaid), `loop dep blocked`
- **Config system**: 20 RunConfig fields via `LOOP_*` env vars, `loop config` command
- **Session management**: `loop session` debug command

### PM/AOM Integration (P0-P3)
- **Unified outcome.json**: `_fail_with_state` covers all 28 failure paths, `--outcome-file` parameter
- **`cmd_status --json`**: machine-readable polling, `--outcome-only` short-circuit
- **Reviewer verification**: `verification` field in TaskCard, safe sandboxed command execution
- **Preflight policy**: `.loop/preflight.json` with forbidden_patterns, max_file_size_mb, require_tests
- **Knowledge loop**: automatic extraction and persistence of patterns/pitfalls/facts from completed rounds
- **AOM provider**: Go provider registration, `aom pipeline-loop` command, session-spawn auto-redirect
- **Integration spec**: `docs/integration-spec.md` v1.0

### Stability (Stability Round)
- `_save_state` skips write when semantically unchanged (incl. sessions/lane_state)
- `_LoopLock` writes PID; `_cleanup_stale_lock` removes orphan locks
- `_prune_stale_worktrees` garbage-collects on startup
- `.state.json.bak` cleaned after successful recovery
- Worktree dispatch: `GIT_DIR`/`GIT_WORK_TREE` env isolation preventing commits to master
- `_dispatch_with_artifact_fallback` retries once (30s wait) on timeout
- E2E test timeouts increased (900s dispatch / 600s artifact)

### Tests
- 589 passing (+52 from v0.3.1 baseline)
- 17 new GIT_DIR worktree isolation tests
- 4 orphan lock boundary tests
- 3 worktree GC tests
- 6 fail_with_state outcome branch tests
- 1 cmd_config format test
- Lint: py_compile OK, import OK

## v0.5.0 (2026-07-03)

### Observability
- **Event stream**: `_emit_event` appends JSONL events to `events.jsonl` on every state transition and terminal outcome
- Events: `state_change` (state/round/task_id/run_id), `terminal` (outcome/rounds/decision/exit_code/files_changed)
- AOM can `tail -f events.jsonl` for real-time progress

### Worktree Simplification
- `--cwd` CLI argument lets AOM specify the provisioned worktree directory
- `_lane_worktrees_*` functions marked `@deprecated` — worktree management delegated to AOM
- agent-task-runner no longer creates or manages git worktrees

### Failure Recovery
- `_detect_stale_state` detects leftover state.json from crashed runs
- Auto-resume: `awaiting_review` → continue from reviewer; `awaiting_work round>1` → continue from worker
- Auto-clean: other stale states → clean bus files and restart
- `--clean-stale` CLI arg for forced cleanup of all bus files
- `_clean_stale_loop_state` removes state.json + all bus files

### Gap Closure
- GIT_DIR worktree isolation tests (3 tests)
- `_cleanup_stale_lock` boundary tests (4 tests)
- `_prune_stale_worktrees` GC tests (3 tests)
- `_fail_with_state` outcome branch tests (6 tests)
- `cmd_config` output format test
- Dispatch retry: `_dispatch_with_artifact_fallback` retries once (30s wait)

### P0+P1 Integration (2026-07-10)

- **PM dispatcher** (`bridge.py:dispatch_atr`) now passes `--outcome-file` and `--cwd` to ATR
- **Result detection** (`bridge.py:check_and_handle_results`) prefers `summary.json` over `state.json` polling — eliminates 5-minute latency
- **Outcome mapping** (`bridge.py:OUTCOME_TO_PM_STATUS`) unified with AOM `pipeline_loop.go`
- **Event stream** (`bridge.py:read_latest_events`) for real-time feedback via `events.jsonl`
- **pm-agent-runner** marked as `@deprecated` — auto task execution now routes through `bridge.py` directly

## v0.6.0 (2026-07-11)

### PM/AOM Full-Chain Integration
- **Full-chain E2E tests**: 11 PM→ATR→PM chain tests + 2 ATR mock tests + 2 Go sync tests
- **pm_outcome_handler.py**: AOM pipeline-loop → PM status sync script
- **events.jsonl consumer**: `read_latest_events()` in PM cron dispatcher
- **OUTCOME_TO_PM_STATUS**: unified mapping validated with 11-outcome test
- **Priority queue**: pick_queued() with due_date + priority scoring
- **Concurrent control**: _MAX_CONCURRENT=1 with running task detection

### Documentation
- **System architecture doc**: full ecosystem topology with ASCII diagram
- **AOM README**: Agent Task Runner integration section with pipeline-loop docs
- **PM integration doc**: v3→v4 with P0+P1 changes
- **MCP tool reference**: ATR-triggering tools + exclusion tags
- **Migration guide**: pm-agent-runner → bridge.py
- **opencode-tasks coexistence**: documented scheduling differences

### Test Coverage
- ATR: 591 tests (586 unit + 3 integration + 2 mock)
- PM bridge: 18 full-chain tests
- AOM Go: 18 tests
- **Total: 627 passing across 3 repos**

## v0.7.0 (2026-08-14)

### ATR Worker Robustness (PM #2653 / #2654)
- **`--auto` permission flag**: opencode worker dispatch (`_build_opencode_command`) now appends `--auto` (auto-approve non-explicitly-denied permissions). Headless workers no longer stall on interactive permission prompts (T-2623). User-side 17 explicit deny rules still honored.
- **Partial work_report synthesis**: when a worker exits (rc=0) without writing work_report.json, `_dispatch_with_artifact_fallback` with `synthesize_on_missing=True` synthesizes a minimal `status="partial"` report (head_sha / files_changed / notes), preserving committed-but-unreported work into the reviewer round instead of discarding the whole run.
- **Partial-status enrichment guard**: `_enrich_work_report_runtime_fields` no longer overwrites an existing `status="partial"` (previously forced to "completed").
- New tests: `--auto` in cmd for new-session + resume branches; synthesize-partial report; enrich preserves partial status.

### Stability
- `_dispatch_with_artifact_fallback` gained optional `synthesize_on_missing` / `synthesize_cwd` kwargs; lane workers synthesize from their worktree handle; lane reviewers do not synthesize.

### Tests
- `pytest -m "not e2e"` → 599 passed / 1 pre-existing failed / 1 skipped / 3 deselected (deterministic repeat: 600 passed / 1 pre-existing failed / 1 skipped).

### E2E Self-Test Isolation (PM #2675, 2026-08-14)
- **tmp-repo e2e isolation**: `tests/test_e2e_smoke.py` now runs the loop inside a throwaway git repo under `tmp_path` (`git init` + minimal loop skeleton) instead of the real repository — loop commits can never reach master history again.
- **answer.py/greet.py removal**: e2e worker artifacts removed from repo root and anchored in `.gitignore`.
- **uv.lock sync**: uv 0.6.0→0.6.1 lockfile drift committed.
- **pytest addopts**: default `pytest` run excludes e2e (`-m "not e2e"`); CI (`loop-ci.yml`) synced accordingly. Run e2e explicitly with `pytest -m e2e`.
- **`_persist_knowledge_updates` fix**: reviewer knowledge pattern persistence no longer crashes on `_normalize_pattern_entry` signature mismatch.
- Independent acceptance: PASS (0 blocking defects) — 3 consecutive full pytest runs left HEAD pinned at `36a5bcf`; e2e 3 passed (~500s); commits `36a5bcf` `2723361` `9d1d6db` `995c7e8` `3eb7193` (+ revert pair `f6bc215`→`05e3801` retained for audit).

### Daemon Idle Crash-Restart Fix (PM #2747, 2026-08-17)
- **Idle clean exit**: daemon-mode invocations (no `--task` / no `task_ref`) with no task card now exit cleanly (exit 0) BEFORE the dirty-worktree check, ending the 30s crash-restart loop on unrelated dirty files.
- **Dirty-tree downgrade in daemon mode**: `_enforce_clean_worktree_or_exit` gained `warn_only` — daemon mode warns and proceeds instead of hard-failing; explicit-mode invocations keep exit 4 semantics.
- **Task-scope overlap guard**: daemon mode refuses (exit 4) when dirty tracked paths overlap the task card's `in_scope` — prevents lane-merge fail-fast `git reset --hard` from wiping unrelated uncommitted changes.
- **systemd unit**: `Restart=always` → `Restart=on-failure` (exit 0 no longer restarts; real failures keep 30s retry). Timer untouched; task pickup cadence changes from crash-loop 30s to timer 5min.
- Tests: `TestDaemonIdle` (8 cases) covering idle exit 0, dirty-check precedence, warn-only downgrade, scope-overlap refusal, and explicit-mode regressions.

### Pre-Existing Test Failure Fix (PM #2748, 2026-08-17)
- **Relative-date freshness samples**: hardcoded future-dated fresh sample (`"last_verified": "2026-04-01T12:00:00Z"`) — a time bomb that expired past the 30-day stale threshold — replaced with runtime-computed relative date (`now(UTC) - 5 days`). Also neutralized the analogous `"source_version": "2026-04-01"` latent hazard. Eliminates the `TestCmdStatus::test_shows_context_file_stats` time bomb with zero new dependencies.
- **Suite-wide path-global isolation**: new `tests/conftest.py` adds a suite-level autouse fixture that snapshots/restores the 8 module globals mutated by 14 direct calls to production `orchestrator._configure_loop_paths()` (from `test_integration.py` and `test_pm_integration.py`), preventing test-order-dependent pollution from breaking `TestResetDefault::test_task_card_in_resettable_files`.
- Result: full `pytest -m "not e2e"` → **614 passed, 1 skipped, 3 deselected, 0 failed** (4 consistent full runs); both previously-failing tests pass in isolation. Commit `768ffb1` (tests only).
