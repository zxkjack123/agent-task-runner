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
