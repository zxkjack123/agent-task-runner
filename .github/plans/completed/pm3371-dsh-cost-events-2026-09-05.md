# Plan: dsh in-process 派发 M4 成本事件落地（PM #3371）

- **revision**: 1（2026-09-05，生成时 HEAD=796f606f）
- **scope_mode**: HOLD — 触达仅 2 文件、硬约束密集（5 元组契约/费率/仅本仓），严禁范围漂移
- **Clarify Gate**: PASS — 用户已裁决策 A（无 usage 事件时 cost_cents=0，字段仍存在）
- **plan_owner**: Plan Architect → handoff: dev-orchestrator

## 背景与目标

- **问题**：dsh in-process（SDK）派发产生的 `dispatch_complete` 事件无成本信息。subprocess 路径同样无——唯一产生点是共享 chokepoint `_report_dispatch_result`（_core.py:3182-3237），data 无 cost/tokens 字段。
- **目标**：dsh in-process 派发后，`dispatch_complete`（及失败时的 `dispatch_fail`）data 含 `cost_cents`（+ token 字段，若可得）。
- **非目标**：不改 subprocess 路径事件形态；不改 `_run_dsh_sdk_dispatch` 5 元组返回契约（tests/test_dsh_backend.py 8 测试依赖）；不动 `_BACKEND_TOKEN_COST_CENTS_PER_MILLION[BACKEND_DSH]=(43,129)`（:433 已存在）；不改知识库/归档/CI。

## 实证基线（已核实，执行时重测锚点）

- usage 事件真实结构：嵌于 `assistant/chunk` 事件，`data.chunk.type=="usage"`，用量在 `data.chunk.usage`（camelCase：inputTokens/outputTokens/totalTokens/cacheReadTokens/reasoningTokens）。非顶层 `type:"usage"`。
- SDK `RunResult` 无 usage 字段；usage 仅在 `result.events`。
- 关键锚点（HEAD=796f606f）：费率 :433；`_report_dispatch_result` :3182；in-process 分支 :3750-3784；共享报告点 :3908（timeout）/ :3949（正常）；subprocess 独有报告点 :3861（KeyboardInterrupt）；`_normalize_token_usage` :5241（仅认蛇形键）；`_runtime_cost_and_token_fields` :5292；`_feed_event` :1692；`_run_dsh_sdk_dispatch` :2899-3005。

## 关键设计决策（显式化）

- **D1 camelCase→snake 映射位置**：新增独立模块级 helper `_extract_dsh_usage_payload(events: object) -> dict[str, object]`，置于 dsh 区（`_dsh_parse_event` 附近，~:2864）。只映射 inputTokens/outputTokens/totalTokens（蛇形键）；丢弃 cacheReadTokens/reasoningTokens（`_runtime_cost_and_token_fields` 不消费，避免越权扩展）。**不扩展 `_normalize_token_usage`**——该函数被 work-report/lane-metrics/subprocess 多路径共享，保持字节级不变以兑现 subprocess 零变化承诺。dsh 特有嵌套（events→chunk→usage）+camelCase 知识集中一处。
  - ALTERNATIVES：扩展 `_normalize_token_usage` 加 camelCase fallback（可加但扩散共享面）；REJECTED。
- **D2 usage 扫描位置与提取通道**：扫描发生在 `_run_dsh_sdk_dispatch` 内部（`result.events` 仅此处可见）。该函数新增 kw-only 可选参数 `usage_callback: Callable[[dict[str, object]], None] | None = None`（镜像既有 `summary_callback` 风格）；成功取得 result 后计算 payload，非空才调用 callback。5 元组返回值一字不改；8 个既有测试不传新 kwarg → 零影响。超时/异常/no-result 早退路径不触发 callback。
  - ALTERNATIVES：改 6 元组（破坏契约，REJECTED）；mutable holder dict（隐式，弱于显式 callback，REJECTED）。
- **D3 多 chunk 归并与 cost 计算**：多个 usage chunk 取 `totalTokens` 最大者（cumulative-monotonic 快照语义，对"累计快照"与"逐 delta"两种流式都确定）；无 totalTokens 时取最后一个非空 chunk。cost 复用 `_runtime_cost_and_token_fields(payload, backend=backend)`（内部走 `_estimate_backend_cost_cents` + 既有 (43,129) 费率；input/output 齐备时 total 不参与加权，cacheRead 不污染 cost）。
- **D4 事件 merge 通道**：`_report_dispatch_result` 新增 kw-only 可选 `runtime_fields: dict[str, object] | None = None`，非 None 时在 `_feed_event` 前 `data.update(runtime_fields)`。subprocess 三报告点（3861/3908/3949 不传）→ 零变化。`_run_auto_dispatch` 在 :3750 附近初始化 `dsh_usage_payload: dict[str, object] = {}`；in-process 调用点（~:3777）传 `usage_callback=lambda p: dsh_usage_payload.update(p)`；if/else 合并后（~:3792）单点计算 `report_runtime_fields = _runtime_cost_and_token_fields(dsh_usage_payload, backend=backend) if run_fn is not None else None`，注入 :3908 与 :3949 两个共享报告点。空 payload → `{"cost_cents": 0}`（决策 A：字段在、值为 0）。
- **D5 键冲突**：runtime_fields 键（input_tokens/output_tokens/total_tokens/cost_cents）与 `_feed_data`/`_retry_budget_fields` 输出键无交集，merge 无覆盖风险（已核对 :3207-3228）。

## 假设清单

1. `_require_registered_backend("dsh")[3]` 返回 `_run_dsh_sdk_dispatch`（:3011 注册确认）；`run_fn is not None` 是 in-process 路径的精确判据。低影响。
2. 基线全量 777 passed（任务给定）；执行时先重测（`--collect-only -q` 计数）。
3. 真机验证需本机已装 deepseek-harness-sdk 与有效凭据；不可用则 Probe 降级 SKIP 并记录（不影响验收代码部分）。
4. usage chunk 只出现在 assistant/chunk 事件（3/3 transcript 实证）；若未来出现顶层 usage 事件，`_extract_dsh_usage_payload` 需小幅扩展——测试用 fixture 覆盖此形态留回归哨。

## 执行计划

### Phase 1: 成本事件落地（3 任务，串行）

**基线漂移重检**（Phase 首步，强制）：`git rev-parse HEAD` + `git status --porcelain`；若 :433/:3182/:3750/:3908/:3949 锚点或 tests/test_dsh_backend.py 漂移 → 先重定位锚点再动手。仅 stage `src/loop_kit/_core.py` + `tests/`。

#### Task 1.1: 新增 `_extract_dsh_usage_payload` 纯函数 helper + 单测
- **目标**：将 SDK events 中的 usage chunk 提取并映射为蛇形键 payload（纯函数，无副作用）
- **依赖**：无
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**：
  - `src/loop_kit/_core.py`：在 dsh 区（`_dsh_parse_event` 之后、`_run_dsh_sdk_dispatch` 之前，~:2864）新增：
    `def _extract_dsh_usage_payload(events: object) -> dict[str, object]`——迭代 events（list[dict]），命中 `type=="assistant/chunk"` 且 `data.chunk.type=="usage"` 的收集 `data.chunk.usage`；取 `totalTokens` 最大者（None 视为 -1，全 None 取最后一个非空）；映射 `inputTokens→input_tokens`、`outputTokens→output_tokens`、`totalTokens→total_tokens`（仅映射存在的键，用 `_coerce_non_negative_int`）；无命中返回 `{}`；非 dict event 安全跳过。
  - `tests/test_dsh_backend.py`：新增 3 测试——① 真实结构 fixture（含 cacheReadTokens/reasoningTokens）→ 返回 `{"input_tokens":189,"output_tokens":149,"total_tokens":8146}`；② 无 usage 事件 → `{}`；③ 多 chunk（totalTokens 非单调/含 None）→ 取最大 totalTokens 者。
- **修改边界**：不改 `_normalize_token_usage` / `_runtime_cost_and_token_fields` / `_run_dsh_sdk_dispatch`；不改 tests/test_orchestrator.py
- **质量检查方式**：`uv run ruff check src/loop_kit/_core.py tests/test_dsh_backend.py`（0 error）；`uv run python -m py_compile src/loop_kit/_core.py`
- **测试命令**：`uv run --group dev pytest tests/test_dsh_backend.py -q`
- **验收标准**：
  - ✅ 新 3 测试通过；既有 8 个 dsh 测试零回归
  - ✅ helper 对空列表/非 list/畸形 dict 返回 `{}` 不抛异常
- **潜在风险**：低。未来若出现顶层 usage 事件，helper 需扩展（假设 4 哨兵测试覆盖）
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断

#### Task 1.2: `_run_dsh_sdk_dispatch` 增加 kw-only `usage_callback` + 单测
- **目标**：在成功路径将提取到的 usage payload 经 callback 传出；5 元组返回契约不变
- **依赖**：T1.1
- **frontier**：否（依赖 T1.1 helper）
- **执行者**：Task Executor
- **修改内容**：
  - `src/loop_kit/_core.py`（:2899-3005）：签名末尾追加 kw-only `usage_callback: Callable[[dict[str, object]], None] | None = None`；在 `returncode = 0 if ...`（~:3000）之后、events 摘要循环附近：`usage_payload = _extract_dsh_usage_payload(result.events)`；`if usage_callback is not None and usage_payload: usage_callback(usage_payload)`。早退路径（ImportError/HarnessError/error/timeout/no-result）一律不调用。
  - `tests/test_dsh_backend.py`：新增 2 测试——① `_ok_result` 扩展 usage chunk 后，`usage_callback` 收到 `{"input_tokens":189,...}` 且 5 元组断言与既有测试一致（stdout/session_id/rc 不变）；② 无 usage → callback 不被调用（决策 A 路径）。
- **修改边界**：不改返回值结构/顺序/类型；不改 `_report_dispatch_result`；不改 subprocess 任何代码
- **质量检查方式**：`uv run ruff check src/loop_kit/_core.py tests/test_dsh_backend.py`（0 error）
- **测试命令**：`uv run --group dev pytest tests/test_dsh_backend.py -q`
- **验收标准**：
  - ✅ 10 个 dsh 测试全绿（8 既有 + 2 新）；5 元组断言在既有测试中逐字不变
  - ✅ 无 usage_callback 调用（全部既有调用点）行为不变
- **潜在风险**：低。callback 仅成功路径触发——与"失败路径 cost_cents=0"设计一致
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断

#### Task 1.3: `_report_dispatch_result` runtime_fields merge + `_run_auto_dispatch` 接线 + 测试
- **目标**：in-process dsh 的 `dispatch_complete`/`dispatch_fail` 携带 cost/token 字段；subprocess 路径零变化
- **依赖**：T1.2
- **frontier**：否
- **执行者**：Task Executor
- **修改内容**：
  - `src/loop_kit/_core.py` `_report_dispatch_result`（:3182-3237）：新增 kw-only `runtime_fields: dict[str, object] | None = None`；在 `data` 构造/更新完成后、`_feed_event` 之前：`if runtime_fields: data.update(runtime_fields)`（位置：task_mode merge 之后 ~:3232）。
  - `src/loop_kit/_core.py` `_run_auto_dispatch`：① `run_fn = _require_registered_backend(backend)[3]`（~:3750）后初始化 `dsh_usage_payload: dict[str, object] = {}`；② in-process run_fn 调用（~:3777-3784）追加 `usage_callback=lambda payload: dsh_usage_payload.update(payload)`；③ if/else 合并后（~:3792，`if first_meaningful_summary_ms is None:` 块之前）单点计算 `report_runtime_fields: dict[str, object] | None = None` + `if run_fn is not None: report_runtime_fields = _runtime_cost_and_token_fields(dsh_usage_payload, backend=backend)`；④ 共享报告点 :3908（timeout）与 :3949（正常）追加 `runtime_fields=report_runtime_fields`。:3861 KeyboardInterrupt 报告点不传（subprocess 独有）。
  - `tests/test_dsh_backend.py`：新增 loop 级测试——monkeypatch `_require_registered_backend` 返回 `(None, None, None, fake_run_fn)`（fake 签名兼容含 `usage_callback` kwarg，先调用 `usage_callback({"input_tokens":189,"output_tokens":149,"total_tokens":8146})` 再返回 `("OK","",0,False,"sess")`）、`_require_registered_parse_event` 返回 `_dsh_parse_event`、`_feed_event` 捕获列表；调用 `_run_auto_dispatch("worker","dsh","hi",30, dispatch_retries=0, paths=None)`；断言捕获的 `dispatch_complete` data：`cost_cents==1`（ceil((189*43+149*129)/1e6)）、`input_tokens==189`、`total_tokens==8146`、`backend=="dsh"`；再以 fake 返回 `("",msg,-9,True,None)` 断言 `dispatch_fail` 含 `cost_cents==0`（决策 A）。
  - `tests/test_orchestrator.py`（仿 :16737 test_task_mode_feed_passthrough 模式）：新增 2 测试——① `_report_dispatch_result(runtime_fields={"cost_cents": 7, "total_tokens": 100})` → `dispatch_complete` data 含两键；② 不传 runtime_fields → data 无 `cost_cents` 键（subprocess 零变化回归哨）。
- **修改边界**：不改费率表；不改 `_normalize_token_usage`；不改 tests/test_dsh_backend.py 既有 8 测试的断言
- **质量检查方式**：`uv run ruff check src/loop_kit tests`（0 error）；`uv run python -c "from loop_kit import orchestrator"`
- **测试命令**：`uv run --group dev pytest tests/test_dsh_backend.py tests/test_orchestrator.py -q`
- **验收标准**：
  - ✅ loop 级测试断言 dispatch_complete cost_cents/token 字段与 dispatch_fail cost_cents=0
  - ✅ 全部 777 passed 不回归（V1 全量复核）
- **潜在风险**：中。`_run_auto_dispatch` 接线若误伤共享路径，subprocess 事件会多出 cost 字段——由"不传 runtime_fields → 无 cost_cents 键"回归哨测试 + 既有全量测试双重防护
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier（无人挡即刻开工） | 依赖已完成 |
|------|------------|--------------------------|------------|
| W1 | T1.1 | T1.1 | — |
| W2 | T1.2 | T1.2 | W1 |
| W3 | T1.3 | T1.3 | W2 |

提交纪律：每 task 独立 commit，message 前缀 `#3371` 并注明 task 号（如 `#3371 T1.1: add _extract_dsh_usage_payload`）；commit 前 `git diff --stat` 确认仅 `src/loop_kit/_core.py` + `tests/` 被 stage（负向验证规则）。

## Post-Execution Verification

Dev Orchestrator 在所有 plan task 执行完毕后**必须**运行本节验证命令。

### Automated Verification（Dev Orchestrator 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量回归 | `uv run --group dev pytest -q` | 777 passed / 0 failed（执行前先 `--collect-only -q \| tail -1` 重测基线；新增测试后 passed ≥ 基线+7） |
| V2 | 静态检查 | `uv run ruff check src/loop_kit tests` | exit 0，0 error |
| V3 | 编译+导入冒烟 | `uv run python -m py_compile src/loop_kit/_core.py && uv run python -c "from loop_kit import orchestrator"` | exit 0 |
| V4 | commit 范围核查 | `git log --oneline -3` + 逐 commit `git diff-tree --no-commit-id --name-only -r HEAD~1` | 每 commit 仅含 `src/loop_kit/_core.py` 或 `tests/` 文件 |

### Manual Verification（三级分类）

### Deferred (needs restart / deployment)
- [ ] D1: 无（本计划不涉及服务重启）

### Probe (best-effort, run if available)
- [ ] P1（真机 1 次验证，无破坏）：本机已装 deepseek-harness-sdk 且凭据有效时执行——
  `uv run python - <<'EOF'`（import orchestrator 后 `_run_auto_dispatch("worker", "dsh", "Reply OK, one sentence only.", 300, dispatch_retries=0, task_id="PM3371-PROBE", round_num=1)`），随后定位 feed 文件（`orchestrator._route_feed_event({}, paths=None)[0]`）并打印最后一条 `dispatch_complete`/`dispatch_fail`，断言 `cost_cents` 键存在且为 int。SDK/凭据不可用 → 标注 `[⚠️ SKIP: dsh-sdk/credentials unavailable]` 不阻塞交付。

### Manual（真正需要人工判断）
- [ ] M1: 人工阅读 P1 输出的 feed 事件行：cost_cents>0、input/output/total_tokens 数值与本次会话量级合理（数值直觉检查）
- [ ] M2: 人工核对 subprocess 派发的一次 dispatch_complete 事件**不**含 cost_cents（形态零变化抽查）

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性 | 1 | 1 | 0 |
| R1.5 | 外部引用事实核查 | 0 | 0 | 0 |
| R2 | 可执行性（含脚本干跑） | 1 | 1 | 0 |
| R2.8 | LLM 可执行性审查 | 0 | 0 | 0 |
| R3 | 风险与边缘（含跨轮一致性） | 1 | 1 | 0 |
| **终止** | **T4 — 全绿：3 任务可逐条执行，无残留歧义** | | | **0** |

- R1 修正：补 `_route_feed_event` 定位命令（真机探针依赖）。
- R2 修正：loop 级测试 fake run_fn 需接受 `usage_callback` kwarg（T1.3 步骤已写明），避免签名不匹配。
- R3 修正：明确 runtime_fields 计算单点置于 if/else 合并后（非两处重复计算），并确认 3861 报告点不传参。

## Execution Log

（Dev Orchestrator 执行后回写；失败时以 `mode=improve` 重入本计划）

## Execution Log

### [2026-09-05] 执行完成（Dev Orchestrator，3/3 任务 ✅）

- **T1.1 ✅**（commit b99202f）：`_extract_dsh_usage_payload`——从 assistant/chunk 事件提取 usage（camelCase→snake，取 totalTokens 最大者）+ 3 单测。
- **T1.2 ✅**（commit 9790b9e）：`_run_dsh_sdk_dispatch` 加 kw-only `usage_callback`（5 元组契约不变）+ 2 单测。
- **T1.3 ✅**（commit 8bb3612）：`_report_dispatch_result` 加 `runtime_fields` merge；`_run_auto_dispatch` in-process 分支经 usage_callback 采集 → `_runtime_cost_and_token_fields` 计算 → 注入 timeout 与正常两报告点 + 2 loop 级测试。
- **Post-Execution Verification**：V1 全量 784 passed/1 skipped/3 deselected（基线 777 + 7 新增）；V2 ruff 0 error；V3 编译+导入 OK；V4 3 commit 均仅 2 文件。
- **P1 真机探针 ✅**（1 次真实 dispatch）：`dispatch_complete` data = `{cost_cents: 1, input_tokens: 9579, output_tokens: 3, total_tokens: 9582}`——M1 数值直觉核对：ceil((9579*43+3*129)/1e6)=ceil(0.4123)=1 ✓。
- **M2 ✅**（代码级代偿）：subprocess 路径三报告点（KeyboardInterrupt/timeout/正常）均不传 runtime_fields → 事件形态零变化；"不传 runtime_fields → 无 cost_cents 键"由既有全量测试 + 负向回归哨覆盖。
- **决策 A 落地**：无 usage 事件时 `_runtime_cost_and_token_fields({})` → `{"cost_cents": 0}`（字段在、值为 0），成功与失败路径均附 cost。

**偏差汇总**：
- [D1] report_runtime_fields 计算点从计划 D4 的"if/else 合并后（first_meaningful 块之前）"微调——实测 timeout 报告点在 first_meaningful 块内、正常报告点在块外，计算点须在两者可见的共享作用域（if 块之前）；行为与计划意图一致
- [D1] lambda 闭包 loop 变量用 default-arg 绑定（ruff B023）
- 无越界改动
