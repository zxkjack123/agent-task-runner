# Project Snapshot — agent-task-runner

> 轻量 bootstrap 快照（2026-08-17，Plan Architect 为 PM #2748 首次生成）。
> 仅覆盖本次计划所需上下文；后续 plan 可在此基础上扩展。

## Architecture
- 包布局：`src/loop_kit/`（`orchestrator.py` 薄门面 re-export `_core.py`；另有 `exceptions/paths/state/file_bus/dispatch/session/config/prompts/knowledge/git_helpers` 子模块）
- 测试：`tests/`（7 个文件：test_bout_to_gitr_coupling / test_concurrency / test_doc_pipeline_compat / test_e2e_smoke / test_integration / test_orchestrator / test_pm_integration），**无 conftest.py**

## Key Modules（与测试全局状态相关）
- `src/loop_kit/_core.py`
  - `_stored_paths: LoopPaths | None`（:665）——`_configure_loop_paths()`（:677）直改，另置 `_LOGS_DIR_ENSURED/_LOGS_DIR_ENSURED_PATH`
  - `PATTERN_STALE_DAYS = 30`（:440）、`PATTERN_HIGH_CONFIDENCE = 0.7`（:441）、`_KNOWLEDGE_STALE_PRUNE_DAYS = 90`（:455）
  - `ROOT = Path.cwd()`（:336，import 时求值）、`_LOOP_DIR = ROOT / ".loop"`（:337）
  - `_RESETTABLE_FILES = _resettable_files()`（:744，import 时求值一次）
  - 时间解析：`_parse_utc_iso8601` / `_to_utc_iso8601`（UTC，"Z" 后缀兼容）
  - feed 全局 setter：`_set_feed_task_id/_set_feed_round/_set_feed_run_id/_set_feed_task_route_policy`（:1314 起）
- `tests/test_orchestrator.py` 已有 file-scope autouse fixture `_isolate_orchestrator_path_globals`（:62-84，快照/恢复 8 个模块全局）——本次计划 conftest 方案的原型

## Test Commands
- 全量（默认已排除 e2e）：`uv run --group dev pytest -q`（pyproject `addopts = ["-m", "not e2e"]`）
- e2e 单独：`uv run --group dev pytest -m e2e`
- 配置：`pyproject.toml [tool.pytest.ini_options]`（testpaths=["tests"]，markers：e2e / integration）

## CI
- 本仓库 CI 配置未在本次调研范围内确认（任务不涉及 CI 变更）

## Dependencies（dev）
- pytest>=9.0.2、pytest-timeout>=2.4.0、ruff>=0.11
- **无** freezegun / pytest-randomly / time-machine / pytest-order（时间冻结方案需引新依赖）

## 已知并发工作区状态（2026-08-17，HEAD=7872db9）
- #2622 会话未提交改动（**严禁卷入其它 commit**）：
  - `M src/loop_kit/_core.py`（格式化 reflow）
  - `M tests/test_orchestrator.py`（42 个 hunk：格式化 + 12 个新测试函数）
  - `M .github/plans/pm2622-doc-pipeline.md`
  - `?? traces/`、`?? .github/plans/backup/`
