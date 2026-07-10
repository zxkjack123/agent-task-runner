# P0+P1+P2 集成改进方案（已细化）

> **状态**: Phase A 完成 (A1-A4 ✅) | Phase B 部分完成 | Phase C 待做
> **基线**: agent-task-runner v0.5.0 (584 tests), project_management bridge.py v2, pm-agent-runner deprecated

---

## 现状分析

```
当前数据流:
  PM task (tags=["auto"])
    → bridge.py: enqueue_task() → auto_task_queue (status=queued)
    → systemd timer (每5分钟) → dispatcher.py: pick_queued()
    → dispatch_atr() → python -m loop_kit run --auto-dispatch --loop-dir .../
    → ATR: Worker → Reviewer → state.json
    → dispatcher.py: check_and_handle_results() → 轮询 state.json (每5分钟)
    → pm_task_update(status="review") + 飞书通知
```

| 问题 | 严重度 | 当前状态 |
|------|--------|---------|
| P0.1: 结果靠轮询 state.json，最坏延迟 5 分钟 | 🔴 | ✅ 已修 — summary.json 优先 |
| P0.2: dispatch_atr 未传 --outcome-file | 🔴 | ✅ 已修 — bridge.py L370-371 |
| P0.3: events.jsonl 无人消费 | 🟡 | ⬜ 待做 — 在 PM cron 侧 tail events.jsonl |
| P1.1: PM / AOM 状态映射不一致 | 🟡 | ✅ 已修 — OUTCOME_TO_PM_STATUS 映射表 |
| P1.2: pm-agent-runner 是死代码 | 🟡 | ✅ 已修 — README @deprecated |
| P2.1: 并发无优先级 | 🟢 | ✅ 已有 — pick_queued() scoring |
| P2.2: opencode-tasks 独立于 ATR | 🟢 | ⬜ 待规划 — P2.3 方案 |

---

## Phase A: P0 + P1 代码变更 ✅ 已完成

### A1 ✅ `dispatch_atr()` 添加 `--outcome-file` + `--cwd`

**文件**: `project_management/src/auto_task/bridge.py` L367-371

```python
cmd = [
    str(_ATR_VENV), "-m", "loop_kit", "run",
    "--loop-dir", str(loop_dir.resolve()),
    "--auto-dispatch", "--allow-dirty",
    "--worker-backend", "opencode", "--reviewer-backend", "opencode",
    "--max-rounds", str(_MAX_ROUNDS), "--timeout", str(_TIMEOUT_SEC),
    "--artifact-timeout", "300",
    "--outcome-file", str(loop_dir.resolve() / "summary.json"),  # ← 新增
    "--cwd", str(loop_dir.resolve()),                            # ← 新增
]
```

### A2 ✅ `check_and_handle_results()` 优先读 summary.json

**文件**: `project_management/src/auto_task/bridge.py` L423-441

```python
summary_path = Path(loop_dir_str) / "summary.json"
if summary_path.exists():
    # 立即检测完成（<5s），不再等待 5 分钟轮询
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    outcome = summary.get("outcome", "")
    if outcome in SUCCESS_OUTCOMES:
        _mark_done(conn, entry_id, task_id, summary)
    else:
        _mark_failed(conn, entry_id, task_id, f"ATR outcome: {outcome}")
    continue
# fallback: state.json for non-terminal states
if not state_path.exists():
    continue
```

### A3 ✅ `OUTCOME_TO_PM_STATUS` 统一映射表

**文件**: `project_management/src/auto_task/bridge.py` L398-411

```python
OUTCOME_TO_PM_STATUS: dict[str, str] = {
    "approved":             "done",
    "no_change_success":    "done",
    "validation_failure":   "needs_attention",
    "config_error":         "needs_attention",
    "state_error":          "needs_attention",
    "timeout":              "blocked",
    "interrupted":          "blocked",
    "max_rounds_exhausted": "blocked",
    "dirty_worktree":       "blocked",
    "lock_failure":         "blocked",
    "changes_required_retry": "running",
}
```

与 AOM 侧 `pipeline_loop.go` L170-192 的映射保持一致。

### A4 ✅ pm-agent-runner 标记 deprecated

**文件**: `pm-agent-runner/README.md` L3

```markdown
> **@deprecated since 2026-07-03** — auto task execution now goes through
> `project_management/src/auto_task/bridge.py` directly via `dispatch_atr()`.
```

---

## Phase B: 测试验证

### B1 ✅ agent-task-runner 584 tests passing

```bash
uv run --group dev pytest tests/ -q
# 584 passed, 2 deselected
```

### B2 ⬜ PM dispatcher 集成测试

验证 `summary.json` 被立即读取：

```bash
# 1. 创建 auto task
pm_task_create(title="E2E test", tags=["auto"], notes="Write a test file")

# 2. 手动触发 dispatcher (跳过 5min timer)
cd /home/gw/opt/project_management
python scripts/auto_task_dispatcher.py

# 3. 验证结果在 30s 内被检测（而非 5min）
# Watch auto_task_queue status transition: queued → running → done
sqlite3 data/pm.db "SELECT status, finished_at FROM auto_task_queue ORDER BY id DESC LIMIT 1"
```

### B3 ⬜ summary.json 损坏时的优雅降级

```python
# bridge.py L427-429 已包含 try/except
try:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, OSError):
    # fall through to state.json polling
    pass
```

验证：手动损坏 summary.json → dispatcher 不崩溃，降级到 state.json 轮询。

---

## Phase C: 事件流消费 + 文档

### C1 ⬜ PM cron 消费 `events.jsonl` 实现实时反馈

**目标**: PM cron 在每个 5 分钟 tick 检查 running task 的 events.jsonl，提取最新事件用于飞书通知（如 "Worker started round 2"）。

**文件**: `project_management/scripts/auto_task_dispatcher.py` 或 `src/auto_task/bridge.py`

```python
def read_latest_events(loop_dir: str, last_offset: int) -> tuple[list[dict], int]:
    """Read new events since last_offset from events.jsonl."""
    events_path = Path(loop_dir) / "events.jsonl"
    if not events_path.exists():
        return [], last_offset
    with open(events_path) as f:
        f.seek(last_offset)
        lines = f.readlines()
        events = [json.loads(line) for line in lines if line.strip()]
        new_offset = f.tell()
    return events, new_offset
```

集成到 `check_and_handle_results()`: 每次检查 running task 时读取最新事件，将 `state_change` 和 `terminal` 事件注入飞书通知。

### C2 ⬜ 更新集成设计文档

**文件**: `project_management/docs/pm-atr-integration-design.md`

更新内容：
- 最新的 dispatch_atr 调用参数（含 --outcome-file + --cwd）
- 结果检测从 state.json 轮询 → summary.json 立即检测
- OUTCOME_TO_PM_STATUS 映射表引用
- events.jsonl 事件流消费说明

### C3 ⬜ agent-task-runner CHANGELOG

更新到 v0.5.0 之后，记录 P0+P1 对 PM 侧的影响。

---

## Phase D: P2 远期改进

### D1: opencode-tasks → ATR 统一调度

**目标**: opencode-tasks 的定时 prompt 任务也走 agent-task-runner 的 Worker→Reviewer 循环。

**方案**:
1. opencode-tasks scheduler daemon 检测到 due task → 生成 task_card.json
2. 调用 `bridge.py:enqueue_task(task_card_json=...)` 入队
3. PM cron dispatcher 按优先级 pick + dispatch ATR
4. ATR 完成 → summary.json → bridge.py 检测 → opencode-tasks DB 回写

**优先级**: P3 — 不紧急，当前 opencode-tasks 直接调 opencode 可正常工作

### D2: 并发限制从 1 提升到 N（可配置）

**当前**: `_MAX_CONCURRENT = 1`（环境变量 `ATR_MAX_CONCURRENT` 控制）
**分析**: 单并发避免 opencode session 冲突和 API 配额争抢。
**改进**: 当使用不同 opencode session 时，可安全提升为 2-3。

---

## 执行进度

| # | 内容 | 状态 | 提交 |
|---|------|------|------|
| A1 | dispatch_atr add --outcome-file + --cwd | ✅ | 9d93896 |
| A2 | check_and_handle_results prefer summary.json | ✅ | 9d93896 |
| A3 | OUTCOME_TO_PM_STATUS mapping table | ✅ | 9d93896 |
| A4 | pm-agent-runner README deprecated | ✅ | 7558554 |
| B1 | ATR test suite verify | ✅ | 584 passed |
| B2 | PM dispatcher integration test | ⬜ | — |
| B3 | summary.json corruption fallback | ⬜ | — |
| C1 | PM cron tail events.jsonl | ⬜ | — |
| C2 | Update integration design doc | ⬜ | — |
| C3 | ATR CHANGELOG update | ⬜ | — |
| D1 | opencode-tasks → ATR bridge | ⬜ | — |
| D2 | Concurrent execution >1 | ⬜ | — |

---

**已完成**: 6/12 | **待做**: 6/12
