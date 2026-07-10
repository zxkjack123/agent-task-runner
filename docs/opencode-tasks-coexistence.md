# opencode-tasks 与本系统的共存说明

opencode-tasks 是一个独立的 Node.js 调度器，用于在 opencode session 中执行
定时 prompt（如 daily standup, branch cleanup, weekly report）。

## 调度的区别

| | opencode-tasks | agent-task-runner |
|---|---|---|
| 调度器 | launchd/systemd (60s) | PM systemd timer (5min) |
| 触发机制 | cron spec in YAML frontmatter | `tags=["auto"]` on PM task |
| 执行方式 | direct `opencode run` | `loop run --auto-dispatch` (PM→Worker→Reviewer 循环) |
| 适用场景 | 轻量定时 prompt，不需要 review | 需要 Worker→Reviewer 的代码任务 |

## 资源协调

两个调度器同时运行时不冲突：

- ATR 单并发控制(`_MAX_CONCURRENT=1`)保证同时只有一个 Worker/Reviewer 在跑
- opencode-tasks 直接调用 `opencode run`，不经过 ATR 的锁机制
- 如果资源紧张(API 配额/session 数量)，考虑错开 cron 时间

## 未来统一方案

opencode-tasks 的定时任务可以交给 agent-task-runner 执行(通过 `bridge.py:enqueue_task()`)。
需要 opencode-tasks 侧适配：生成 task_card.json → 入队 PM auto_task_queue → ATR 执行 → 回写结果。
