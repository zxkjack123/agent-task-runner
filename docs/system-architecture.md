# System Architecture — Agent Ecosystem

> 2026-07-11 | 覆盖: PM + AOM + agent-task-runner + opencode + opencode-tasks

## 架构总览

```
                         ┌─────────────────────┐
                         │   PM System          │
                         │   (SQLite + MCP)     │
                         │                      │
                         │  pm_task_create(...) │
                         │  pm_task_complete()  │
                         │  pm_task_update()    │
                         └──────┬──────────────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
     │  auto_task/  │  │  AOM (Go)    │  │ opencode-    │
     │  bridge.py   │  │  control     │  │ tasks (Node) │
     │              │  │  plane       │  │              │
     │ enqueue_task │  │              │  │ scheduler    │
     │ dispatch_atr │  │ pipeline-    │  │ (60s cron)   │
     │ check_result │  │ loop         │  │              │
     └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
            │                 │                 │
            │ systemd         │ manual          │ systemd
            │ timer 5min      │ invocation      │ timer 60s
            │                 │                 │
            ▼                 ▼                 ▼
     ┌────────────────────────────────────────────────┐
     │          agent-task-runner (loop_kit)          │
     │                                                │
     │   ┌─ task_card.json ─┐                        │
     │   │  (PM: LLM generates│                       │
     │   │   AOM: task record)│                       │
     │   └───────────────────┘                        │
     │                                                │
     │   ┌─────────┐    ┌──────────┐                 │
     │   │ Worker   │───▶│ Reviewer │                 │
     │   │ (opencode)│   │ (opencode)│    ← auto-     │
     │   │          │    │          │      dispatch   │
     │   │ writes   │    │ validates │                 │
     │   │ code     │    │ result   │                 │
     │   └────┬─────┘    └────┬─────┘                 │
     │        │               │                       │
     │        ▼               ▼                       │
     │   ┌──────────────────────────┐                 │
     │   │  summary.json            │                 │
     │   │  events.jsonl            │                 │
     │   │  state.json (fallback)   │                 │
     │   └──────────┬───────────────┘                 │
     └──────────────┼────────────────────────────────┘
                    │
                    ▼
     ┌──────────────────────────────────┐
     │  PM Result Handler               │
     │                                  │
     │  bridge.py:                      │
     │    check_and_handle_results()    │
     │    → reads summary.json (<5s)    │
     │    → reads events.jsonl          │
     │    → fallback: state.json        │
     │                                  │
     │  scripts/:                       │
     │    pm_outcome_handler.py         │
     │    → AOM pipeline-loop calls     │
     │    → PM task status sync         │
     │                                  │
     │  Notification:                   │
     │    → Feishu card (飞书卡片)      │
     └──────────────────────────────────┘
```

## 数据流

### Path A: PM Cron Auto-Dispatch（主要路径）

```
1. User/AI: pm_task_create(title="...", tags=["auto"])
2. PM MCP: detects "auto" tag → bridge.enqueue_task()
3. bridge.py: LLM decomposes task → task_card_json → INSERT auto_task_queue
4. systemd timer (5min): dispatcher.py → pick_queued()
5. dispatch_atr(): python -m loop_kit run --auto-dispatch --outcome-file ...
6. ATR: Worker(opencode) → Reviewer(opencode) → summary.json
7. bridge.check_and_handle_results(): reads summary.json → _mark_done()
8. PM: task status="review", progress=100, Feishu card sent
```

### Path B: AOM Pipeline-Loop（用于 AOM 管理的任务）

```
1. User: aom pipeline-loop <task-id>
2. AOM: generateTaskCardJSON → provision worktree
3. AOM: exec.Command("python", "-m", "loop_kit", "run", ...)
4. ATR: Worker → Reviewer → summary.json
5. AOM: readOutcomeJSON → taskService.Close/Update (AOM local DB)
6. AOM: exec.Command("python", "pm_outcome_handler.py", ...) → PM sync
```

### Path C: Manual CLI

```
1. User: loop run --task task_card.json --auto-dispatch
2. ATR: Worker → Reviewer → summary.json → events.jsonl
```

## 关键文件

| 组件 | 文件 |
|------|------|
| PM MCP Server | `project_management/mcp_server/server.py` |
| Auto Task Bridge | `project_management/src/auto_task/bridge.py` |
| Cron Dispatcher | `project_management/scripts/auto_task_dispatcher.py` |
| PM Outcome Handler | `project_management/scripts/pm_outcome_handler.py` |
| AOM Pipeline Loop | `agent-orchestrator-management/internal/cli/pipeline_loop.go` |
| AOM ATR Provider | `agent-orchestrator-management/internal/provider/agent_task_runner.go` |
| ATR Core Loop | `agent-task-runner/src/loop_kit/_core.py` |
| ATR Dispatch | `agent-task-runner/src/loop_kit/dispatch.py` |
| ATR State Machine | `agent-task-runner/src/loop_kit/state.py` |

## Layered Pipeline (fit-review → execute → accept → close)

**归属声明(必读)**: 该分层管线由 **copilot-agents 侧 `pm-task-closed-loop` skill 编排**,并非 `src/loop_kit/state.py` 实现。ATR 核心循环(state 4 态: idle/awaiting_work/awaiting_review/done)仅对应本流中的 **execute** 段;fit-review 是 loop 前置,accept/close 是 loop 后置。三者为可插拔阶段,不改变现有 worker↔reviewer 核心循环。

- **T1 轻量(默认)**: 适配审查(task-fit-reviewer)→ 执行(ATR worker/reviewer 循环)→ 独立验收(acceptance-verifier)→ 收尾(closer)
- **T2 标准**: + plan-architect 计划
- **T3 重型**: + critical-thinking 挑战 + 人工审批点(触发含: 不可逆操作、高风险面、验收失败 1 次自动升级、外部事实断言密集)

> **分级命名交叉引用(2026-08-18 doc-sync #2872)**: 本节 T1/T2/T3 是 **ATR 分层管线的历史分级命名**（4/5/6 环节递进），与 pm-task-closed-loop skill 的 `complexity:T0/T1/T2`（短链/全链/全链+CT 双轮）是**两套独立分级体系**，非同一体系的改名。近似映射（非等价）：本节 T1 ≈ skill T0+fit-review、T2 ≈ T1、T3 ≈ T2。执行编排时以 skill 的 complexity tags 为准；本节仅描述 ATR 管线的历史阶段划分。

**不变底线**: 前置适配审查 / 执行与验收独立性分离(+外部真相交叉验证 + 修复后复验)/ 收尾闭环。
**护栏**: 验收独立+外部交叉验证 / commit-relative 验证 / 外部事实断言附证据或待验证标记 / .loop 工件衔接 / 计划验收命令自推演。

角色文档: `docs/roles/task-fit-reviewer.md`、`docs/roles/acceptance-verifier.md`、`docs/roles/closer.md`(输出契约均为编排侧产物,非 loop_kit dispatch 工件)。

## 相关文档

- [ATR Integration Spec](integration-spec.md) — AOM 集成规范
- [PM-ATR Design](../project_management/docs/pm-atr-integration-design.md) — PM 侧设计
- [opencode-tasks Coexistence](opencode-tasks-coexistence.md) — opencode-tasks 共存
- [AOM README](../agent-orchestrator-management/README.md) — AOM 文档
