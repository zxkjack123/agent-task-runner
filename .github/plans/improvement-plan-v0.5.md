# 改进计划：事件流 + worktree 简化 + 失败恢复

**基线**: v0.4.0, 584 tests, 81% coverage

---

## I1: 事件流（解决"看不到过程"痛点）

### 目标
每次状态转换和关键生命周期事件写入 `events.jsonl`，AOM 可用 `tail -f` 消费。

### 事件规格

```jsonc
// 状态转换事件
{"event":"state_change","state":"awaiting_work","round":1,"ts":"...","task_id":"T-42","run_id":"run-xxx"}

// worker/reviewer 生命周期
{"event":"worker_started","round":1,"ts":"..."}
{"event":"worker_failed","round":1,"ts":"...","reason":"timeout"}
{"event":"reviewer_started","round":1,"ts":"..."}
{"event":"reviewer_failed","round":1,"ts":"...","reason":"timeout"}

// 终端事件（包含 outcome 摘要）
{"event":"terminal","outcome":"approved","rounds":2,"ts":"...","decision":"approve"}
```

### 实现
| # | 任务 | 修改点 | 说明 |
|---|------|--------|------|
| 1.1 | `_emit_event(event_type, payload)` 函数 | 新函数，L996 后 | 追加 JSON 行到 `events.jsonl` |
| 1.2 | `_apply_state_transition` 中 emit | L6250+ | 每次状态转换 emit `state_change` 事件 |
| 1.3 | `_run_single_round` worker 前后 emit | L10960, L10995 | `worker_started` / `worker_completed` / `worker_timeout` |
| 1.4 | `_run_single_round` reviewer 前后 emit | L11280, L11330 | `reviewer_started` / `reviewer_completed` / `reviewer_timeout` |
| 1.5 | 终端事件 emit | `_write_round_summary` | `terminal` + outcome 摘要 |
| 1.6 | `cmd_status --events` 支持 tail | `cmd_status` | `--events` 模式持续读取并打印最新事件 |
| 1.7 | 测试 | test_orchestrator.py | 验证事件格式和字段完整性 |

**预计:** 2h

---

## I2: worktree 简化（职责归位给 AOM）

### 目标
agent-task-runner 不创建/管理 worktree，只接受 `--cwd` 在指定目录运行。AOM 负责 provision worktree。

### 变更
| # | 任务 | 修改点 | 说明 |
|---|------|--------|------|
| 2.1 | 保留 `_prune_stale_worktrees`（startup GC） | — | 用户要求保留，作为防御性 GC |
| 2.2 | `_lane_worktrees_*` 系列函数标记 deprecated | L6547-6795 | 添加 docstring `@deprecated: worktree management belongs in AOM` |
| 2.3 | `_run_single_round` 的 lane 派发跳过 worktree | L10843 | 当 `lane_dispatch_enabled` 时用 `--cwd` 而非创建 worktree |
| 2.4 | `_create_lane_worktree` 改为设置 `--cwd` | L6730 | 不在 agent-task-runner 内创建 worktree |
| 2.5 | `--cwd` CLI 参数 | run_p.add_argument | 明确指定工作目录 |
| 2.6 | `_prepare_lane_worktrees` 简化为返回目录列表 | L6759 | 不创建 git worktree，只返回目录路径 |
| 2.7 | 测试 | test_orchestrator.py | 验证 deprecation、cwd 参数转发 |

**预计:** 3h

---

## I3: 失败恢复（崩溃后自动修复）

### 目标
`loop run` 启动时检测残留 `state.json` → 自动清理或 resume。

### 决策规则
| state.json 状态 | 动作 |
|----------------|------|
| `state=done` | 正常，跳过 |
| `state=idle` | 正常，跳过 |
| `state=awaiting_work` 且 `round=1` | 可能是上次首次 worker 前崩溃 → 清理 state，重新开始 |
| `state=awaiting_work` 且 `round>1` | 上次 reviewer changes_required 后崩溃 → 从当前 round 恢复 |
| `state=awaiting_review` | worker 已完成但 reviewer 未启动 → 从 reviewer 阶段恢复 |
| 无 state.json | 正常，冷启动 |

### 实现
| # | 任务 | 修改点 | 说明 |
|---|------|--------|------|
| 3.1 | `_detect_stale_state()` 函数 | 新函数，在 `_run_multi_round_via_subprocess` 前调用 | 读取 state.json 判断是否残留 |
| 3.2 | `--resume` CLI 参数 | run_p.add_argument | 强制恢复模式 |
| 3.3 | `--clean-stale` CLI 参数 | run_p.add_argument | 强制清理残留 |
| 3.4 | 恢复逻辑 | `_run_multi_round_via_subprocess` 入口 | `awaiting_review` → 从 reviewer 继续；`awaiting_work round>1` → 从 worker 继续 |
| 3.5 | 清理逻辑 | `_run_multi_round_via_subprocess` 入口 | 清理 state.json + bus files，从 round=1 开始 |
| 3.6 | 测试 | test_orchestrator.py | 四种残留状态 × 恢复/清理行为 |

**预计:** 2.5h

---

## 总工时: 7.5h

## 执行顺序: I1 → I2 → I3

（I1 和 I2 独立，I3 依赖 I1 的事件流记录残留信息）
