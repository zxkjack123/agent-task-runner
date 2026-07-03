# 3 缺口执行计划

> 基线: 567 tests, 81% coverage, GIT_DIR fix 零测试

---

## G1: 多 lane 并行 E2E 验证

### 1.1 GIT_DIR 隔离单元测试
**文件:** `tests/test_orchestrator.py`
**TestGITDirWorktreeIsolation:**
- `test_git_dir_set_when_cwd_is_worktree` — cwd `.git` 为文件时，`subprocess.Popen` 的 `env` 含 `GIT_DIR`/`GIT_WORK_TREE`
- `test_git_dir_not_set_when_git_is_directory` — cwd `.git` 为目录时（非 worktree），`env` 不含 `GIT_DIR`
- `test_git_dir_skip_on_broken_git_file` — `.git` 文件格式错误时，`env` 不含 `GIT_DIR`

### 1.2 集成测试
**文件:** `tests/test_integration.py`
**TestMultiLaneWorktreeIsolation:**
- 创建临时 worktree → 模拟 worker commit → verify master HEAD 不变、worktree branch 前进

### 1.3 真实 E2E Multilane
用现有 `E2E-MULTI-LANE` task_card + `max-parallel-workers=2`

---

## G2: 覆盖率 81% → 85%

### 2.1 `_cleanup_stale_lock` 边界测试
`test_cleanup_stale_lock_pid_alive/dead/invalid/missing`

### 2.2 `_prune_stale_worktrees` 测试
孤儿目录/已注册/空目录三分支

### 2.3 `cmd_config` 输出格式测试
env/file/default 来源标注验证

### 2.4 `_fail_with_state` outcome 分支覆盖
`config_error/lock_failure/dirty_worktree/validation_failure/max_rounds_exhausted/interrupted`

---

## G3: opencode E2E 稳定性

### 3.1 dispatch 重试 — `_dispatch_with_artifact_fallback` 第一次超时后 wait 30s 重试一次

### 3.2 E2E 测试超时增加 — `900/600`

---
**预计:** 4.5h
