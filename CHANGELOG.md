# Changelog

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
