# 4 个残留问题修复计划

## 问题 1: AOM → PM 状态不同步 🔴

**现象:** AOM `pipeline-loop` 完成后仅更新 AOM 自己的 SQLite，不回写 PM 系统。

**方案:** 创建 `scripts/pm_outcome_handler.py`，AOM 在 pipeline-loop 完成后调用：
```bash
python pm_outcome_handler.py /path/to/outcome.json <task_id>
```

**文件:**
- `project_management/scripts/pm_outcome_handler.py` (新建, ~50行)
- `agent-orchestrator-management/internal/cli/pipeline_loop.go` (+5行，添加 subprocess 调用)

**验收:** AOM pipeline-loop 完成后 PM 任务状态同步更新

---

## 问题 2: events.jsonl 未被 PM cron 消费 🟡

**现象:** `read_latest_events()` 已添加但 `check_and_handle_results()` 没调用它。

**方案:** 在 `check_and_handle_results()` 的 running 任务轮询中追加事件读取，将最新事件信息写入 auto_task_queue 的 progress 字段。

**文件:** `project_management/src/auto_task/bridge.py`

**验收:** 轮询 running 任务时能从 events.jsonl 读取状态变更

---

## 问题 3: opencode-tasks 独立调度 🟡

**现象:** opencode-tasks 直接调 `opencode run`，不经过 ATR Worker/Reviewer 循环。

**方案:** 不改变 opencode-tasks。在 `docs/` 中新增共存说明文档。

**文件:** `agent-task-runner/docs/opencode-tasks-coexistence.md`

---

## 问题 4: bridge.py 直写 SQL 🟢

**现象:** `_mark_done`/`_mark_failed` 直接 UPDATE PM SQLite，不经过 MCP。

**方案:** 不改变。直接 SQL 写是 PM Cron Dispatcher 的设计选择——同进程内操作比 MCP 调用更快且更可靠。在 bridge.py 顶部添加设计说明注释。

**文件:** `project_management/src/auto_task/bridge.py` (+3行注释)

---

## 执行顺序

| # | 任务 | 预计 |
|---|------|------|
| 1.1 | 创建 pm_outcome_handler.py | 20min |
| 1.2 | AOM pipeline-loop 调用 handler | 10min |
| 2.1 | check_and_handle_results 消费 events.jsonl | 30min |
| 3.1 | opencode-tasks 共存文档 | 15min |
| 4.1 | bridge.py 设计注释 | 5min |
| 4.2 | agent-task-runner 测试 + 全量提交 | 15min |

**总计: 1.5h**
