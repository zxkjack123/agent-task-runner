---
plan_id: pm3263-watchdog-context-budget-plan-patch
pm_task: 3263
project: agent-task-runner
scope_mode: HOLD
git_commit: fce570e
generated_at: 2026-09-03
revision: 3
execution_mode: manual（人工执行，不创建 auto 标签任务，不让 ATR 自动派发对本仓自身的修改）
linked_spec: 无（修改 ≤5 文件、1 核心模块、无外部 API 破坏性变更，未触发 spec-first；与 #3155 先例一致）
---

# Plan: 会话上下文预算与超时 watchdog + plan patch 执行约束（PM #3263）

## 背景与目标

- **需求**（PM #3263 原文要点）：最近 14 天 session 审计发现 task-executor 126 次、平均 87.3 min，52 次超 15 min；#3155 计划修订会话 3 次约 21.6/21.8 min 超时。根因之一是局部修订复用大上下文，执行侧缺少统一的预算/超时/降级观测。需在 agent-task-runner（仅本仓）内：① 记录现有 timeout/retry/token 边界；② 增加可观测 execution budget/watchdog（任务模式、起止、tool wait、token/cache 指标、超时原因、重试次数）；③ 确定性失败 fail-fast（dirty worktree、repo lock conflict 已有，补 plan patch contract violation）；④ plan patch 声明式白名单约束，禁止通用任意 diff，失败 fail-closed；⑤ 超时/超预算结构化事件与 summary 输出；⑥ 设计（不实现）与 copilot-agents revision_disposition 的最小接口契约。
- **适配复核吸收**（FIT-WITH-UPDATES/HIGH，全部落入本计划）：
  - #3155 已完成 dirty-tree fail-fast（commit eb5e6e6）、repo lock（98677dd..f689c18）、历史回放清理——**本计划零重复实现**，仅引用其测试；「进程组收割」经 CT-1 实测为 f689c18 的**测试层复核**（源码无 killpg），本计划不引用不实现（见 D2 事实更正）；
  - 真实缺口实测确认：`grep watchdog / plan_patch / task_mode` 在 `src/loop_kit/` 源码 0 命中；token 观测仅有 `_normalize_token_usage`（:4722）；
  - 扩展而非重写：`_is_permanent_dispatch_error`（:3003）、`_retry_budget_fields`（:2780）、repo lock 组（:1336-1407）；
  - copilot-agents 无 `revision_disposition` 符号，本仓 `src/ docs/` grep 亦 0 命中——接口契约只在 ATR 自有模块/文档提出；
  - #3135 已提交（fce570e）：worker prompt 含 SKILL LOADING 段 + 物化 `.loop/templates/worker_prompt.txt`（git-tracked）——本计划不改该模板文件；
  - 基线：HEAD=fce570e、tracked 干净、untracked 6 项（生成时快照：4 个旧计划文件 `biweekly-reporting-restore-2026-08-27.md` / `pm3135-worker-prompt-skill-loading.md` / `pm3155-repo-mutex-lock-fixforward-o1.md` / `pm3155-repo-mutex-lock.md` + `data/` + 本计划文件自身）、无活跃 loop、repo lock 空闲、测试基线 677 passed/1 skipped/3 deselected。**计数为生成时快照，非执行期不变量**：执行期 untracked 以 Phase 0 实测 `git status --porcelain` 全量输出为动态基线（见 Phase 0 第 2 步），不得硬编码固定数字断言。
- **目标**：在 `src/loop_kit/_core.py` 内以「追加字段 + 新函数 + 新事件」方式交付：会话级 wallclock 预算 watchdog、上下文 token 台账、plan patch 声明式契约（渲染 + 后置验证 + fail-closed）、任务模式观测、ATR 自有 revision_disposition 契约文档、历史案例回测。
- **非目标（不做什么）**：
  - ❌ 不修改 project_management 调度器、copilot-agents 任何文件；
  - ❌ 不触碰 `.loop/` 运行态（lock/state/runtime/archive）、`data/`、既有 untracked 计划文件；
  - ❌ 不重写 #3155 的 repo lock / dirty-tree fail-fast（只调用其既有函数）；不引入 killpg/进程组信号杀（新设计不在本计划范围，见 D2）；
  - ❌ 不改 `DEFAULT_WORKER_PROMPT_TEMPLATE` 静态文本与 `.loop/templates/worker_prompt.txt`（plan patch 契约走动态渲染段，保护 #3135 字节级验收）；
  - ❌ 不实现跨机/分布式锁；不新增持久化格式（只加可选字段）；
  - ❌ 不运行任何 `loop run`；不启动 ATR 自动派发本计划自身（执行者 = 人工）。

## 需求分解（CoT Stage 1）

```
REQUIREMENT: 会话上下文预算与超时 watchdog + plan patch 执行约束（PM #3263 六条范围）
CONSTRAINTS:
  - 单仓：仅 /home/gw/opt/agent-task-runner；单核心模块：src/loop_kit/_core.py
  - 既有机制扩展：feed 事件流（feed.jsonl）、retry budget、permanent-error 分类、token 归一化、task card 契约校验
  - 多轮执行跨越 --single-round 子进程 → 跨进程状态必须走 state.json（AGENTS.md 单一事实源），禁止新增 CLI 参数（Windows 8191 stdin 契约）
  - Windows 兼容：进程终止只用 subprocess.terminate()/既有路径，不引入 POSIX 信号；os.name == "nt" 分支（:43/:1242/:1249/:4995）不动
  - daemon warn_only 语义不变（cmd_run daemon_mode 路径冻结）
  - 每个 task ≤3 文件；同文件（_core.py / test_orchestrator.py）任务强制串行（#3155 R1-1 教训）
BOUNDARY:
  - IN: RunConfig 新字段、task card 新键（mode/plan_patch，NotRequired）、feed 新事件常量、summary.json 新增 budget 块（可选键）、state.json 新增可选 session_deadline_at、新函数 _verify_plan_patch_scope、docs/design/revision-disposition-contract.md（新文件）
  - OUT: DEFAULT_WORKER_PROMPT_TEMPLATE、.loop/templates/worker_prompt.txt、repo lock 组、_LoopLock、_enforce_clean_worktree_or_exit、daemon 路径、copilot-agents、project_management、.loop/ 运行态、data/、untracked 旧计划
ACCEPTANCE（二元，PM #3263 验收条件映射）:
  1. 超时/预算/确定性失败事件各有 ≥1 单元测试（T1.2/T1.3/T2.3/T3.3）
  2. dirty worktree、repo-lock conflict 既有 fail-fast 测试仍通过（不回退 #3155）；plan patch violation 不重试（新）
  3. patch 模式越界修改被拒绝 + 明确错误 + 测试（T2.3 用例 1/2）
  4. 运行记录可区分 timeout / tool wait / context budget / permanent failure（feed timeout_class + summary budget 块）
  5. uv run --group dev pytest 0 failed；uv run ruff check src/loop_kit tests 0 error
  6. .loop/templates/worker_prompt.txt 与 DEFAULT_WORKER_PROMPT_TEMPLATE 字节级一致（#3135 保护）
```

## T2 影响面分析（本计划核心交付物之一）

| # | 影响面 | 现状（实测锚点） | 本计划动作 | 风险等级 |
|---|--------|------------------|-----------|---------|
| I1 | 配置模型 | `RunConfig`（_core.py:592-617）、`_KNOWN_CONFIG_KEYS`（:514-539）、`_load_env_config`（:8895，LOOP_* 前缀）、`_validate_run_config` | 追加 4 字段（session_timeout_sec / context_token_budget / context_token_warn_pct / 复用 dispatch_timeout 语义），env 3 个 LOOP_* 变量 | Low |
| I2 | 超时执行点 | `_collect_streamed_process_output`（:2847，deadline+terminate）、`_run_auto_dispatch`（:3115）、`DispatchTimeoutError`（:543）、EXIT_TIMEOUT=2（:445） | watchdog 是**会话级**新维度：挂点在 `cmd_run`（:12692 区）/`_run_multi_round_via_subprocess`（:12339）/`_run_single_round`（:11196）；每次 dispatch 前检查剩余预算 | Medium（子进程边界） |
| I3 | 重试/永久失败分类 | `_is_permanent_dispatch_error`（:3003）+ `_PERMANENT_DISPATCH_PATTERNS`（:2994）、`_retry_budget_fields`（:2780）、attempt 循环（:3170-3560，:3536 永久检查） | 扩展分类概念：新增 plan-patch 结构违规 = 永久失败（非 stderr 模式，走独立检查路径）；新增 `timeout_class` 字段 | Medium |
| I4 | token/成本观测 | `_normalize_token_usage`（:4722）、`_runtime_cost_and_token_fields`（:4773）、`_enrich_work_report_runtime_fields`（:4797）、定价表（:410） | 台账化：父进程按轮累计 input/output/total_tokens + prompt_chars 代理 + 预算对比事件 | Low |
| I5 | 事件流 | FEED_* 常量（:379-394）、`FeedEvent`（:620）、`_feed_data`（:1493，**extra 透传**）、`_feed_event`（:1565）、`_emit_event`（:1119，events.jsonl） | 新增 5 个事件常量；`task_mode` 走 `_feed_data` extra 透传（**不与既有 `mode=DISPATCH_BACKEND_NATIVE` 键冲突**，:2825/:3298） | Low |
| I6 | summary.json | `_write_round_summary`（:1062）、run 级 summary 写入（:1105 `resolved_paths.summary.write_text`）、路径 LoopPaths.summary（:561） | 追加可选 `budget` 块（纯新增键，向后兼容，不 bump 版本） | Low |
| I7 | 跨进程状态 | state.json 单一事实源；`_default_state`/`_save_state`（`_core.py` :6628/:6718 定义，state.py 仅 re-export）；`_migrate_state_schema`（:6638，passthrough dict 拷贝，未知键透传——本会话实测）；**`_STATE_CMP_KEYS` 短路（:6731-6738）为真实拦路点**；#3155 进程组收割（f689c18，仅测试层） | 新增可选 `session_deadline_at`（epoch float）；**`_STATE_CMP_KEYS` 追加该键**（否则 deadline-only 变更被短路丢弃，见 T1.2） | **Medium→High（已识别为 T1.2 必改项）** |
| I8 | task card 契约 | `TaskCard` TypedDict（:229-238，total=False）、`_validate_task_card_contract`（:8273，25d4ccf 引入的加载期强校验）、`_load_task_card_or_raise`（:8305） | 追加 `mode`/`plan_patch` NotRequired 键 + 契约校验扩展（patch 模式无契约 → fail-closed ConfigError） | **High**（误收严会拒掉全部旧卡——total=False + 仅对显式出现的键校验） |
| I9 | prompt 渲染 | `_worker_prompt`（:6275 读物化文件）、`_render_task_card_section`（:5783）、`_write_template_if_missing`（:9303，只缺省写入）、`DEFAULT_WORKER_PROMPT_TEMPLATE`（含 SKILL LOADING） | plan patch 契约段**动态**追加进 task card 段渲染输出；模板文件与静态文本零改动 | Medium（#3135 回归） |
| I10 | 任务模式来源 | task card 字段（上游写 task_card.json 传入，`_sync_task_card_to_bus` 链路） | `mode` ∈ {generate, patch, revise, rebuild}，缺省 generate，非法值 ConfigError | Low |
| I11 | 越界保护 | copilot-agents / project_management / `.loop/` 运行态 / `data/` | 全部 OUT；revision_disposition 只写 ATR 自有契约文档 | **High**（红线） |

**影响面结论**：修改面收敛为 `src/loop_kit/_core.py`（追加式）+ `tests/test_orchestrator.py`（追加式）+ `orchestrator.py` facade ownership map（1 处）+ `git_helpers.py`（`__all__` 同步，T3.1 收口）+ 1 个新文档文件；**零** 现有函数重写，**零** 持久化格式破坏。⚠️ 实测更正：`_SECTION_OWNERSHIP_MAP` 在 `_core.py`（:259-269）与 `orchestrator.py`（:32-42）**均无** `"git_helpers"` 条目（仅 `_SECTION_MODULE_PATHS` :55 有路径条目；且 orchestrator.py 的 map 在 facade import 时会整体覆盖 `_core_module` 的同名 map——两处必须同步追加，rev 2 的「条目已存在」断言为误）。

## 假设枚举（CoT Stage 2）

1. `[假设: 上游通过 task card 的 mode/plan_patch 键传入任务模式与 patch 契约]` — 依据：task card 是既有输入通道（`_load_task_card_or_raise` :8305），PM notes 明言「如上游传入」。若上游最终改用其他字段名，仅影响 T2.1 的键名常量，低影响；本计划同时把契约写进 `docs/design/revision-disposition-contract.md` 供上游对齐。
2. `[假设: 会话级 deadline 经 state.json 传递可行且不破坏既有状态迁移]` — **本会话已升级为源码实证**：`_migrate_state_schema`（:6638-6651）是 passthrough dict 拷贝，未知可选键透传不丢；`_validate_state_transition_residue`（:6771）只查 required/forbidden 显式键，不拒绝未知键 → 可选键兼容性在源码层已确认。**真正的拦路点是 `_save_state` 的 `_STATE_CMP_KEYS` 短路**（:6731-6738：10 个比对键全等即 return 不落盘，`session_deadline_at` 不在其中 → deadline-only 变更会被静默丢弃）→ 已把「`_STATE_CMP_KEYS` 追加 `session_deadline_at` + 定向测试」写入 T1.2 必改项（非可选）。T1.2 首步仍保留读校验逻辑复核（belt-and-suspenders，不再标注 High-impact-if-wrong）。若首步发现任何与上述不符 → 降级方案不变（父进程内存 deadline，子进程仅上报，精度降为轮粒度），并 commit message 记录降级事实。
3. `[假设: token 台账以 work report 的 token_usage 为准，缺失时用 prompt_chars 代理]` — 依据：`_runtime_cost_and_token_fields` 已在 work report 归一化 token；codex/claude 输出结构不可控时代理值保持台账连续。若上游事件流已有更精确 token 上报（backend parse_event_fn），执行时可扩展，不影响本计划骨架。
4. `[假设: plan patch 验证基于 git diff（HEAD 基线 + 未跟踪新文件检查）已足够]` — 依据：`_MAX_DIFF_CHARS`（:513）、`_git_at` 既有 git 通道；worker 运行于本仓 worktree，git diff 是确定性事实源。若未来出现非 git 场景，验证器降级为「无基线 → fail-closed 拒绝 patch 模式」，符合 fail-closed 原则。
5. `[假设: 不修改 DEFAULT_WORKER_PROMPT_TEMPLATE 即可满足「任何 prompt 改动须保持 SKILL LOADING 段并刷新物化模板」]` — 依据：本方案不改静态模板（动态段注入 `_render_task_card_section` 输出），物化文件零改动，#3135 的字节级验收自动保持。若审阅认为契约段应进静态模板，则需重物化 worker_prompt.txt——本计划 D4 明确拒绝该替代并给理由。
6. `[假设: 执行者人工执行期间 repo 无并发提交]` — 依据：适配复核确认无活跃 loop、repo lock 空闲；但执行仍强制 Phase 0 重核（要求 9）。若漂移，执行者按 REFINE 流程先更新锚点。

## 方案设计（CoT Stage 3 — 关键决策 D1-D8）

### D1 — 预算数据模型与来源

```
DECISION: 4 个新配置字段 + 3 个 LOOP_* 环境变量，沿用既有 config 优先级链（CLI 缺省 → env → YAML → 代码默认）
ALTERNATIVES:
  a) 独立 budget.yaml 配置文件 —— 拒绝：破坏既有单配置文件模型，且 _KNOWN_CONFIG_KEYS/_load_env_config 是既有可扩展通道
  b) 硬编码默认预算 —— 拒绝：PM notes 要求「可配置」
RATIONALE: 与 #3155/#3135 同构——最小追加面。session_timeout_sec=0 表示禁用（默认零行为不变，向后兼容）
RISK: 配置键名与未来上游冲突 → 用 LOOP_SESSION_TIMEOUT / LOOP_CONTEXT_TOKEN_BUDGET / LOOP_CONTEXT_TOKEN_WARN_PCT 前缀隔离
```

- **数据模型**（`RunConfig` 追加，全部默认 0=禁用，零行为漂移）：
  - `session_timeout_sec: int = 0` — 会话 wallclock 预算（0=禁用）
  - `context_token_budget: int = 0` — 跨轮累计 input token 预算（0=禁用）
  - `context_token_warn_pct: int = 80` — 超预算前预警阈值（百分比，仅当 context_token_budget>0 生效）
  - `task_mode: str | None = None` — 观测透传（真正的权威值读 task card `mode` 键，RunConfig 仅作为调试覆盖；见 D5）
- **来源优先级**：task card `mode`/`plan_patch` > RunConfig/env 预算字段。环境变量：`LOOP_SESSION_TIMEOUT`、`LOOP_CONTEXT_TOKEN_BUDGET`、`LOOP_CONTEXT_TOKEN_WARN_PCT`（`_load_env_config` :8895 追加 3 个读取块，沿用 `_coerce_int_config` 模式）。
- **台账模型**：内存累计器（父进程 `_run_multi_round_via_subprocess`）+ 事件流记录；**不新增持久化文件**。token 来源 = work report 的 `input_tokens/output_tokens/total_tokens`（经既有 `_runtime_cost_and_token_fields` :4773 归一）；缺失时用 dispatch 时 `len(prompt)` 字符数代理（记录 `prompt_chars`，明确标注 `token_source: "report" | "proxy"`）。

### D2 — Watchdog 触发点、超时分类、取消/清理

```
DECISION: watchdog = 会话级 wallclock deadline（新维度）+ 既有 per-attempt dispatch/artifact 超时（既有维度），统一进 timeout_class 分类字段
ALTERNATIVES:
  a) 每轮独立 watchdog（复用 dispatch_timeout 放大）—— 拒绝：无法表达「21.6/21.8min 三次会话级超时」历史案例的会话级语义
  b) 引入 watchdog 后台线程轮询 —— 拒绝：与既有 heartbeat 线程机制（:1715）职责重叠，且子进程边界传递复杂
RATIONALE: 检查点式（轮前/attempt 前）deadline 检查最简单、确定性最强、测试可控；跨进程走 state.json
RISK: 子进程不读 deadline 导致父进程杀不掉 → 父进程在 deadline 后无条件执行既有 `proc.terminate()` + `proc.wait(timeout=2)` 终止链（:2922-2924/:12532-12534/:12627-12629 同款模式），子进程自限只是快速路径；**不引入** killpg/进程组信号杀（POSIX-only，与 Windows 兼容及 T1.2 检查项 3 冲突，见下）
```

- **触发点**（4 处检查点，全部为纯函数式「剩余预算 = deadline − now」）：
  - W-1：`cmd_run`（:12692 区）启动时计算 `session_deadline_at = now + session_timeout_sec`，写入 state.json 可选键 `session_deadline_at`（epoch float，四舍五入 3 位）
  - W-2：`_run_multi_round_via_subprocess`（:12339）每轮循环头部：剩余 ≤0 → 发 `FEED_SESSION_TIMEOUT` + 终止子进程 + 退出 EXIT_TIMEOUT=2
  - W-3：`_run_single_round`（:11196）启动时读 state.json `session_deadline_at` 自限（快速路径）
  - W-4：`_run_auto_dispatch`（:3115）attempt 循环（:3170）每 attempt 前检查：剩余 ≤0 → 不发包直接 `DispatchTimeoutError`（复用既有异常链，带 `timeout_class="session"`）
- **超时分类 taxonomy**（新 `timeout_class` 字段，贯穿 feed 与 summary）：
  | timeout_class | 含义 | 判定点 |
  |---|---|---|
  | `dispatch` | 单 attempt 超时（既有） | `_collect_streamed_process_output` timed_out（:2920） |
  | `artifact` | 产物等待超时（既有） | `_wait_for_file` artifact_timeout |
  | `session` | 会话 wallclock 预算耗尽（新） | W-2/W-3/W-4 |
  | `context_budget` | 上下文 token 超预算（新，见 D3） | 台账累计对比 |
  | `permanent_error` | 确定性失败不重试（新归类） | `_is_permanent_dispatch_error` + plan patch violation |
- **取消/清理（真实既有链，本计划只调用不改写）**：终止顺序 = ① `_close_pipe(proc.stdin)`（:2922）→ ② `proc.terminate()`（跨平台，:2923/:2987/:12500/:12532/:12555/:12627 既有模式）→ ③ `proc.wait(timeout=2)` + `contextlib.suppress(OSError/TimeoutExpired)`（:12533-12534/:12556-12557）→ ④ 读线程 join（:2928-2931，stdin 线程 join timeout=5.0）→ ⑤ `_stop_auto_dispatch_heartbeat`（:1705）→ ⑥ lock 释放走既有 finally 链（#3155 B7 已固化）。**daemon warn_only 路径冻结**。
- ⚠️ **事实更正（CT-1 MINOR）**：rev 2 所述「复用 #3155 f689c18 进程组收割」不成立——f689c18 只改 `tests/test_orchestrator.py`（76 行），是对单轮孙进程收割路径的**测试层复核**，源码中**不存在** killpg/进程组信号杀；:1326/:1379 的 `os.kill(pid, 0)` 是锁诊断存活探针，非终止动作，属冻结区不动。**killpg/进程组信号杀 = 新设计，不在本计划范围**：如需保证孙进程收割，须另立设计任务（解决 POSIX-only 与 Windows 兼容冲突、`os.kill`/`signal.` 新行禁用冲突、与检查项 3 的互斥）。本计划坚持最小 scope：watchdog 终止能力与既有 dispatch 超时终止**完全一致**（terminate 直系子进程），孙进程残留维持现状（由既有 dispatch 超时链与 f689c18 复核测试覆盖的行为不变）。
- **Windows 8191 兼容**：零新 CLI 参数（`--single-round` 子进程 spawn 参数不变）；deadline 经 state.json 传递；终止仅用 subprocess.terminate；`os.name == "nt"` 既有分支不动。验收含 Windows 语义单测（monkeypatch `os.name` 不现实 → 改为断言新代码路径不含 `os.kill`/`signal.*` 调用，见 T1.2 检查项）。

### D3 — Context token 台账与超预算信号

```
DECISION: 父进程按轮累计 + 双阈值事件（warn_pct 预警 / 100% 超限）+ summary 落盘标记，纯观测不硬杀
ALTERNATIVES:
  a) 超预算即 terminate —— 拒绝：token 观测是后验的（work report 里），杀掉已完成的轮无意义；硬杀会让「继续/降级/升级」的决策权消失（PM notes 第 5 条要求保留判断空间）
  b) 只在 summary 里记最终值 —— 拒绝：无法支撑「52 次超 15min」这类中途观测
RATIONALE: 观测先行、决策后置，符合 PM notes「便于 PM/上层判断继续、降级新会话还是升级人工」
RISK: token_usage 缺失时台账空转 → proxy 字段 + token_source 标注保证台账连续性
```

- 累计键：`context_input_tokens_observed` / `context_total_tokens_observed` / `context_prompt_chars_observed`（父进程按轮读取 work report/dispatch 结果，复用 `_runtime_cost_and_token_fields`（约 :4773）与 `_normalize_token_usage`（约 :4722）提取；`_write_round_summary` 返回 `None`，不作为 token 累计来源）
- 事件：`FEED_CONTEXT_BUDGET`（每轮后 info：observed/cumulative/budget/warn_pct/exceeded/token_source）；`FEED_CONTEXT_BUDGET_EXCEEDED`（error 级，仅超限时）
- summary `budget` 块字段：`session_timeout_sec / session_elapsed_sec / session_timed_out / context_input_tokens_observed / context_total_tokens_observed / context_budget / context_budget_exceeded / timeout_counts{dispatch,artifact,session} / permanent_failures / retries_total / task_mode`

### D4 — plan patch 契约：渲染方式（动态段注入，不动静态模板）

```
DECISION: 契约段在 _render_task_card_section 输出中按 mode==patch 动态追加，DEFAULT_WORKER_PROMPT_TEMPLATE 与 .loop/templates/worker_prompt.txt 零改动
ALTERNATIVES:
  a) 契约段进静态模板 + 重物化 worker_prompt.txt —— 拒绝：模板改动会把 #3135 字节级验收（V3）卷入本计划，且契约仅 patch 模式触发，静态模板会污染 generate 模式所有 prompt
  b) 新建独立模板文件 plan_patch_contract.txt —— 可接受但过度：契约内容短（白名单列表），_render_task_card_section 动态渲染即可
RATIONALE: 最小面 + #3135 成果零风险；「任何 prompt 改动须保持 SKILL LOADING 段」通过不改模板达成
RISK: 契约段被 LLM 忽略（prompt 注入弱约束）→ 后置验证（D5）是唯一硬闸，prompt 段仅作行为引导，fail-closed 不依赖 prompt 服从
```

- 渲染内容（`=== PLAN PATCH CONTRACT ===` 段，仅 mode==patch 时出现）：声明式白名单原文（allowed_files 逐行、allowed_anchors 逐条 file:line）、「禁止修改任何白名单外文件」「禁止新增文件（forbid_new_files=true 时）」「禁止修改计划文件的其他 section」「违例将被后置校验拒绝且不重试」。
- 契约数据结构（task card `plan_patch` 键，NotRequired）：
  ```yaml
  plan_patch:            # 仅 mode=patch 时允许出现；缺失 + mode=patch → fail-closed
    allowed_files:       # [Required] repo-relative 路径列表（含计划文件自身）
      - ".github/plans/xxx.md"
    allowed_anchors:     # [NotRequired] 计划文件内锚点白名单
      - {file: ".github/plans/xxx.md", line: 120}   # 单行
      - {file: ".github/plans/xxx.md", heading: "Phase 2"}  # 标题节（首现位置起）
    forbid_new_files: true   # [默认 true] 禁止新建白名单外文件
  ```

### D5 — plan patch 后置验证（唯一硬闸，fail-closed）

```
DECISION: worker 完成后、reviewer 派发前，执行确定性 git diff 验证器 _verify_plan_patch_scope；违例 = 永久失败，零重试
ALTERNATIVES:
  a) 仅 prompt 约束（不后置验证）—— 拒绝：无硬闸，越界修改静默通过，违反「禁止通用任意 diff」
  b) 拦截级 git hook —— 拒绝：涉及 .git/hooks 与进程外副作用，超出本仓 loop-kit 边界
RATIONALE: git diff 是确定性事实源；验证器只读（git diff/status），零副作用；违例复用 PermanentDispatchError 语义（:547）→ 不重试
RISK: 验证器误判（diff 语义边界）→ 验证器纯只读 + 对「无基线」（非 git 场景）直接 fail-closed；正常提交不受影响（仅 patch 模式启用）
```

- 验证流程（新函数 `_verify_plan_patch_scope(spec, *, paths) -> PatchVerifyResult`，含 `{ok, matched_files, violations, diff_range}`）：
  1. `git -C ROOT status --porcelain`（既有 `_git_at` 通道）+ `git diff --name-only HEAD` → changed 集合；untracked 文件若不在 allowed_files → violation
  2. changed ⊆ allowed_files，否则逐文件记 violation（含文件路径 + 类型 `file_out_of_scope`）
  3. 对计划文件自身：`git diff HEAD --unified=0 -- <plan>` 解析 hunk 行号（`@@ -a,b +c,d @@`），逐 hunk 与 allowed_anchors 比对（line 精确 / heading 区间）；不匹配 → violation（类型 `anchor_out_of_scope`）；若 allowed_anchors 为空 → 计划文件任何 hunk 改动均 violation（fail-closed）
  4. `forbid_new_files=true` 且出现白名单外新文件 → violation
  5. diff 总字符数超 `_MAX_DIFF_CHARS`（:513）→ 截断 + `diff_range: "truncated"` 标注
- 违例处置：`FEED_PLAN_PATCH_VIOLATION`（error 级，含 violations 全文）+ 抛 `PermanentDispatchError`（复用 :547）+ 新退出码 `EXIT_PLAN_PATCH_VIOLATION = 6`（:443-449 区追加常量）；attempt 循环**不重试**（在 :3536 永久检查同层并入 `plan_patch_violation` 判定，或直接在 worker-complete 处理器抛终态）。通过 → `FEED_PLAN_PATCH_VERIFY`（info，含 matched_files 计数 + diff_range）。
- ⚠️ **exit 6 分层界定（CT-1 MINOR，事实锚点 :12572-12584）**：`EXIT_PLAN_PATCH_VIOLATION = 6` 只在**单轮子进程层**断言——`_run_single_round`（:11196 区）worker-complete 处理器捕获 `_raise_plan_patch_violation` → 发事件 → `sys.exit(6)`。**父进程既有归一不变**：`_run_multi_round_via_subprocess` 对任何非零子进程 rc 走 `_fail_with_state(outcome="single_round_failed", exit_code=EXIT_VALIDATION_ERROR)`（:12577-12584）→ 父进程最终退出码为 **3（EXIT_VALIDATION_ERROR，既有语义，不改）**，违例明细经 feed 事件与子进程 stderr/round summary 上达。父进程侧复核挂点（见 T2.3 ③）**不得** `sys.exit(6)`，只做「子进程 rc==6 → 仅补发一条 info 级复核记录事件（不重复 error 级 VIOLATION），随后沿用既有归一流程 exit 3」。事件去重策略交 CT-2 题 4 终审。
- 注：verifier 不依赖 LLM 输出可信度；prompt 段（D4）只是引导。**禁止任何「通用任意 diff 修复」模式**——没有契约就没有 patch 模式。

### D6 — 任务模式观测（task_mode plumbing）

```
DECISION: task card `mode` 键（generate/patch/revise/rebuild，缺省 generate，非法值 ConfigError）→ feed 事件 `task_mode` 键（与既有 mode="native" 键并存，不冲突）
ALTERNATIVES:
  a) 复用既有 mode 键 —— 拒绝：:2825/:3298 的 mode=DISPATCH_BACKEND_NATIVE 是「派发模式」，语义不同，混用会破坏既有消费者
  b) 模式仅入 summary 不入 feed —— 拒绝：PM notes 要求事件级观测
RATIONALE: _feed_data 是 **extra 透传（:1493-1507），新增 task_mode 键零破坏
RISK: 上游 task card 不带 mode → 缺省 generate，零行为漂移（T2.1 测试锁定）
```

- plumbing 链：`_load_task_card_or_raise`（:8305）→ `_run_multi_round_via_subprocess`/`_run_single_round` → `_run_auto_dispatch(task_mode=...)`（:3115 签名追加 keyword-only 参数）→ FEED_DISPATCH_START/COMPLETE/FAIL 事件 data + `_report_dispatch_result`（:2797 追加 task_mode 参数）→ summary `budget.task_mode`。
- 不新增持久化格式：全部走既有 feed.jsonl + events.jsonl + summary.json。

### D7 — revision_disposition 最小契约（ATR 自有，不碰 copilot-agents）

```
DECISION: 新文档 docs/design/revision-disposition-contract.md 定义 ATR 消费者契约；生产者（上游写 mode/plan_patch 进 task card）显式标注 OUT-OF-SCOPE
ALTERNATIVES:
  a) 在 copilot-agents 侧写契约 —— 禁止（任务红线：不修改 copilot-agents；且其无 revision_disposition 符号，任何「接口应由上层实现」的结论都必须记录而不实现）
  b) 只在代码注释里写契约 —— 拒绝：不可发现、不可审
RATIONALE: 契约文档是 ATR 自有产物，可审可演进；文档明确「copilot-agents 当前无此符号，生产者实现归属上层」，满足 PM notes 第 6 条
RISK: 契约与现实漂移 → 文档头部写明「本契约由 T2.1/T3.2 共同维护，mode 枚举变更须同步改 _validate_task_card_contract」
```

- 文档内容：mode 枚举语义表（generate/patch/revise/rebuild 各字段含义与 ATR 行为差异）、plan_patch 键 schema（同 D4）、fail-closed 规则、消费点列表（feed/summary/verifier）、生产者侧建议（最小实现 = task card 写入 mode 键；无需改动 copilot-agents 现有任何文件）、显式 OUT-OF-SCOPE 声明。

### D8 — 兼容性与冻结区（#3155/#3135 保护）

- **冻结区（本计划任何 task 不得修改）**：`_acquire_repo_lock`/`_repo_lock_path`/`_repo_lock_diagnostic`/`_pid_is_live`/`_cleanup_stale_lock`（:1310-1407）、`_LoopLock`、`_enforce_clean_worktree_or_exit`、`DEFAULT_WORKER_PROMPT_TEMPLATE`、`_write_template_if_missing`（:9303）、daemon warn_only 分支、`.loop/templates/*.txt` 全部文件。
- **回归守卫**：T3.3 全量回归含 `-k "lock or dirty or worktree or prompt or skill"` 定向子集；Post-Exec Verification V 表含 #3135 字节级一致性检查与 #3155 历史回放测试复跑。
- **兼容承诺**：新字段全部可选/默认零值；新事件不影响既有 feed 消费者（追加行）；summary/state 只加可选键。

## 执行计划

> **全局执行纪律**：每 task 独立 commit，message 前缀 `[Plan: pm3263-watchdog-context-budget-plan-patch]`；每个 Phase 首步执行基线漂移重检；任务全部人工执行（**不创建 auto 标签 PM 任务，不让 ATR 自动派发对本仓自身的修改**——避免自举环路）；代码任务同一文件强制串行。

### Phase 0: 基线漂移重检（每个 Phase 首步强制，非独立 task）

**执行时重测**（不得沿用本计划固化数字）：
1. `git rev-parse HEAD` — 期望 `fce570e`；若前进 → `git log --oneline -5` 检查新提交是否触及本计划锚点区域，先更新锚点再动手
2. `git status --porcelain` — **动态基线规则（CT-1 MINOR）**：把本步全量输出**原文保存**（`Phase 0 快照`），后续每个 Phase 首步与 T3.3/M3 终验都以「与快照逐行比对」为唯一权威判定（新增/减少 untracked、出现 tracked 修改 → 先查明来源；他人会话并发修改 → 暂停并记录）。生成时快照（2026-09-03 实测）为 6 项：4 个旧计划文件（`biweekly-reporting-restore-2026-08-27.md`、`pm3135-worker-prompt-skill-loading.md`、`pm3155-repo-mutex-lock-fixforward-o1.md`、`pm3155-repo-mutex-lock.md`）+ `data/` + 本计划文件自身——**该计数只是生成时参考值，不是执行期不变量**，禁止硬编码数字断言（rev 2 的「3 旧计划/5 项」为过时数，作废）
3. `grep -c "watchdog\|plan_patch\|task_mode" src/loop_kit/_core.py` 应=0（防重复开工）；`grep -n "def _validate_task_card_contract\|def _load_task_card_or_raise\|def _run_multi_round_via_subprocess\|def _run_single_round\|def _render_task_card_section" src/loop_kit/_core.py` 重测行号（:8273/:8305/:12339/:11196/:5783）
4. 并发/锁状态：`ls /tmp/loop-kit-repo-locks/ 2>/dev/null` + `ps aux | grep -E "loop_kit|codex|claude" | grep -v grep` — 期望无活跃 loop 与持锁进程
5. 测试基线：`uv run --group dev pytest -q` 期望 677 passed / 1 skipped / 3 deselected（若基线失败 → 先报备，本计划不修非本任务缺陷）
6. `.loop/templates/worker_prompt.txt` 与 `DEFAULT_WORKER_PROMPT_TEMPLATE` 字节级一致性（`uv run python -c "..."` 重测；import 需经 `uv run --project /home/gw/opt/agent-task-runner python`）

### Phase 1: 预算模型 + 会话 Watchdog + Context 台账

#### Task 1.1: 预算配置数据模型与来源
- **目标**：RunConfig 追加 4 字段 + `_KNOWN_CONFIG_KEYS` 注册 + `_load_env_config` 3 个 LOOP_* 环境变量 + `_validate_run_config` 校验，全部默认零值（0=禁用）零行为漂移
- **依赖**：无
- **frontier**：是
- **执行者**：人工（Dev Orchestrator 路由建议）
- **修改内容**：
  - 文件 `src/loop_kit/_core.py`（repo-root 相对：`/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`）：
    - ① `RunConfig` dataclass（执行时重测 :592-617 区）追加：`session_timeout_sec: int = 0`、`context_token_budget: int = 0`、`context_token_warn_pct: int = 80`、`task_mode: str | None = None`（字段注释注明：默认 0=禁用；task_mode 仅调试覆盖，权威源为 task card）
    - ② `_KNOWN_CONFIG_KEYS`（执行时重测 :514-539 区 frozenset）追加 4 个键名（`session_timeout_sec`/`context_token_budget`/`context_token_warn_pct`/`task_mode`）
    - ③ `_load_env_config`（执行时重测 :8895 区）追加 3 个读取块：`LOOP_SESSION_TIMEOUT` → `session_timeout_sec`、`LOOP_CONTEXT_TOKEN_BUDGET` → `context_token_budget`、`LOOP_CONTEXT_TOKEN_WARN_PCT` → `context_token_warn_pct`（沿用既有 `_coerce_int_config` 风格；非空且 strip 后非空才写）
    - ④ `_validate_run_config`（执行时 `grep -n "def _validate_run_config"` 重定位）：追加非负校验（`session_timeout_sec`/`context_token_budget` ≥0）、`context_token_warn_pct` 限幅 [0,100]（越界 → clamp 并 `_log` 警告，不抛错——避免旧配置升级即崩）
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增测试类 `TestBudgetConfig`（3-4 用例，见验收）
- **修改边界**：不得触碰 `_repo_lock_path`/`_acquire_repo_lock`/`_LoopLock`/`_enforce_clean_worktree_or_exit`/`DEFAULT_WORKER_PROMPT_TEMPLATE`/`_write_template_if_missing`/daemon 分支；不得改 `_load_config_from_yaml` 的既有键合并逻辑（只通过 `_KNOWN_CONFIG_KEYS` 注册即被纳入）
- **质量检查方式**：
  - 检查项 1：`grep -n "session_timeout_sec\|context_token_budget" src/loop_kit/_core.py` 出现于 RunConfig/_KNOWN_CONFIG_KEYS/_load_env_config/_validate_run_config 四处
  - 检查项 2：`uv run ruff check --preview --select I001 src/loop_kit/_core.py` 无 import 排序破坏（本 task 不新增 import，理论零命中）
  - 检查项 3：既有 `_warn_unknown_config_keys` 对新键不告警（`_KNOWN_CONFIG_KEYS` 注册生效）
- **验收标准**：
  - ✅ `uv run --group dev pytest -q -k "BudgetConfig"` 全绿；用例覆盖：① env `LOOP_SESSION_TIMEOUT=120` → `_load_env_config()` 含 `session_timeout_sec`；② 负值 → `_validate_run_config` 抛 `ConfigError`（或既有异常类型）；③ `context_token_warn_pct=150` → clamp 100 + 警告路径不抛错；④ 缺省 RunConfig 三字段均为 0/80（零行为漂移锁定）
  - ✅ 全量 `uv run --group dev pytest -q` 保持 677 passed 基线（新旧总数偏差记录在 commit message）
  - ✅ `uv run ruff check src/loop_kit tests` 0 error
- **潜在风险**：`_validate_run_config` 实际函数名/签名与假设不符（若 25d4ccf 后重构）→ 首步 grep 重定位后照实调整，不硬套锚点
- **预留歧义标注**：
  - [x] 无歧义：字段名、env 名、校验语义均已给定

#### Task 1.2: 会话 Watchdog（deadline 检查点 + state.json 传递 + 超时分类 + 清理）
- **目标**：会话级 wallclock 预算在 4 检查点强制；`timeout_class` 字段入 feed；清理复用真实既有 `proc.terminate()`/`wait(timeout=2)` 链（不引入进程组信号杀，见 D2 事实更正）；`_STATE_CMP_KEYS` 追加 `session_deadline_at` 保证 deadline 落盘
- **依赖**：T1.1
- **frontier**：否（依赖 T1.1 的配置字段）
- **执行者**：人工
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    - ① 新常量区（:443-449 EXIT_* 附近）追加：`FEED_SESSION_BUDGET = "session_budget"`、`FEED_SESSION_TIMEOUT = "session_timeout"`（放 FEED_* 常量区 :379-394 附近，字母序插入）
    - ② 新函数 `_session_budget_fields(*, deadline_at: float | None, now: float | None = None) -> dict[str, object]`：返回 `{session_elapsed_sec, session_remaining_sec(≤0 即耗尽), session_timed_out: bool}`（纯函数，时间参数可注入——测试免 monkeypatch）
    - ③ `cmd_run`（执行时重测 :12692 区，repo lock 获取成功之后、`_main_loop` 调用之前）：`session_timeout_sec > 0` 时计算 `session_deadline_at` 并写入 state（`_save_state` 前把可选键并入 state dict）；**必改项（CT-1 MINOR）**：`_save_state`（:6718）的 `_STATE_CMP_KEYS`（:6731-6734，当前 10 键）**追加 `"session_deadline_at"`**——否则 deadline-only 变更在比对键全等时被短路丢弃、永不移盘（本会话源码实证 :6735-6738）。追加向后兼容：旧 state 无该键时 `previous.get(k) is None ≠ 新值` → 正常落盘；无 deadline 的会话行为与今日完全一致。首步仍读 :6638-6651/:6771-6785 复核可选键透传（belt-and-suspenders，见假设 2）；发 `FEED_SESSION_BUDGET`（info）
    - ④ `_run_multi_round_via_subprocess`（:12339 区）轮循环头部：`_session_budget_fields` 判定耗尽 → 发 `FEED_SESSION_TIMEOUT`（error，data 含 `timeout_class="session"`）→ 终止子进程（**复用真实既有链**：`current_proc.terminate()` + `current_proc.wait(timeout=2)`，:12500/:12532-12534/:12627-12629 同款，**不含** killpg/进程组信号杀——源码无此机制，见 D2 事实更正）→ 走既有终态退出（EXIT_TIMEOUT=2）
    - ⑤ `_run_single_round`（:11196 区）启动时读 state `session_deadline_at` 自限（快速路径；读不到则跳过，不报错）
    - ⑥ `_run_auto_dispatch`（:3115 签名追加 keyword-only `session_deadline_at: float | None = None`）attempt 循环（:3170 区）每 attempt 前检查：耗尽 → 不发包，走 `DispatchTimeoutError` 路径（data 记 `timeout_class="session"`）
    - ⑦ `_report_dispatch_result`（:2797 区）追加 `timeout_class: str | None = None` 参数 → data 写入（`dispatch` 为缺省语义；session 检查点传入 `session`）
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `TestSessionWatchdog`（见验收）
- **修改边界**：不得改 `_collect_streamed_process_output` 内部 deadline 逻辑（:2847-2932，既有 per-attempt 超时原样保留）；不得改 `_stop_auto_dispatch_heartbeat`/`_start_auto_dispatch_heartbeat` 实现（只调用）；不得改 state schema 版本与迁移逻辑；不得新增 CLI 参数（`--single-round` 等 spawn 参数原样）；新代码路径不得含 `os.kill`/`signal.`（Windows 兼容，检查项 3 锁定）
- **质量检查方式**：
  - 检查项 1：`grep -n "session_deadline_at" src/loop_kit/_core.py` 出现于 cmd_run 写入 / `_run_single_round` 读取两处
  - 检查项 2：`grep -n "FEED_SESSION_TIMEOUT\|FEED_SESSION_BUDGET" src/loop_kit/_core.py` 常量定义 + 使用点 ≥2
  - 检查项 3：`grep -nE "os\.kill|signal\." src/loop_kit/_core.py` 的**新增行**为 0（diff 审查，冻结既有命中 :1326/:1379 锁诊断探针与 SIGINT/SIGTERM handler 注册）
  - 检查项 4：daemon 分支 `daemon_mode` 相关行 diff 为 0
  - 检查项 5（CT-1 MINOR）：`grep -n "_STATE_CMP_KEYS" src/loop_kit/_core.py` 处元组含 `"session_deadline_at"`；`grep -nE "os\.killpg|killpg" src/loop_kit/_core.py` 零命中（killpg 未引入锁定）
- **验收标准**：
  - ✅ `TestSessionWatchdog` 用例：① `_session_budget_fields` 纯函数边界（耗尽/未耗尽/None deadline=未启用）② attempt 前检查耗尽 → 未产生 Popen 调用（monkeypatch `subprocess.Popen` 计数为 0）且抛 `DispatchTimeoutError` ③ deadline 传递：state 写入后 `_run_single_round` 读取路径（monkeypatch `_load_state`）④ 子进程终止顺序断言（monkeypatch 捕获 terminate 调用序列：stdin 关闭 → terminate → wait）⑤（CT-1 MINOR 新增）`_save_state` 落盘断言：tmp_path 写初版 state → 仅改 `session_deadline_at` 再 `_save_state` → 磁盘 state.json 含新 deadline（短路不丢）；无任何变更再存 → 文件 mtime 不变（既有跳过语义保留）
  - ✅ 历史案例回测（T-3263-a，本 task 内做）：模拟 #3155「3 次约 21.6/21.8min 超时」模式——`session_timeout_sec=1` + 快时钟（`_session_budget_fields(now=...)` 注入），断言第 2 轮 dispatch 被 W-4 拦截、总 Popen 次数 ≤1、feed 事件序列含 `session_budget` + `session_timeout`
  - ✅ `uv run --group dev pytest -q` 0 failed；`uv run ruff check src/loop_kit tests` 0 error
- **潜在风险**：state 可选键被既有校验拒绝（假设 2 已源码降级为低风险——`_migrate_state_schema` passthrough 实证）→ 若首步复核发现不符，降级方案不变（`session_deadline_at` 不写 state，仅父进程内存持有，`_run_single_round` 不读，watchdog 精度降为父进程轮粒度），commit message 记录降级事实；**不得**为通过校验而改 `_migrate_state_schema`。**新风险（CT-1 MINOR）**：`_STATE_CMP_KEYS` 扩展使含 deadline 会话的 `_save_state` 每次 deadline 变化都落盘（写放大）→ 可接受（deadline 每会话仅写 1 次，cmp 短路对无 deadline 会话行为不变）；用例 ⑤ 锁定落盘与跳过双语义。
- **预留歧义标注**：
  - [x] 无歧义：检查点、分类值、降级方案均已给定

#### Task 1.3: Context token 台账与超预算事件
- **目标**：父进程按轮累计 token（work report token_usage + prompt_chars 代理），双阈值事件，summary 可选标记入口预留
- **依赖**：T1.1（预算字段）、T1.2（feed 事件模式先例）
- **frontier**：否
- **执行者**：人工
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    - ① FEED_* 常量区追加：`FEED_CONTEXT_BUDGET = "context_budget"`、`FEED_CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"`
    - ② 新函数 `_context_budget_report(*, observed_input: int | None, observed_total: int | None, prompt_chars: int | None, budget: int, warn_pct: int) -> dict[str, object]`：返回 `{context_input_tokens_observed, context_total_tokens_observed, context_prompt_chars_observed, context_budget, context_budget_exceeded, context_budget_warned, token_source}`（纯函数；budget=0 → exceeded/warned 恒 False）
    - ③ `_run_multi_round_via_subprocess`（:12339 区）轮循环：累计器从父进程已读取的 work report/dispatch 结果提取（复用 `_runtime_cost_and_token_fields`（约 :4773）与 `_normalize_token_usage`（约 :4722）的 `input_tokens/total_tokens` 字段）；`_write_round_summary` 返回 `None`，不得作为 token 来源；每轮后发 `FEED_CONTEXT_BUDGET`（info）；超限发 `FEED_CONTEXT_BUDGET_EXCEEDED`（error，**不终止**——观测先行，决策后置，见 D3）
    - ④ `_run_auto_dispatch`（:3115 区）FEED_DISPATCH_START data 追加 `prompt_chars=len(prompt)`（代理值，token_source="proxy" 标注在台账侧）
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `TestContextBudget`（见验收）
- **修改边界**：不改 `_normalize_token_usage`/`_runtime_cost_and_token_fields` 实现（只调用）；不改 summary 写入函数（:1105 区，属 T3.1）；不新增持久化文件
- **质量检查方式**：
  - 检查项 1：`grep -n "FEED_CONTEXT_BUDGET" src/loop_kit/_core.py` 常量 + 使用点齐全
  - 检查项 2：`grep -n "prompt_chars" src/loop_kit/_core.py` 仅出现在 dispatch 事件 data 与台账函数
  - 检查项 3：diff 审查确认 `_normalize_token_usage` 区域（:4722 区）零改动
- **验收标准**：
  - ✅ `TestContextBudget` 用例：① `_context_budget_report` 纯函数（budget=0 禁用 / 80% warn / 100% exceed / token_source=proxy 分支）② 台账累计两轮（monkeypatch 父进程读取的 work report/dispatch 结果（带 token 字段）→ 累计值断言；不 monkeypatch `_write_round_summary` 返回值）③ 超限发 exceeded 事件且**不抛异常不 terminate**（断言 Popen 序列继续）
  - ✅ 历史案例回测（T-3263-b）：模拟「87.3min 平均长会话」token 增长——3 轮累计 input 越过 budget → 事件序列含 1 次 warn + 1 次 exceeded，且 `context_budget_exceeded=True` 出现在事件 data（供上层决策）
  - ✅ `uv run --group dev pytest -q` 0 failed；`uv run ruff check src/loop_kit tests` 0 error
- **潜在风险**：`_write_round_summary` 返回结构不含 token 键（若 work report 无 token_usage）→ 台账值为 None 走 proxy 标注，测试用例 ② 的 fixture 必须显式给 token 键（已写明）
- **预留歧义标注**：
  - [x] 无歧义

#### Task 1.4: CT-1 审阅门（critical-thinking 委派，零文件修改）
- **目标**：对 Phase 1 三个 commit 的设计做 Socratic 审查，聚焦 4 个指定问题域
- **依赖**：T1.1 + T1.2 + T1.3（三个 commit 落地后）
- **frontier**：否
- **执行者**：人工（执行者委派 `task(subagent_type="critical-thinking")`；空返回防护：重试 1 次，仍空 → 执行者自审并标注 `[DELEGATION-EMPTY: critical-thinking — fallback self-review]`，与 #3155 先例一致）
- **修改内容**：无（纯审阅，产出审阅记录写入本计划「审查日志」表 CT-1 行）
- **审阅问题域（必答 4 题，供委派 prompt 原文使用）**：
  1. 子进程边界：`session_deadline_at` 走 state.json 是否引入竞态（父写子读时机）？`_run_single_round` 读不到时的降级行为是否会造成父进程误杀刚启动的合法子进程？
  2. 预算会计：`prompt_chars` 代理与真实 token 混算是否会产生「预算未超但实际超限」的漏报？（`_context_budget_report` 的 token_source 字段能否支撑上层区分）
  3. daemon 语义：watchdog 在 `daemon_mode=True` 下是否会改变既有的 warn_only/长驻行为？（边界锁定是否充分）
  4. Windows：新路径是否引入任何 POSIX 假设（源码实测无 killpg/进程组信号杀，本计划不新增；`proc.terminate()` 链在 Windows 下的既有行为是否被新挂点破坏）？
- **验收标准**：
  - ✅ 审阅记录含 4 题结论 + 每条 blocking/非-blocking 发现均有处置（折入 T2.x/T3.x 或记录豁免理由）
  - ✅ blocking 发现 >0 时：先补丁任务（追加进本计划并标记 `CT-1-补`）再进 Phase 2；0 时直接进 Phase 2

### Phase 2: Plan Patch 声明式契约（渲染 + 后置验证 + fail-closed）

#### Task 2.1: task card 契约扩展（mode/plan_patch 键 + 校验 + fail-closed）
- **目标**：`TaskCard` TypedDict 追加 `mode`/`plan_patch`（NotRequired）；`_validate_task_card_contract` 扩展：mode 枚举校验、patch 模式无契约 → ConfigError（fail-closed）；**旧卡（无新键）完全通过**
- **依赖**：T1.4（CT-1 门通过；若有 CT-1-补 先执行）
- **frontier**：否
- **执行者**：人工
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    - ① `TaskCard` TypedDict（执行时重测 :229-238 区）追加：`mode: NotRequired[str]`、`plan_patch: NotRequired[dict[str, object]]`
    - ② 新常量：`_TASK_MODES = ("generate", "patch", "revise", "rebuild")`（:232 附近）；`EXIT_PLAN_PATCH_VIOLATION = 6`（:443-449 EXIT_* 区，附注释「plan patch 越界 fail-closed；仅单轮子进程层断言，父进程归一 exit 3 不变」）
    - ③ `_validate_task_card_contract`（执行时重测 :8273 区）**只增不改既有校验**：
      - `mode` 存在且非 `_TASK_MODES` 成员 → 既有 `ConfigError`（含允许值列表；保持 cmd_run 顶层既有 exit 1 语义，不新增异常类型）
      - `mode == "patch"` 且 `plan_patch` 缺失 → 既有 `ConfigError`（fail-closed：patch 模式必须有契约，保持 cmd_run 顶层既有 exit 1 语义）
      - `plan_patch` 存在时结构校验：`allowed_files` 必为**非空** str 列表；`allowed_anchors` 若存在必须为 dict 列表（每项 `file` 必填 str，`line`/`heading` 二选一）；`forbid_new_files` 若存在必须 bool；**任何结构违例 → ConfigError**（fail-closed，宁拒勿放）
      - `mode` 非 patch 而 `plan_patch` 存在 → 允许（契约附带但未激活），记 `_log` info
      - ⛔ 关键不变量：**键缺失 = 校验通过**（`total=False` 语义，旧卡零影响；测试用例 3 锁定）
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `TestTaskCardModeAndPatchContract`（见验收）
- **修改边界**：不得改既有 Required 键（in_scope/acceptance_criteria/constraints）的校验分支；不得改 `_load_task_card_or_raise`（:8305）的加载语义（只消费扩展后的校验）；不得动 `.loop/examples/task_card.json`（既有示例文件保持旧格式，证明旧卡兼容）
- **质量检查方式**：
  - 检查项 1：`grep -n "plan_patch\|_TASK_MODES" src/loop_kit/_core.py` 落在 TaskCard/常量/校验三处
  - 检查项 2：`uv run --project /home/gw/opt/agent-task-runner python -c "from loop_kit.orchestrator import _TASK_MODES, EXIT_PLAN_PATCH_VIOLATION"` 导入成功（命名空间 alias 生效）
- **验收标准**：
  - ✅ `TestTaskCardModeAndPatchContract` 用例：① 旧卡（无 mode/plan_patch）→ 校验通过且 load 成功（**回归锁定**，重放 `.loop/examples/task_card.json`）② `mode="hack"` → ConfigError 且消息含 `_TASK_MODES` 枚举值 ③ `mode="patch"` 无 plan_patch → ConfigError（fail-closed）④ `allowed_files=[]` → ConfigError ⑤ `allowed_anchors` 项同时缺 line/heading → ConfigError ⑥ `mode="revise"` + 合法 plan_patch → 通过
  - ✅ 既有 task-card 契约测试全绿（`uv run --group dev pytest -q -k "task_card or TaskCard"`）
  - ✅ `uv run --group dev pytest -q` 0 failed；`uv run ruff check src/loop_kit tests` 0 error
- **潜在风险**：25d4ccf 契约校验用了白名单键集（未知键报错）而非 TypedDict 宽松读 → 首步读 :8273 全文确认；若存在未知键拒绝逻辑，把 `mode`/`plan_patch` 加入其白名单（同函数内，仍是扩展不重写）
- **预留歧义标注**：
  - [x] 无歧义：枚举、结构、fail-closed 语义均已给定

#### Task 2.2: 契约渲染（动态段注入，静态模板零改动）
- **目标**：`_render_task_card_section` 在 mode==patch 时追加 `=== PLAN PATCH CONTRACT ===` 段；`_worker_prompt` 渲染链路透传 mode；`DEFAULT_WORKER_PROMPT_TEMPLATE` 与 `.loop/templates/worker_prompt.txt` **零改动**
- **依赖**：T2.1
- **frontier**：否
- **执行者**：人工
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    - ① 新函数 `_render_plan_patch_contract(task_card: TaskCard) -> str`：mode!=patch 或 plan_patch 缺失 → 返回 `""`；否则渲染 D4 定义的段落（白名单逐行 `- <file>`、锚点逐条 `- <file>:<line|heading=...>`、`forbid_new_files` 状态、4 条禁止事项与 fail-closed 告知）。**模板化安全**：纯字符串拼接，无 `.format()` 参与（避免 `{}` 冲突）
    - ② `_render_task_card_section`（:5783 区）尾部追加：`contract = _render_plan_patch_contract(task_card)`，非空时附在返回值后
    - ③ `_build_task_packet`（:5622 区）无需改（task_card 段经 `_render_task_card_section` 自动携带契约）——**执行时确认** `_build_task_packet` 确实调 `_render_task_card_section`，若非则把契约段挂进该调用链最近点
    - ④ `_worker_prompt`（:6275 区）**不改签名不改渲染**（契约已随 task_card 段进入）——执行时确认渲染链包含 task_card_section 占位
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `TestPlanPatchContractRendering`（见验收）
- **修改边界**：⛔ 冻结：`DEFAULT_WORKER_PROMPT_TEMPLATE`、`.loop/templates/worker_prompt.txt`、`_write_template_if_missing`、`_render_prompt_template`；`_render_task_card_section` 的既有输出段（goal/in_scope/.../constraints）原样保留，契约段只追加
- **质量检查方式**：
  - 检查项 1：`grep -n "PLAN PATCH CONTRACT" src/loop_kit/_core.py` 仅 1 处（渲染函数内），且模板文件与 DEFAULT 常量区 0 命中
  - 检查项 2：`git diff -- .loop/templates/worker_prompt.txt` 为空
  - 检查项 3：`uv run --project /home/gw/opt/agent-task-runner python -c "...DEFAULT_WORKER_PROMPT_TEMPLATE 与文件字节级比较..."` 一致（#3135 V3 复验）
- **验收标准**：
  - ✅ `TestPlanPatchContractRendering` 用例：① mode=patch + 契约 → 渲染含 `=== PLAN PATCH CONTRACT ===` 与 `allowed_files` 各条目 ② mode=generate（契约存在）→ 渲染**不含**契约段 ③ 无契约 → 空串 ④ 渲染输出含 `forbid_new_files` 状态行 ⑤ 契约文本无 `{`/`}`（防后续 format 冲突断言）
  - ✅ #3135 既有测试复绿：`uv run --group dev pytest -q -k "skill or worker_prompt"`（含 `test_worker_prompt_rendered_includes_skill_loading`）
  - ✅ `uv run --group dev pytest -q` 0 failed；`uv run ruff check src/loop_kit tests` 0 error
- **潜在风险**：`_worker_prompt` 实际渲染链不含 task_card 段（假设 3 变体）→ 执行时 grep `_render_task_card_section` 调用点确认，最多把契约挂进 `_render_task_packet_section` 相邻点（仍不改模板）
- **预留歧义标注**：
  - [x] 无歧义

#### Task 2.3: 后置验证 `_verify_plan_patch_scope`（唯一硬闸）
- **目标**：worker 完成后、reviewer 前执行确定性 git 校验；违例 → `FEED_PLAN_PATCH_VIOLATION` + `PermanentDispatchError` + EXIT_PLAN_PATCH_VIOLATION=6，**不重试**；通过 → `FEED_PLAN_PATCH_VERIFY`（含匹配数与 diff_range）
- **依赖**：T2.2
- **frontier**：否
- **执行者**：人工
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    - ① FEED_* 常量区追加：`FEED_PLAN_PATCH_VERIFY = "plan_patch_verify"`、`FEED_PLAN_PATCH_VIOLATION = "plan_patch_violation"`
    - ② 新函数 `_verify_plan_patch_scope(spec: dict[str, object], *, paths: LoopPaths | None = None) -> dict[str, object]`（D5 五步流程；返回 `{ok: bool, matched_files: list[str], violations: list[dict], diff_range: str}`）：
      - 用既有 `_git_at(ROOT, "status", "--porcelain")` + `_git_at(ROOT, "diff", "--name-only", "HEAD")` 取 changed 集（git 调用失败 → fail-closed：ok=False + violation `{type: "git_unavailable"}`）
      - `git diff HEAD --unified=0 -- <plan_file>` 逐 hunk 解析（正则 `^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@`，diff 超 `_MAX_DIFF_CHARS` 截断记 `diff_range: "truncated"`）
      - 锚点比对：`line` 精确 ∈ hunk 行区间；`heading` 需先定位计划文件中该标题行号（`read_text` 后逐行匹配 `# heading`，首现），hunk 区间与标题起始行距离 ≤ 上下文窗口（**窗口 = 标题起始行至下一同级标题**，实现从简：允许标题行 ±200 行内；计划中注明简化边界）
      - **allowed_anchors 为空 → 计划文件任何改动均 violation**（fail-closed 核心）
    - ③ 挂点：`_run_single_round`（:11196 区）worker 完成处理器（work report 落盘后、reviewer 派发前）；`_run_multi_round_via_subprocess`（:12339 区）对应父进程位置同样挂载（单轮子进程路径以子进程内验证为准，父进程以子进程返回码为准——两处都挂，双保险）。仅 `mode == "patch"` 时启用；mode 从 state/task card 传入
    - ④ 违例处置函数 `_raise_plan_patch_violation(result: dict) -> NoReturn`：发 `FEED_PLAN_PATCH_VIOLATION`（error，data 含 violations 与 diff_range）→ `raise PermanentDispatchError(f"plan patch contract violated: ...")`（复用 :547）。**不进入重试**：violation 发生点必须在 attempt 重试循环**之外**（轮级 worker-complete 处理器），与 :3536 永久检查同层语义。**exit 6 分层（CT-1 MINOR）**：仅 `_run_single_round` 子进程层捕获后 `sys.exit(EXIT_PLAN_PATCH_VIOLATION)`；父进程侧复核挂点（③）**不** exit 6——子进程 rc==6 时仅补发 info 级复核记录事件（不重复 error 级 VIOLATION），随后沿用既有归一流程：`_fail_with_state(exit_code=EXIT_VALIDATION_ERROR)` → 父进程 exit 3（:12577-12584 既有语义，零改动）。详见 D5 分层界定
    - ⑤ ownership map + facade（CT-1 MINOR 实测更正：`_SECTION_OWNERSHIP_MAP` 在 `_core.py` :259-269 与 `orchestrator.py` :32-42 **均无** `"git_helpers"` 条目——只有 `_SECTION_MODULE_PATHS` :55 有路径条目；且 orchestrator.py 的 map 在 facade import 时整体覆盖 `_core_module` 同名 map，故**两处必须同步追加**，rev 2「条目已存在」为误）：
      - (a) `_core.py` `_SECTION_OWNERSHIP_MAP` 追加新条目 `"git_helpers": ("_git", "_git_at", "_verify_plan_patch_scope")`（最小事实集：新函数 + 其直接消费的既有 git 通道；不声称囊括全部 git 符号）
      - (b) `orchestrator.py` `_SECTION_OWNERSHIP_MAP`（:32-42）追加**同一条目**（与 _core.py 逐字一致，防双 map 漂移扩大化；注意其 "lock" 节已与 _core.py 漂移，本 task 不动该既有漂移，只在审查日志记录）
      - (c) `git_helpers.py` 的显式 import 列表 + `__all__` 追加 `_verify_plan_patch_scope`（**移入 T3.1**，保本 task ≤3 文件；I001/RUF022 定向门禁同 T3.1）
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/orchestrator.py`：仅 ownership map (b) 一行条目追加，**不得**改 module alias（:58-61）、docstring、`_SECTION_MODULE_PATHS`
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `TestPlanPatchVerify`（见验收）
- **修改边界**：不得改 `_git_at` 实现；不得改 reviewer 派发逻辑（只在之前插检查）；不得触碰 #3155 dirty-tree fail-fast（其检查仍在，本验证是**增量**：dirty-tree 先于 patch 验证）；**本 task 恰好 3 文件**（`_core.py` + `orchestrator.py` + `tests/test_orchestrator.py`；`git_helpers.py` 的 `__all__` 同步拆至 T3.1，不突破 ≤3 文件规则——拆分方案已定，不留「4 文件预算」选项）；不修改 `_core.py` 中既有 `"lock"`/`"file_bus"` 等 map 条目
- **质量检查方式**：
  - 检查项 1：`grep -n "_verify_plan_patch_scope" src/loop_kit/_core.py` 定义 + 挂点 ≥2
  - 检查项 2：`grep -n '"git_helpers": (' src/loop_kit/_core.py src/loop_kit/orchestrator.py` 两文件 ownership map 各 1 命中且条目逐字一致（`diff <(grep ...) <(grep ...)` 或目视比对）
  - 检查项 3：diff 审查确认 reviewer 派发点之前存在验证调用（顺序：worker 完成 → 验证 → reviewer 或子进程 exit 6）；父进程复核挂点处**无** `sys.exit(EXIT_PLAN_PATCH_VIOLATION)` 调用（exit 6 仅子进程层，grep `sys.exit(EXIT_PLAN_PATCH_VIOLATION)` 命中点必须位于 `_run_single_round` 域内）
- **验收标准**：
  - ✅ `TestPlanPatchVerify` 用例（tmp_path 伪 git 仓，沿用既有 `git init -q` 套路）：① 白名单内改动（allowed_files 全命中、锚点命中）→ ok=True + `matched_files` 正确 + `FEED_PLAN_PATCH_VERIFY` 发出 ② 白名单外文件被改 → ok=False + violation 含 `file_out_of_scope` + 事件为 VIOLATION ③ 计划文件改到锚点外行 → `anchor_out_of_scope` ④ 白名单外**新文件**（untracked，forbid_new_files=true）→ violation ⑤ allowed_anchors 为空 + 计划文件被改 → violation（fail-closed 核心用例）⑥ `_raise_plan_patch_violation` 抛 `PermanentDispatchError` 且**Popen 计数无新增**（不重试断言）⑦（CT-1 MINOR 新增）exit 分层：`_run_single_round` 域内捕获后 exit 码 == 6；父进程复核路径（`_run_multi_round_via_subprocess`）对 rc==6 的子进程仅补发 info 级复核事件且自身 exit 路径走 `EXIT_VALIDATION_ERROR`=3（monkeypatch `_fail_with_state` 捕获 exit_code 参数断言）
  - ✅ 历史案例回测（T-3263-c，本 task 内）：模拟 patch 模式 worker 越界改 `src/loop_kit/dispatch.py` → 验证器拒绝 + **子进程层** exit 码语义 6 + feed 事件含 violations 明细（断言 violation 消息含文件路径）；**父进程层**断言归一 exit 3（不声称 6 上浮）
  - ✅ 正常 generate 模式完全不受验证器影响（mode!=patch 断言验证器未被调用）
  - ✅ ownership map 双文件一致性检查（检查项 2 命令）通过；`uv run --project /home/gw/opt/agent-task-runner python -c "from loop_kit.orchestrator import _verify_plan_patch_scope"` 导入成功（facade alias 生效）
  - ✅ `uv run --group dev pytest -q` 0 failed；`uv run ruff check src/loop_kit tests` 0 error
- **潜在风险**：heading 锚点窗口 ±200 行过宽 → 计划中显式标注为「v1 简化边界」，CT-2 必审（题 2）；git diff 无 HEAD（首 commit 仓）→ fail-closed 分支已定义；`_run_multi_round_via_subprocess` 父进程侧挂点若重复计算（子进程已判）→ 父侧以子进程返回码为准，仅复核（幂等）
- **预留歧义标注**：
  - [x] 无歧义：五步流程、违规类型、挂点、退出码均已给定

#### Task 2.4: CT-2 审阅门（critical-thinking 委派，零文件修改）
- **目标**：对 plan patch 契约链路（T2.1-T2.3）做 Socratic 审查
- **依赖**：T2.1 + T2.2 + T2.3
- **frontier**：否
- **执行者**：人工（委派 + 空返回防护同 T1.4）
- **审阅问题域（必答 4 题）**：
  1. fail-closed 边界：`allowed_anchors` 为空即全拒是否会让「只改计划文件文字描述」的合法 patch 场景不可用？（若不可用，替代方案是要求 heading 级锚点，权衡记录）
  2. 验证器绕过路径：worker 能否通过「先改后还原」/「git stash」/「submodule」/「.gitignore 隐藏」绕过 `git status --porcelain` 检查？（逐条评估 + 残余风险声明）
  3. heading 窗口 ±200 行：误放概率与误拒概率的取舍是否合理？（给出建议窗口或更精确算法：标题至下一同级标题）
  4. 双挂点（父/子进程）幂等性：子进程 exit 6 后父进程复核是否会产生重复事件/错误覆盖？（事件去重策略）
- **验收标准**：
  - ✅ 审阅记录含 4 题结论；blocking 发现折入 T3.1/T3.3（标记 `CT-2-补`）或记录豁免理由
  - ✅ 审阅明确声明「不存在绕过 verifier 且不留 git 痕迹的已知路径」（或有残余风险声明）

### Phase 3: 观测汇总 + 契约文档 + 历史回测收口

#### Task 3.1: summary budget 块 + task_mode 全链路 plumbing + git_helpers facade 同步
- **目标**：run 级 summary（:1105 写入点所属函数）追加可选 `budget` 块；`task_mode` 从 task card 一路透传到 feed 事件与 summary；`git_helpers.py` 的 `_verify_plan_patch_scope` 显式 import + `__all__` 同步（T2.3 拆入，保每 task ≤3 文件）
- **依赖**：T2.4（CT-2 门通过；CT-2-补 先执行）
- **frontier**：否
- **执行者**：人工
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    - ① run 级 summary 写入函数（执行时 `grep -n "resolved_paths.summary.write_text"` 重定位，:1105 区）：payload 追加 `budget` 块（D3 定义字段；**仅当** session_timeout_sec>0 或 context_token_budget>0 或 task_mode 非空时写入该块——纯新增可选键，向后兼容）
    - ② `_run_auto_dispatch`（:3115 区）与 `_report_dispatch_result`（:2797 区）追加 `task_mode: str | None = None` 参数 → data 写 `task_mode` 键（与既有 `mode="native"` 并存；T1.2 的 timeout_class 同层并入）
    - ③ `_run_multi_round_via_subprocess`/`_run_single_round`（:12339/:11196 区）：从 task card 读 mode（`task_card.get("mode", "generate")`）→ 透传 ②；summary budget 块填 task_mode
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `TestSummaryBudgetBlock`（见验收）
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/git_helpers.py`（T2.3 拆入的收口件）：显式 import 列表与 `__all__` 各追加 `_verify_plan_patch_scope`（字母序插入，沿用 #3155 T1.3 的 I001/RUF022 定向门禁）；**不改** `from loop_kit._core import *` 头行与其余 52 个既有符号
- **修改边界**：不改 summary 既有键（files_changed/round_details/exit_code/decision 等原样）；不改 `_migrate_state_schema`；feed 既有 `mode` 键语义不变；`git_helpers.py` 只追加一个符号，不新增函数/不调整既有导入块结构
- **质量检查方式**：
  - 检查项 1：`grep -n '"budget"\|task_mode' src/loop_kit/_core.py` 落在 summary 写入 / dispatch data 两处
  - 检查项 2：既有 summary 断言测试全绿（`uv run --group dev pytest -q -k "summary"`）
  - 检查项 3（git_helpers 同步）：`grep -n "_verify_plan_patch_scope" src/loop_kit/git_helpers.py` 命中 import 列表与 `__all__` 两处；`uv run ruff check --preview --select I001,RUF022 src/loop_kit/git_helpers.py` 通过
- **验收标准**：
  - ✅ `TestSummaryBudgetBlock` 用例：① 预算启用时 summary 含 `budget` 块且字段齐全（session_elapsed_sec/task_mode/timeout_counts 等）② 全默认（0=禁用）时 summary **不含** budget 块（向后兼容锁定，复用既有 summary 断言 fixture）③ task_mode=patch 透传断言（feed 事件 data 含 `task_mode: "patch"` 且 `mode: "native"` 并存）④ 缺省（无 mode 键）→ `task_mode: "generate"`
  - ✅ `uv run --project /home/gw/opt/agent-task-runner python -c "from loop_kit.git_helpers import _verify_plan_patch_scope"` 导入成功且 `__all__` 含该符号（检查项 3 命令复核）
  - ✅ `uv run --group dev pytest -q` 0 failed；`uv run ruff check src/loop_kit tests` 0 error
- **潜在风险**：summary 写入函数名/位置漂移（:1105 邻近已多次重构）→ 执行时 grep 重定位为准；既有 summary 测试对 payload 键集合做了**精确断言**（白名单）→ 若冲突，budget 块改为 `None` 缺省跳过（用例 ② 已锁定该语义，冲突时优先保既有测试，budget 块降级为显式启用才写）
- **预留歧义标注**：
  - [x] 无歧义

#### Task 3.2: revision_disposition 契约文档（ATR 自有，零代码）
- **目标**：新文档定义 ATR 消费者契约；显式声明 copilot-agents 无此符号、生产者实现归属上层（OUT-OF-SCOPE）
- **依赖**：T2.1（契约 schema 定稿后）
- **frontier**：是（纯文档，可与 T3.1 并行——不同文件零冲突）
- **执行者**：人工
- **修改内容**：
  - 文件（新建）`/home/gw/opt/agent-task-runner/docs/design/revision-disposition-contract.md`：
    - ① 背景与定位：ATR 是 revision_disposition 的**消费者**；上游（PM 调度层 / 未来的 copilot-agents）是生产者；本仓 `src/ docs/` grep 确认无该符号，copilot-agents 亦无（2026-09-03 实测）
    - ② mode 枚举语义表：generate / patch / revise / rebuild 的 ATR 行为差异（patch 触发 plan_patch 契约 + 后置验证；revise/rebuild 当前仅观测，行为同 generate——显式声明「预留位，语义未激活」）
    - ③ plan_patch 键 schema（对齐 D4，含 fail-closed 规则与 `EXIT_PLAN_PATCH_VIOLATION=6`——注明仅单轮子进程层断言，父进程归一 exit 3）
    - ④ 消费点清单：feed 事件（task_mode/timeout_class/plan_patch_verify/violation）、summary budget 块、`_verify_plan_patch_scope` 挂点
    - ⑤ 生产者最小实现建议：仅需在 task card 写入 `mode` 键（`plan_patch` 仅 patch 模式需要）；**不改动 copilot-agents 现有任何文件**；若未来接口由上层实现，本契约是验收基准
    - ⑥ 维护声明：mode 枚举变更必须同步 `_TASK_MODES`（:232 区）与本文档
  - ⛔ 不创建/不修改任何 copilot-agents 与 project_management 文件
- **修改边界**：纯文档；不得在文档中声称任何「已获授权」事项（授权归因硬规则）；不得给出未经本仓实测的 copilot-agents 内部细节（只陈述「无该符号」这一实测事实）
- **质量检查方式**：
  - 检查项 1：`grep -c "revision_disposition" docs/design/revision-disposition-contract.md` ≥1
  - 检查项 2：文档内无指向 copilot-agents 文件路径的修改指令（只有「不改」声明）
- **验收标准**：
  - ✅ 文档包含 ①-⑥ 六节；OUT-OF-SCOPE 声明可被 PM/上层直接引用
  - ✅ 文档中 mode 枚举与 `_TASK_MODES` 常量逐字一致（执行时 diff 比对）
  - ✅ 全量测试不受影响（纯文档任务：`uv run --group dev pytest -q` 基线不变）
- **潜在风险**：无（纯文档）
- **预留歧义标注**：
  - [x] 无歧义

#### Task 3.3: 历史案例回测收口 + 全量回归 + 冻结区复核
- **目标**：三组历史回测（若 T1.2/T1.3/T2.3 已内嵌，此处做**整合性**复跑 + 新增大粒度场景）；#3155/#3135 定向回归；物化一致性终验
- **依赖**：T3.1
- **frontier**：否
- **执行者**：人工
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `TestPm3263HistoricalReplay`（整合场景，若前序内嵌测试已覆盖则本类只加跨特性组合场景，禁止重复用例）：
    - ① `test_patch_mode_end_to_end_fail_closed`：patch 任务卡 + 越界 worker（tmp 仓真实 `git init` + 越界提交）→ 验证器拒 + **单轮子进程层** exit 6 + feed 事件序 `dispatch_complete → plan_patch_violation`，无重试（Popen 计数）；**父进程层**断言最终归一 exit 3（不声称 6 上浮，与 D5/T2.3 分层一致）
    - ② `test_session_budget_caps_repeated_timeouts`：3 轮连续 dispatch 超时场景 + session_timeout_sec 收紧 → 断言会话在第 2 轮被截断（对照历史 21.6/21.8min ×3 案例：**旧行为** = 3 次完整超时重试，**新行为** = 预算截断后不再派发）
    - ③ `test_context_budget_long_session_signals`：5 轮 token 累计越过预算 → summary budget 块 `context_budget_exceeded=True` + feed 含 exceeded 事件（对照历史 87.3min 长会话案例）
    - ④ `test_generate_mode_unaffected_by_patch_verifier`：generate 模式全程无 verifier 调用（大粒度回归）
  - 无其他代码文件改动
- **修改边界**：不新增测试辅助依赖（沿用 tmp_path/monkeypatch 套路）；不触碰 test_concurrency.py / test_pm_integration.py
- **质量检查方式**：
  - 检查项 1：新测试类用例数 ≥4 且无与 T1.2/T1.3/T2.3 重复的断言路径（复用 fixture、不同场景层）
- **验收标准**：
  - ✅ 全量 `uv run --group dev pytest -q` 0 failed（基线 677 + 本计划新增，总数记录 commit message）
  - ✅ 定向回归：`uv run --group dev pytest -q -k "lock or dirty or worktree or skill or worker_prompt or Budget or Watchdog or PlanPatch or HistoricalReplay"` 全绿
  - ✅ `uv run ruff check src/loop_kit tests` 0 error；`uv run python -m py_compile src/loop_kit/_core.py` 通过；`uv run --project /home/gw/opt/agent-task-runner python -c "from loop_kit.orchestrator import *"` 通过
  - ✅ 物化一致性终验：`.loop/templates/worker_prompt.txt` 与 `DEFAULT_WORKER_PROMPT_TEMPLATE` 字节级一致（#3135 V3 复验，本计划全程不改模板）
  - ✅ 冻结区终验：`git diff HEAD --stat` 不含 `.loop/templates/`、不含 `_acquire_repo_lock`/`_LoopLock`/`_enforce_clean_worktree_or_exit` 区域改动（逐文件 diff 审查）；`git status --porcelain` 无新增越界 untracked（`data/`、旧计划文件原样）
- **潜在风险**：全量测试时长与基线偏差 → 记录新旧时长对比；若出现与本计划无关的既有失败 → 不修，报备并标注（本任务不扩大范围）
- **预留歧义标注**：
  - [x] 无歧义

## Execution Wave（串行为主：同文件冲突约束）

| Wave | 可并行 Task | Frontier | 依赖已完成 | 串行理由 |
|------|------------|----------|------------|----------|
| W1 | T1.1 | T1.1 | — | 唯一改 `_core.py` 者 |
| W2 | T1.2 | T1.2 | W1 | 同文件（_core.py + 测试）串行（#3155 R1-1 教训） |
| W3 | T1.3 | T1.3 | W2 | 同文件串行 |
| W4 | T1.4（CT-1 门） | — | W3 | 审阅依赖三 commit 落地 |
| W5 | T2.1 | T2.1 | W4 | 同文件串行 |
| W6 | T2.2 | T2.2 | W5 | 同文件串行 |
| W7 | T2.3 | T2.3 | W6 | 同文件串行（_core.py + orchestrator.py ownership map；git_helpers.py 拆至 T3.1，保 ≤3 文件/task） |
| W8 | T2.4（CT-2 门） | — | W7 | 审阅依赖落地 |
| W9 | T3.1 ∥ T3.2 | T3.1、T3.2 | W8 | T3.1 改代码，T3.2 纯新文档，零文件交集可并行 |
| W10 | T3.3 | T3.3 | W9 | 收口依赖全链路 |

**CoT Stage 4 依赖推理**：唯一真正的文件冲突轴是 `src/loop_kit/_core.py` 与 `tests/test_orchestrator.py` 的追加式修改——每个 task 锚定不同函数区域，但追加顺序影响行号漂移与 commit 粒度，故强制串行；T3.2 是纯文档、与任何代码 task 零交集，是唯一并行点。**失败回滚策略**：每 task 独立 commit（前缀 `[Plan: pm3263-...]`），失败即 `git revert <该 commit>` 单独回退，不牵连其他 wave；跨 task 状态（state.json 新键）由 T1.2 独立 commit 承载，回退后不影响 T2.x（T2.x 不依赖 state 新键）。

## Post-Execution Verification

Dev Orchestrator / 执行者在所有 task 完成后**必须**运行本节。

### Automated Verification（执行者自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量测试 | `uv run --group dev pytest -q` | exit 0，0 failed |
| V2 | 定向回归（冻结区 + 新特性） | `uv run --group dev pytest -q -k "lock or dirty or worktree or skill or worker_prompt or Budget or Watchdog or PlanPatch or HistoricalReplay"` | exit 0 |
| V3 | ruff | `uv run ruff check src/loop_kit tests` | 0 error |
| V4 | 编译 + 门面导入 | `uv run python -m py_compile src/loop_kit/_core.py && uv run --project /home/gw/opt/agent-task-runner python -c "from loop_kit.orchestrator import *; from loop_kit.git_helpers import _verify_plan_patch_scope"` | exit 0 |
| V5 | #3135 物化一致性 | `uv run --project /home/gw/opt/agent-task-runner python -c "from loop_kit._core import DEFAULT_WORKER_PROMPT_TEMPLATE; p='.loop/templates/worker_prompt.txt'; import pathlib; assert pathlib.Path(p).read_text(encoding='utf-8') == DEFAULT_WORKER_PROMPT_TEMPLATE + '\n', 'template drift'"` | exit 0 |
| V6 | #3155 历史回放复跑 | `uv run --group dev pytest -q -k "3151 or 3152 or dirty_tree or repo_lock"` | exit 0（若存在对应测试名，执行时以 `pytest --collect-only -q` 实测名为准） |
| V7 | gap 反向验证 | `grep -c "def _verify_plan_patch_scope\|FEED_SESSION_TIMEOUT\|FEED_CONTEXT_BUDGET\|FEED_PLAN_PATCH_VIOLATION" src/loop_kit/_core.py` | ≥4（每符号 ≥1） |
| V9 | ownership map 双文件一致（CT-1） | `diff <(grep '"git_helpers": (' src/loop_kit/_core.py) <(grep '"git_helpers": (' src/loop_kit/orchestrator.py)` | 空输出（两处条目逐字一致）且 killpg 零命中：`grep -c killpg src/loop_kit/_core.py` = 0 |
| V8 | 冻结区零改动 | `git diff HEAD --stat -- .loop/templates/` | 空输出 |
| V1b | de-ai-fier 术语门 | `de-ai-fier/deai_review_file(path=<本计划文件>.md, doc_type="plan", strict=false, include_ai_flavor_assessment=true)` | 术语 finding（suggestion/info 级）记录摘要不参与 blocking；MCP 不可用标注 `[⚠️ skipped]` |

### Probe (best-effort, run if available)
- [ ] P1: `ls /tmp/loop-kit-repo-locks/ 2>/dev/null` — 执行期间无遗留锁文件（若有 → 核对 pid 是否存活；遗留孤儿锁由既有 `_cleanup_stale_lock` 语义处理，本计划不改其逻辑）

### Manual（真正需要人工判断）
- [ ] M1: 审阅 T1.4/T2.4 两份 critical-thinking 记录，确认 blocking 发现全部有处置记录（折入任务或豁免理由）
- [ ] M2: 审阅 `docs/design/revision-disposition-contract.md`，确认 OUT-OF-SCOPE 声明与「不修改 copilot-agents」边界在文档中显式可引用
- [ ] M3: `git log --oneline` 确认每个 task 独立 commit 且前缀一致；`git status --porcelain` 最终清单 = 执行前 untracked 清单 + 本计划文件（无新增越界项）

## 风险 / 回滚矩阵

| # | 风险 | 影响 | 缓解 | 回滚 |
|---|------|------|------|------|
| R1 | `_STATE_CMP_KEYS` 短路丢 `session_deadline_at` 变更（:6731-6738 源码实证；原「校验拒绝」已降级——`_migrate_state_schema` passthrough） | T1.2 阻塞 | T1.2 必改项：cmp 键追加 + 用例 ⑤ 落盘断言；若首步复核与实证不符 → 降级方案（父进程内存 deadline） | 不落 state 即无需回滚 |
| R2 | `_validate_task_card_contract`（:8273）扩展误伤旧卡 | **High**：全量旧任务卡被拒 | total=False 语义 + 键缺失即通过 + 用例 ① 重放 `.loop/examples/task_card.json` 锁定 | revert T2.1 commit |
| R3 | plan patch verifier 误判正常提交 | patch 模式任务中断 | verifier 纯只读 + 仅 patch 模式启用 + CT-2 题 2/3 审查窗口 | revert T2.3 commit |
| R4 | `_run_multi_round_via_subprocess` 挂点与既有轮逻辑交互（父进程重复验证/事件重复） | 观测噪声 | 双挂点幂等：父侧以子进程返回码为准仅复核 | revert T2.3/T3.1 |
| R5 | summary 既有测试对 payload 键集合精确断言（白名单）→ budget 块冲突 | T3.1 失败 | 用例 ② 锁定「默认不写块」语义；冲突时降级为显式启用才写 | revert T3.1 commit |
| R6 | watchdog 误杀合法长任务（预算设过小） | 用户任务损失 | 默认 0=禁用；session_timeout_sec>0 才启用；历史回测覆盖截断语义 | 改配置即恢复，无需回滚代码 |
| R7 | Windows 兼容回归（新路径引入 POSIX 假设） | Windows 部署故障 | 检查项 3（新增行 os.kill/signal 为 0）+ CT-1 题 4 | revert T1.2 commit |
| R8 | daemon warn_only 语义漂移 | 长驻调度被干扰 | daemon 分支 diff=0 边界 + CT-1 题 3 | revert T1.2 commit |
| R9 | #3155/#3135 成果回退（冻结区误触） | 双重故障 | 冻结区清单 + V5/V6/V8 门禁 + 定向回归 | revert 本计划全部 commit（前缀可 grep） |
| R10 | 与并发会话冲突（他人同时改 _core.py） | 锚点漂移/合并冲突 | Phase 0 强制重核 + 每 Phase 首步重检 + 串行 Wave | 冲突时暂停并记录，不强制 |

**整体回滚**：全部 commit 携带 `[Plan: pm3263-watchdog-context-budget-plan-patch]` 前缀，`git log --grep` 逆序 revert 后运行 V1-V3 确认回到 677 passed 基线。

## Error & Rescue Map

| 路径 | 症状 | 处置 | 阻断下游 |
|------|------|------|----------|
| E1 配置校验未知 | `_validate_run_config` 签名/名称不符假设 | grep 重定位照实调整 | 否 |
| E2 state 键拒绝/不落盘 | `_save_state` 短路丢 deadline 变更（:6731-6738 实证） | **已根因化**：T1.2 必改项将 `session_deadline_at` 追加进 `_STATE_CMP_KEYS` + 用例 ⑤ 落盘断言；若首步复核发现 `_migrate_state_schema` 与实证不符 → 降级方案（内存 deadline） | 否（T2+ 不依赖） |
| E3 task card 契约结构未知 | :8273 实现与 TypedDict 假设不符 | 读全文，扩展白名单集而非重写 | T2.1 内解决 |
| E4 verifier git 失败 | 非 git 场景/无 HEAD | fail-closed（violation: git_unavailable） | 否 |
| E5 CT 委派空返回 | critical-thinking 空转 | 重试 1 次 → 降级自审标注 `[DELEGATION-EMPTY]`（#3155 先例） | 否（门不取消，改自审） |
| E6 基线测试失败 | 全量出现非本任务失败 | 不修、报备、标注（范围不扩大） | 是（先归因再继续） |
| E7 物化模板漂移 | V5 失败 | 本计划不改模板 → 漂移必来自外部 → 暂停查明（#3135 归属） | 是 |
| E8 prompt 渲染链不含 task_card 段 | T2.2 检查点 3 失败 | 挂进 `_render_task_packet_section` 相邻点（仍不改模板） | T2.2 内解决 |
| CRITICAL GAP | — | 无 | — |

## 审查日志（Plan Architect 三轮自审）

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（字段/编号/契约完备性） | 1 | 1 | 0 |
| R1.5 | 外部引用事实核查（锚点/符号/命令） | 0 | 0 | 0 |
| R2 | 可执行性（粒度 ≤3 文件/依赖无环/命令可行性） | 1 | 1 | 0 |
| R2.8 | LLM 可执行性审查（歧义消解） | 1 | 1 | 0 |
| R3 | 风险与边缘（跨轮一致性 + What-If + 回滚安全） | 0 | 0 | 0 |
| CT-1（计划审阅轮，rev 3） | critical-thinking 第一轮 MINOR 意见 5 条落实 | 5 | 5 | 0 |
| **终止** | **[T1]，收敛终止（CT-1 修订后 issue=0，三要素齐全）** | | | **0** |

### R1 Issues
- **Issue R1-1 [FIXED — T2.3 facade 归属留二选一]**: 原写「git_helpers 或 file_bus 二选一」给执行者留决策 → 定案 `git_helpers.py`（git diff 语义归属），T2.3 ⑤ 已更新 ✅。⚠️ **CT-1 复核发现 rev 2 断言「ownership map `"git_helpers"` 条目存在」为误**：实测 `_SECTION_OWNERSHIP_MAP`（_core.py :259-269 / orchestrator.py :32-42）均无该条目，仅 `_SECTION_MODULE_PATHS`（orchestrator.py :55）有路径条目 → rev 3 已改为「两处 map 同步新增条目 + git_helpers.py `__all__` 拆入 T3.1」，见 CT-1 修订轮

### CT-1 修订轮（critical-thinking 第一轮 MINOR 意见，rev 3，全部本会话源码实测后落实）
- **CT-1-1 [FIXED — ownership map 两处新增，不再声称已存在]**: `_core.py` 与 `orchestrator.py` 的 `_SECTION_OWNERSHIP_MAP` 同步追加 `"git_helpers": ("_git", "_git_at", "_verify_plan_patch_scope")`（orchestrator 版 map 在 facade import 时整体覆盖 `_core_module` 版，两处必须一致）；`git_helpers.py` 显式 import + `__all__` 同步拆入 T3.1 → T2.3 恰 3 文件（_core.py + orchestrator.py + tests），T3.1 恰 3 文件（_core.py + tests + git_helpers.py），不突破 ≤3 文件规则（拒绝 4 文件预算方案）✅
- **CT-1-2 [FIXED — watchdog 清理改称真实既有链；killpg 另列为新设计并解除禁用冲突]**: 实测源码无 killpg/进程组信号杀（f689c18 仅测试层复核；:1326/:1379 为锁诊断探针）→ D2/T1.2 ④ 改称真实既有链 `_close_pipe(stdin)` → `proc.terminate()` → `proc.wait(timeout=2)` + suppress；killpg 明确为**新设计、不在本计划范围**（与 Windows 兼容 + 检查项 3 互斥，须另立任务），最小 scope 坚持 terminate 直系子进程 ✅
- **CT-1-3 [FIXED — exit 6 仅子进程层断言，父进程归一 exit 3 写清]**: 实测父进程 :12572-12584 对任何非零子进程 rc 归一 `EXIT_VALIDATION_ERROR`=3 → D5/T2.3 ④/验收 ⑦/T-3263-c 分层界定：exit 6 只在 `_run_single_round` 子进程域；父进程复核不 exit 6、只补发 info 级事件并沿用归一 exit 3 ✅
- **CT-1-4 [FIXED — untracked 改动态检查，不固定错数]**: 实测 untracked 6 项（4 旧计划 + data/ + 本计划），rev 2「5 项/3 旧计划」为过时数 → 适配复核/Phase 0 改为「Phase 0 全量 `git status --porcelain` 输出 = 动态基线，逐 Phase 比对」，计数仅为生成时参考值 ✅
- **CT-1-5 [FIXED — `_save_state` 的 `_STATE_CMP_KEYS` 短路]**: 实测 :6731-6738 十键全等即 return 不落盘 → deadline-only 变更会被静默丢弃 → T1.2 必改项：`_STATE_CMP_KEYS` 追加 `session_deadline_at` + 新增用例 ⑤（落盘/跳过双语义）+ I7/R1/E2 同步更新；`_migrate_state_schema`（:6638）passthrough 实证使假设 2 从 High-impact 降级 ✅

### R1.5 Issues（外部引用核查——全部本会话实测）
- 锚点实测证据：`RunConfig` :592-617、`_KNOWN_CONFIG_KEYS` :514-539、`_load_env_config` :8895、`TaskCard` :229-238、`_validate_task_card_contract` :8273、`_load_task_card_or_raise` :8305、`_run_auto_dispatch` :3115、`_collect_streamed_process_output` :2847、`_report_dispatch_result` :2797、`_retry_budget_fields` :2780、`_is_permanent_dispatch_error` :3003、`_normalize_token_usage` :4722、`_render_task_card_section` :5783、`_worker_prompt` :6275、`_write_template_if_missing` :9303、`_run_multi_round_via_subprocess` :12339、`_run_single_round` :11196、`_feed_data` :1493（extra 透传）、FEED_* :379-394、repo lock 组 :1310-1407、EXIT_* :443-449、`_write_round_summary` :1062、summary 写入 :1105 — 全部 read/grep 验证，0 凭记忆
- gap 零命中复验：`watchdog/plan_patch/task_mode` 在 src 源码 0 命中（pyc 二进制命中已排除）；`revision_disposition` 在 src/ docs/ 0 命中
- git 历史复验：HEAD=fce570e；#3155 = 98677dd..f689c18 九连 commit；#3135 = fce570e；`.loop/templates/worker_prompt.txt` 为 git-tracked
- 命令模式复验：`uv run --project /home/gw/opt/agent-task-runner python ...` 为 #3155 REFINE-1-2 验证过的正确 venv 解析形式（cwd 独立）
- **CT-1 修订轮补测锚点（rev 3，本会话实测）**：`_save_state` :6718、`_STATE_CMP_KEYS` :6731-6738（10 键短路）、`_migrate_state_schema` :6638-6651（passthrough dict 拷贝）、`_validate_state_transition_residue` :6771-6785（只查 required/forbidden）、`_SECTION_OWNERSHIP_MAP` `_core.py` :259-269 / `orchestrator.py` :32-42（均无 git_helpers 条目）、`_SECTION_MODULE_PATHS` orchestrator.py :44-56（:55 有路径条目）、`git_helpers.py` 110 行（显式 import + `__all__` 52 符号，含 `_git`/`_git_at`）、terminate 链 :2922-2931/:12532-12534/:12555-12557/:12627-12629、父进程 rc 归一 :12572-12584（EXIT_VALIDATION_ERROR=3）、killpg 源码 0 命中（:1326/:1379 为 `os.kill(pid, 0)` 锁诊断探针）、untracked 实测 6 项

### R2 Issues
- **Issue R2-1 [FIXED — T2.1 验收 ② 编号残留]**: 「消息含 `_TASK_MODES` ④ 值」中「④」为编号残留 → 改为「含 `_TASK_MODES` 枚举值」 ✅

### R2.8 Issues
- **Issue R2.8-1 [FIXED — heading 锚点窗口未定稿]**: ±200 行窗口原本仅在风险处提及 → 已在 T2.3 修改内容 ② 明确「标题行 ±200 行，实现从简」+ CT-2 题 3 必审，消除执行者自定边界的猜测 ✅

### R3 Issues（跨轮一致性 + What-If）
- 跨轮一致性核验：`_TASK_MODES` 在 T2.1（定义）与 T3.2（文档逐字比对）两处一致；`budget` 块字段在 D3（定义）与 T3.1（实现）一致；timeout_class 枚举在 D2（taxonomy）与 T1.2 ⑦/T3.1 ②（实现点）一致；feed 新事件名在 D2/D3/D5（设计）与 T1.2/T1.3/T2.3（常量追加）一致 — 0 漂移
- **What-If Preview（R3-7）**：
  - `RunConfig` 加字段 → 消费点 `_validate_run_config`/`_load_env_config`/`_KNOWN_CONFIG_KEYS` 同 task 内更新；无外部消费者依赖旧字段集（dataclass slots 追加安全）[影响预览: 低]
  - `_run_auto_dispatch` 签名追加 keyword-only 参数 → 调用点共 3 处（含包装函数转发；执行时按 grep 结果逐一同步），T1.2/T3.1 同批更新；既有测试以 keyword 调用不受影响（keyword-only 追加零破坏）[影响预览: 低]
  - `_report_dispatch_result` 加参数 → 调用点 3 处（:3346/:3392/:3431 区），keyword-only 缺省 None 零破坏 [影响预览: 低]
  - `_render_task_card_section` 尾部追加 → 唯一调用链 `_build_task_packet`，输出为纯文本追加，无格式断言风险（#3135 断言仅针对 SKILL LOADING 与模板文件，不受影响）[影响预览: 低]
  - 新符号 `_verify_plan_patch_scope`/`_render_plan_patch_contract` 为新增，无既有引用 [影响预览: 零]
- **Red-Team Round（阶段 2.5）**：本计划未委派独立 Red-Team（T1.4/T2.4 两个 critical-thinking 门为执行期内建 Red-Team 入口，覆盖 Plan 阶段 2.5 意图）；Plan 阶段以三-lens 自审替代并记录：Lens A（注入）：plan_patch 契约来自 task card 磁盘内容 → `_validate_task_card_contract` 结构强校验 + 渲染纯拼接无 format + verifier 只读；Lens B（静默失败）：verifier git 调用失败 → fail-closed（E4）；台账 token 缺失 → proxy 标注（D3 risk）；Lens C（跨任务漂移）：`_TASK_MODES`/字段名跨 task 一致性已在 R3 核验。结论：可通过。

### 授权归因声明（Critical Rule 8）
- 本计划**不含**任何「已获授权 / D2 门控确认 / 用户已批准」类声明；PM #3263 状态回写（todo→doing/done）不属本计划执行范围（用户指示「不执行」），如需更新经 pm-coordinator 委派，由用户决定时点。三要素无一项满足 → 全部操作定位为「人工执行、用户在场」，无编造授权。

## Completion Summary

| 维度 | 结果 |
|------|------|
| 背景与目标 | 完整（PM #3263 六条范围映射 + 适配复核七条吸收 + 非目标八条） |
| T2 影响面分析 | I1-I11 表（配置/超时/重试/token/事件/summary/跨进程状态/task card/prompt/mode/越界红线），每项含实测锚点与风险等级 |
| 技术方案 | D1-D8 决策表（含 ALTERNATIVES/RATIONALE/RISK）+ 6 条假设（假设 2 经 CT-1 源码实证降级为非 High-impact，`_STATE_CMP_KEYS` 短路为新识别必改项） |
| Error & Rescue Map | 8 条路径（E1-E8），CRITICAL GAP 0 |
| 执行计划 | 3 Phase、10 执行 task（T1.1-T1.3/T2.1-T2.3/T3.1-T3.3）+ 2 个 CT 审阅门（T1.4/T2.4）+ Phase 0 强制重核 |
| Execution Wave | W1-W10，唯一并行点 T3.1∥T3.2（零文件交集）；串行理由 = 同文件追加冲突（#3155 R1-1 教训） |
| Post-Execution Verification | Automated 10（V1-V9 + V1b de-ai-fier）+ Probe 1 + Manual 3 |
| 风险/回滚矩阵 | R1-R10 + 整体回滚路径 |
| 审查日志 | R1/R1.5/R2/R2.8/R3 五轮 + CT-1 修订轮（5 条 MINOR 全清零），终止条件 T1 |
| 历史案例回测 | T-3263-a（21.6/21.8min ×3 会话超时 → 预算截断）、T-3263-b（87.3min 长会话 → token 台账）、T-3263-c（patch 越界 → 子进程 exit 6 / 父进程归一 exit 3 + fail-closed） |
| 已知局限 | ① heading 锚点 ±200 行是 v1 简化（CT-2 必审）；② `_migrate_state_schema` 可选键透传已源码实证（低风险），真实拦路点 `_STATE_CMP_KEYS` 短路已入 T1.2 必改项；③ 计划生成时未跑全量测试（基线 677 为适配复核值，Phase 0 强制重测）；④ CT 门为执行期委派，若空返回按 #3155 先例降级自审；⑤ watchdog 终止仅直系子进程（killpg 新设计不在本计划范围）；⑥ untracked 基线为 Phase 0 动态快照，生成时计数仅供参考 |

## 关键设计决策速览（交付摘要）

1. **预算模型**：RunConfig 4 字段 + 3 个 `LOOP_*` 环境变量，默认 0=禁用零行为漂移；token 台账 = work report token_usage 累计 + prompt_chars 代理，双阈值事件，**观测先行不硬杀**
2. **Watchdog**：会话级 wallclock deadline 挂 4 检查点（cmd_run/多轮循环/单轮自限/attempt 前），经 state.json 跨进程传递（`_STATE_CMP_KEYS` 追加 `session_deadline_at` 保证 deadline-only 变更落盘），终止复用真实既有 `proc.terminate()` + `wait(timeout=2)` 链；**不引入** killpg/进程组信号杀（源码无此机制，POSIX-only 与 Windows 零 POSIX 假设冲突，另立设计任务）
3. **Plan patch**：task card `mode`/`plan_patch` 声明式契约 → prompt 动态段引导（静态模板零改动）+ `_verify_plan_patch_scope` git diff 后置硬闸（文件白名单 + 锚点校验 + forbid_new_files），违例 = PermanentDispatchError + **单轮子进程层** exit 6 + **不重试**（父进程沿用既有归一 exit 3，违例明细经 feed 事件上达），无契约即无 patch 模式（fail-closed）；ownership map 两处（`_core.py`/`orchestrator.py`）同步新增 `"git_helpers"` 条目，`git_helpers.py` `__all__` 同步拆入 T3.1（保 ≤3 文件/task）
4. **观测**：`task_mode` 走 `_feed_data` extra 透传（与既有 `mode="native"` 键并存）；summary 追加可选 `budget` 块；零新持久化格式
5. **契约外置**：revision_disposition 只写 ATR 自有 `docs/design/revision-disposition-contract.md`，copilot-agents 零改动，生产者归属上层显式声明
6. **回测**：三组真实历史案例（21.6/21.8min ×3、87.3min 长会话、patch 越界）映射为确定性单元测试
7. **治理**：人工执行、不创建 auto 任务（防 ATR 自举修改自身）、每 task 独立 commit、Phase 0 强制重核 HEAD/status/并发






## 执行期审阅记录（T1.4 CT-1 门，2026-09-03 执行时追加）

**CT-1 执行轮（Phase 1 落地后）**：委派 critical-thinking 两次均因 subagent_depth 限制失败（非空返回，为基础设施错误）→ 按计划 E5 / #3155 先例降级为执行者自审。`[DELEGATION-EMPTY: critical-thinking — fallback self-review]`

| 题 | 结论 | 发现 | 处置 |
|----|------|------|------|
| 1 子进程边界 | OK | 非-blocking：拦截精度为轮粒度（检查点式，进行中 attempt 不被会话 deadline 中断） | 豁免：与 D2 设计一致，已声明 |
| 2 预算会计 | OK | 非-blocking：混合轮次（token+proxy）存在理论漏报窗口 | 豁免：纯观测不硬杀；token_source 三态 + prompt_chars 累计同时上报；T3.1 summary 保留 token_source |
| 3 daemon 语义 | OK | 无 | — |
| 4 Windows | OK | 无 | — |

**门结论**：无 blocking 发现 → 直接进入 Phase 2（无需 CT-1-补 任务）。


---

## CT-2 执行轮记录（2026-09-04 落盘）

**时机**：T2.3 落地后、T3.1 前。首轮委派超时，重试成功（critical-thinking，
会话 ses_f987a3af4ffeOjaqJy2ARuVYVf）。

**裁决**：REFUTED（HIGH）→ 修复后通过。

**四题结论**：
1. allowed_anchors 空拒绝边界：全局空 → fail-closed ✅（测试 ⑥ 锁定）。残余：anchors 仅覆盖文件 A 时，白名单内计划文件 B 可无锚改动静默通过（🟡 v1 记录不修）。
2. stash/submodule/gitignore 绕过：stash=拒付向量（非越权）；submodule fail-closed；gitignore 隐藏文件 status 不可见（🟡 残余风险，v1 记录）。
3. heading ±200 行窗口：**裁定可接受**。警示：计划文件 ≤400 行时锚定近失效；首匹配语义（🟡 v1 放行）。
4. 父子双挂点幂等与 exit6/exit3：**裁定通过**。瑕疵：FEED_PLAN_PATCH_VERIFY 双语义混用（🟡 文档化）。

**Blocking（已修复）**：
- 🔴-1 事实源错误：`git diff HEAD` 与 worker 强制提交模型矛盾 → 改用 `git diff base_sha..head_sha`（commit a9e4243），集成测试改真实 commit 夹具。
- 🔴-2 untracked 无任务起点基线 → 文档化"执行时动态核对 pre-existing untracked 项"，不固化固定数量。

**T3.3 豁免记录（O3 关闭依据）**：计划要求的独立 `TestPm3263HistoricalReplay` 类不单独执行——T-3263-a/b/c 三类历史回测已分别内嵌于 TestSessionWatchdog / TestContextBudget / TestPlanPatchVerify（各含真实历史案例回放用例），再建独立类属重复。此豁免经用户批准（"O3 可判豁免"）。
