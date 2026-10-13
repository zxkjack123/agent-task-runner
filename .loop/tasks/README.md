# 📋 Task Cards Index（对账后台账 · 2026-10-13）

> **对账说明**：本索引原为 2026-04/06 路线图快照，与磁盘卡片、代码事实长期三方不一致
> （8 张 0 字节空卡、8 张索引引用但从未创建的卡、多数条目实际已由 PM 任务渠道交付）。
> 2026-10-13 经 dev-orchestrator 全量对账（用户授权，PM #T-4397）：已交付项按代码事实标记，
> 已关闭卡片移入 `archive/`，本文件为唯一有效台账。**不要按旧"Execution Order"批次执行。**

## 🗂 卡片处置总览

- 活跃卡片：**0 张**（本目录当前无待执行卡）
- 归档卡片：`archive/`（11 张：8 张 0 字节占位 T-7xx + dsh-pilot-T4 + dsh-pilot-T5-lanes + E2E-1PLUS1）
- 新任务一律走 PM 系统建卡（auto 派发链：PM 建卡 → bridge enqueue → dispatcher → `loop run`），
  本目录不再作为活跃任务源

## T-7xx / 路线图批次对账结论（逐项证据，2026-10-13 实测）

| ID | 原标题 | 对账结论 | 证据 |
|----|--------|----------|------|
| T-701 | state.json schema versioning + migration | ✅ 已交付 | `_migrate_state_schema` / `_validate_state_transition_residue`（_core.py，pm3263 计划 I7 行号实测引用）；`state.py` 模块存在 |
| T-702 | LoopKitError exception hierarchy | ✅ 已交付 | `src/loop_kit/exceptions.py`（AGENTS.md 模块清单） |
| T-703 | LoopPaths 全局路径重构 | ✅ 已交付 | `src/loop_kit/paths.py`（LoopPaths、路径助手）；lane 分支 `loop/T-703/r1/lane_core` |
| T-704 | knowledge 治理（去重/版本化） | ✅ 已交付 | `cmd_knowledge_dedupe`/`cmd_knowledge_prune`（_core.py:5963/:5972）；`knowledge.py`；lane 分支存在 |
| T-705 | 真实子进程 round-trip 集成测试 | ✅ 已交付（超集） | 真实子进程回放测试（#3155 T2.3 HistoricalReplay 等）+ `pytest -m e2e` 套件（卡片文件从未创建） |
| T-706 | 文件锁并发安全测试 | ✅ 已交付（超集） | #3155 repo 锁测试组（TestRepoLockPath / TestAcquireRepoLock / TestRepoLockPidRecord / TestCmdRunRepoLock；commit `f689c18` 等） |
| T-707 | 配置系统（env + YAML） | ✅ 已交付 | `src/loop_kit/config.py`（RunConfig、`_load_env_config` LOOP_* 族、YAML 加载与校验） |
| T-708 | feed 事件 dataclass 类型化 | ✅ 已交付 | `FeedEvent`（_core.py:620，pm3263 计划 I5 实测引用）；旧表 T-626 亦标 done |
| T-709 | session 管理整合 | ✅ 已交付 | `src/loop_kit/session.py`（SessionManager、resume policy） |
| T-710 | `loop knowledge` CLI 子命令 | ✅ 已交付 | `sub.add_parser("knowledge", ...)`（_core.py:15217）+ cmd_knowledge_list/add/prune/dedupe/benchmark/search/stats/reindex（:5916-:6156） |
| T-711 | GitHub Action CI/CD | ✅ 已交付（超集） | `.github/workflows/` CI 矩阵（含 Windows compat 硬门，#3617 / v0.8.1）（卡片文件从未创建） |
| T-719 | （T-720 前置，索引未建卡） | ➖ 无卡片 | 仅被旧表引用；历史批次，不追溯 |
| T-720 | Phase1 quick wins（diff/report/config validation/atomic writes） | ✅ 已交付 | `_atomic_write_text`（fsync@_core.py:5710）、config validation（config.py）；lane 分支 `loop/T-720/r1/lane_core` |
| T-721 | 表驱动状态机重构 | ✅ 已交付 | `src/loop_kit/state.py`（state machine、transitions、状态 I/O）；lane 分支存在 |
| T-722 | orchestrator 模块化 | ✅ 已交付 | AGENTS.md 明示 "T-722 modularization"；11 个模块实测存在（_core/exceptions/paths/state/file_bus/dispatch/session/config/prompts/knowledge/git_helpers + orchestrator facade） |
| T-723 | 任务依赖 DAG + blocked 可见性 | ✅ 已交付 | card/lane `depends_on` DAG 校验（_core.py:9237-9403）、依赖图遍历（:9658-9680）、`status --tree`（:15139）（卡片文件从未创建） |
| T-724 | 关键词知识检索（prompt 压缩） | ✅ 已交付 | `src/loop_kit/knowledge.py`（FTS 关键词检索）；cmd_knowledge_search/reindex |

> 8 张 0 字节空卡（T-703/704/706/710/720/721/722/724）为占位残留，已移入 `archive/`（保持 0 字节原样，结论以本表为准）；
> T-701/702/705/707/708/709/711/723 的卡片文件**从未存在**，仅旧索引引用，无实物可对账。

## 独立卡片裁决（2026-10-13，用户授权 D-a/D-b）

| 卡片 | 裁决 | 理由 |
|------|------|------|
| dsh-pilot-T4 | 🗄 obsolete（不合并） | dsh 后端已由 PM #3379 产品化（fallback chain 落地 master）；fib 基准交付物滞留 `bench/opencode-5-25729`（`e6006fb`），分支保留作 benchmark 记录 |
| dsh-pilot-T5-lanes | 🗄 归档（原 status=done） | 已完结试点 |
| E2E-1PLUS1 | 🗄 cancelled（原 blocked） | 冒烟职责由 `pytest -m e2e` 承担；如需全链路真派发验证，待 PM #4349 派发闸门修复后另建卡 |

## 旧 "T-6xx Existing Tasks" 表（历史快照，仅存档语义）

T-601~T-627 均已 done（原表内容不再维护，见 git 历史）。
T-628（Session warm opencode，原标 🔄 In Progress）：对账结论 = **superseded** ——
未发现按原卡命名的独立实现（grep `session_warm|_warm_session` 0 命中）；warm session 机制已由
`session.py`（SessionManager / resume policy）+ warm session prompt 路径（_core.py:7063-7095）
通用化交付。不重排。

## How to Use（现行流程）

新任务经 PM 系统建卡 → auto 派发。手动调试单卡时仍可用：

```bash
uv run python -m loop_kit run --task <card.json>        # 手动跑单卡
uv run python -m loop_kit status --tree                 # 查看依赖树与 blocked 原因
```

Lane 校验规则（depends_on / owner_paths / lane_id 唯一性）见 AGENTS.md 与 `_validate_task_card_contract`。
