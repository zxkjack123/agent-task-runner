# P0+P1+P2 完整改进方案

## 现状分析 (基于实际代码审阅)

| 发现 | 实际状态 |
|------|---------|
| P0.1: PM dispatcher 使用 `--loop-dir` 无 `--outcome-file` | `bridge.py:dispatch_atr()` L359-369 没有 `--outcome-file` |
| P0.1: 结果靠轮询 state.json | `bridge.py:check_and_handle_results()` 每 5 分钟轮询 |
| P0.2: events.jsonl 无人消费 | 刚加的 feature，PM 和 AOM 都没用 |
| P1.1: PM 和 AOM 状态映射不一致 | PM: done/failed, AOM: Done/NeedsAttention/Blocked |
| P1.2: pm-agent-runner 是死代码 | ATR bridge 直接 subprocess.Popen，不经过 pm-agent-runner |
| P2.1: 优先级队列已存在 | `bridge.py:pick_queued()` L242-301 已有 scoring |
| P2.2: opencode-tasks 独立调度 | 与 ATR 完全独立，互不感知 |

---

## P0: 消除 5 分钟延迟 — PM dispatcher 改用 --outcome-file + events.jsonl

### 任务
- **P0.1**: `dispatch_atr()` 添加 `--outcome-file` 参数
- **P0.2**: `check_and_handle_results()` 优先用 `summary.json`，fallback 到 `state.json`
- **P0.3**: PM dispatcher 新增 `--event-tail` 模式消费 `events.jsonl`（可选，降低轮询频率到 30s）

### 文件变更
- `project_management/src/auto_task/bridge.py`: dispatch_atr L359 添加 `--outcome-file`
- `project_management/src/auto_task/bridge.py`: check_and_handle_results 先读 summary.json

### 验收
- ATR 任务完成后 PM 立即检测（不再等待 5 分钟）
- `--outcome-file` 路径与 loop_dir 一致

---

## P1: 统一状态映射 + 清理死代码

### P1.1: 统一 outcome→status 映射表

**文件:** `project_management/src/auto_task/bridge.py`

```python
OUTCOME_TO_PM_STATUS = {
    "approved": "done",
    "no_change_success": "done", 
    "validation_failure": "needs_attention",
    "config_error": "needs_attention",
    "state_error": "needs_attention",
    "timeout": "blocked",
    "interrupted": "blocked",
    "max_rounds_exhausted": "blocked",
    "dirty_worktree": "blocked",
    "lock_failure": "blocked",
}
```

PM 和 AOM 都用同一张映射表（AOM 侧已在 `pipeline_loop.go` 实现）

### P1.2: 标记 pm-agent-runner 为 deprecated

**文件:** `pm-agent-runner/README.md`

加一行 `> **@deprecated** — auto task execution now goes through project_management/src/auto_task/bridge.py directly.`

---

## P2: 调度优先级 + 统一执行引擎

### P2.1: 优先级队列增强

`bridge.py:pick_queued()` 已有完善的 priority scoring。不需要改动。

### P2.2: opencode-tasks → ATR 桥接（低优先级）

opencode-tasks 的定时任务可以交给 agent-task-runner 执行。需要：
- opencode-tasks 生成 task_card.json
- 调用 `bridge.py:enqueue_task()` 或直接 `dispatch_atr()`
- 结果回写到 opencode-tasks 的 SQLite DB

**当前优先级: P2 — 不强求，方案可行但不紧急**

---

## 执行计划

### Phase A: P0 + P1 代码变更 (1.5h)

| # | 文件 | 变更 |
|---|------|------|
| A1 | `bridge.py:dispatch_atr` | 添加 `--outcome-file` + `--cwd` 参数 |
| A2 | `bridge.py:check_and_handle_results` | 优先读 summary.json，fallback state.json |
| A3 | `bridge.py` | 添加 `OUTCOME_TO_PM_STATUS` 映射表 |
| A4 | `pm-agent-runner/README.md` | 添加 deprecated 标记 |

### Phase B: 测试验证 (0.5h)

| # | 内容 |
|---|------|
| B1 | agent-task-runner E2E smoke test with --outcome-file |
| B2 | PM dispatcher dry-run with updated dispatch_atr |

### Phase C: 文档更新 (0.5h)

| # | 内容 |
|---|------|
| C1 | 更新 `docs/pm-atr-integration-design.md` 反映新的调用方式 |
| C2 | agent-task-runner CHANGELOG 更新 |

---

**总计: 2.5h**
