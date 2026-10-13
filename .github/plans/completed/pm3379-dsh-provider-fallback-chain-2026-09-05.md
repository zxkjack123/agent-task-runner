# Plan: dsh backend 多 provider fallback chain（PM #3379）

- **revision**: 1（2026-09-05，生成时 HEAD=457c6e7）
- **scope_mode**: HOLD — bug/常规改造，触达仅 `src/loop_kit/_core.py` + `tests/test_dsh_backend.py` 两文件，严禁范围漂移
- **Clarify Gate**: PASS — 用户已提供 SDK 0.1.2rc1 实测 + task-fit 复核，5 项歧义均已消解
- **plan_owner**: Plan Architect → handoff: dev-orchestrator

## 背景与目标

- **问题**：dsh in-process（SDK）派发单渠道硬编码，deepseek 官网故障即整派发失败，无回退。
- **目标**：`_run_dsh_sdk_dispatch` 支持按优先级顺序的渠道列表（默认 deepseek 官网在前、360ai 在后），故障类错误自动回退下一渠道，顺序可 env 配置（调换顺序不改代码）。
- **非目标**：业务失败 `finish_reason != completed` 不回退；不改 5 元组返回契约（`tests/test_dsh_backend.py` 既有测试依赖）；不动费率 `_BACKEND_TOKEN_COST_CENTS_PER_MILLION[BACKEND_DSH]=(43,129)`（:433，分渠道费率是 follow-up）；不改 subprocess 三后端（run_fn 仅注册 BACKEND_DSH）。

## 实证基线（已核实，执行时重测锚点）

- SDK 0.1.2rc1 实测：`DeepSeekHarnessConfig` 含 `base_url`/`api_key` 字段；`DeepSeekHarness.__init__` 内 `if self.config.base_url is not None: env["DEEPSEEK_BASE_URL"]=...`（api_key 同理→`DEEPSEEK_API_KEY`）。**provider 字符串不影响端点**，决定性的是 base_url；多渠道切换 = 切 base_url+api_key 组合。**注意**：harness 映射的 env 变量名硬编码为 `DEEPSEEK_BASE_URL`/`DEEPSEEK_API_KEY`（不随渠道变），360 的 URL/key 值也写入同名 env——运行时以值为准。
- HarnessError 故障子类 3 个（均直接继承 HarnessError）：`JsonRpcError`/`SdkProtocolError`/`TransportClosedError`；业务失败 = `finish_reason != completed`（正常 return，非异常）。
- 关键锚点（HEAD=457c6e7）：`_run_dsh_sdk_dispatch` 定义 :2946、docstring :2956-2962、provider/model 读取 :2975-2976、max_tokens :2977-2980、patches :2986-2989、`DeepSeekHarness(...)` 构造 :2996-3004（**当前不传 base_url/api_key**）、thread start+join :3010-3017、超时分支 :3019-3024、error 分支 :3026-3034、result/finally :3036-3043、业务 finish_reason :3045-3048、usage_callback :3049-3052、summary 事件 :3053-3056、`register_backend(BACKEND_DSH, ..., run_fn=_run_dsh_sdk_dispatch)` :3063；`_log` :1708；dsh 区起始 :2836。
- 既有 env 命名族：`LOOP_DSH_PROVIDER`/`LOOP_DSH_MODEL`/`LOOP_DSH_MAX_TOKENS`/`LOOP_DSH_PATCHES`。测试文件 `tests/test_dsh_backend.py`（458 行）：`_install_fake_module` 注入 fake `deepseek_harness`/`deepseek_harness.errors`（`HarnessError=FakeHarnessError`），fake harness `run()` 返回 result。

## 关键设计决策（显式化）

- **D1 渠道配置形态**：新 env `LOOP_DSH_PROVIDER_CHAIN`（逗号分隔渠道 id）。缺省/空串 → 单渠道 `["deepseek"]`（**向后兼容**：今天 loop_kit 从不注入 base_url，端点恒为内置官网，单 deepseek 默认=既有行为）。每渠道 base_url 由 env `LOOP_DSH_BASE_URL_<CH_UPPER>` 覆盖，缺省回落内置表；每渠道 api_key 从内置表的 `api_key_env` 名读取（deepseek→`DEEPSEEK_API_KEY`、360ai→`AI360_API_KEY`），读到的**值**作为 harness `api_key` kwarg 传入（不是把 env 名传进去）。模块级内置表：
  - `deepseek` → base_url `https://api.deepseek.com/v1`、api_key_env `DEEPSEEK_API_KEY`
  - `360ai` → base_url `https://api.360.cn/v1`、api_key_env `AI360_API_KEY`
  - 未知渠道 id → 显式 fail-loud（`return ("", f"dsh config error: unknown channel {cid}", 1, False, normalized_sid)`），不静默跳过。
- **D2 默认值**：`deepseek`（单官网，**非** `deepseek,360ai`）。启用 360 由用户显式设 `LOOP_DSH_PROVIDER_CHAIN=deepseek,360ai`。理由：向后兼容 + 不擅自改变现有部署端点。
- **D3 故障子类判定方式**：fallback 谓词 = `isinstance(exc, HarnessError)`（覆盖 3 个故障子类）。业务失败是正常 return（不在异常路径）→ 天然不进 fallback。非 HarnessError 的 `BaseException` = 意外内部 bug → fail-loud（不回退，沿用既有 "dsh-sdk error" 行为）。风险：若未来 SDK 有非故障 HarnessError 子类，需收紧为显式三元组（见风险矩阵）。
- **D4 超时语义**：整派发 budget 不变（**单个**外层 `worker.join(timeout=...)` 仍是总预算）；fallback 是**异常驱动**而非时间切片——一个渠道抛故障异常即回退，不按时间切分 per-provider 预算。`timed_out=True` 语义 =「整个预算耗尽时渠道仍在挂起」（悬挂渠道无法在预算内回退，由外层 close harness 触发 `TransportClosedError` 但此时已超时返回）。`request_timeout_seconds` 保持不设（沿用 :3014-3016 注释语义）。
- **D5 provider 透传**：`provider` kwarg 传**渠道 id**（身份标识，不影响端点）；`model` 保持全局 `LOOP_DSH_MODEL`（渠道无关）。`base_url`/`api_key` 以 kwargs 传入 harness（config 字段），harness 内部映射到硬编码 env 名。usage_callback 仅对**成功渠道**调用一次（:3049-3052 逻辑不变，移到赢渠道 return 路径）。

## 假设清单

1. `[假设: 360ai 与 deepseek 官网同为 OpenAI 兼容端点，SDK runtime 仅读 `DEEPSEEK_BASE_URL`/`DEEPSEEK_API_KEY` env 名判定端点与密钥]` — 由 SDK 实测 D1/D2 支撑；若 runtime 实际读的是 `AI360_*` 命名的 env 则需调整 D5 注入方式（低影响，测试已用 kwargs 断言隔离）。
2. `[假设: 网络类故障均以 HarnessError 子类上抛（TransportClosedError/JsonRpcError），无裸 requests.ConnectionError 泄漏]` — 由 SDK 实测 3 子类支撑；高影响若错（fallback 漏捕网络异常）→ 缓解：D3 谓词预留扩展为显式 tuple 的位置，真机联调发现再补。
3. `[假设: 现有部署无人依赖 `LOOP_DSH_PROVIDER` 改变端点行为]` — 该 env 现仅透传标识（端点由内置默认决定），D5 改由渠道 id 派生 provider；若有人依赖此 env 显示名，属外观级差异，可接受。

## 执行计划

每 Phase 首步强制**基线漂移重检**：`git rev-parse HEAD` + `git status --porcelain`，与 `457c6e7` 假设漂移（目标文件被改/行号移动）→ 先更新锚点再动手。每 task 独立 commit（message 含 `#3379`），只 stage `src/loop_kit/_core.py` + `tests/test_dsh_backend.py`。

### Phase 1: 渠道配置面 + base_url/api_key 接线

#### Task 1.1: 渠道表 + resolver + 单渠道接线（向后兼容）
- **目标**：新增渠道配置面，把 base_url/api_key 接入既有单次 `DeepSeekHarness` 构造（task-fit「前提纠正」：当前 :2996-3004 从不传 base_url/api_key，是新增工作）。
- **依赖**：无
- **frontier**：是
- **执行者**：Task Executor（dev-orchestrator 路由）
- **修改内容**：
  - `src/loop_kit/_core.py`：dsh 区（:2836 之后、`_build_dsh_command` 前）新增模块级常量 `_DSH_DEFAULT_CHANNELS: dict[str, dict[str, str]]`（D1 表）+ helper `_resolve_dsh_channels() -> list[tuple[str, str, str]]`（返回 `(channel_id, base_url, api_key)` 列表；解析 `LOOP_DSH_PROVIDER_CHAIN`，缺省→`["deepseek"]`，每渠道 base_url 取 `LOOP_DSH_BASE_URL_<CH_UPPER>` 覆盖否则内置默认，api_key 取 `os.environ.get(api_key_env, "")`）。
  - `src/loop_kit/_core.py` `_run_dsh_sdk_dispatch` 主体（:2975 附近）：调用 `_resolve_dsh_channels()`，未知渠道 id 时 `ValueError` 或直接 return 配置错误元组（fail-loud）；`provider=provider` 行替换为取 `channels[0]` 的 id/base_url/api_key；`DeepSeekHarness(...)`（:2996-3004）新增 `base_url=..., api_key=...` 两个 kwarg。
  - `tests/test_dsh_backend.py`：新增 resolver 单测（缺省单渠道 / 逗号分隔 / 空串 / 空白 / base_url env 覆盖 / api_key 值读取）；断言 `FakeHarness.instances[0].kwargs["base_url"]=="https://api.deepseek.com/v1"` 且 `kwargs["api_key"]==<DEEPSEEK_API_KEY 值>`。
- **修改边界**：不改 `_run_in_worker` 线程结构；不改 5 元组契约；不改 subprocess 后端；不引入 fallback 循环（T1.2 做）。
- **质量检查方式**：`uv run --group dev pytest tests/test_dsh_backend.py -q`；`uv run ruff check src/loop_kit/_core.py tests/test_dsh_backend.py`
- **验收标准**：✅ resolver 缺省返回 `[("deepseek", "https://api.deepseek.com/v1", <key>)]`；✅ 未知渠道 id fail-loud（returncode 1，stderr 含 "unknown channel"）；✅ 既有 8 个 run_fn 测试仍绿（5 元组不变、kwargs 新增 base_url/api_key 不影响既有断言）。
- **潜在风险**：base_url/api_key 位置传错导致 fake harness kwargs 断言漂移——用 kwargs 名显式断言规避。
- **预留歧义标注**：[ ] 无歧义：resolver 返回形状与 fail-loud 语义已定，可直接执行。

#### Task 1.2: fallback 循环（异常驱动）
- **目标**：`_run_in_worker` 内按渠道顺序循环，`HarnessError`（故障）→ close+记日志+下一渠道；成功（取到 result）→ 记录赢渠道+result+harness 后 return；非 HarnessError `BaseException` → 记录 error 后 return（fail-loud）。单外层 thread join 不变（D4）。
- **依赖**：T1.1
- **frontier**：是（T1.1 完成后）
- **执行者**：Task Executor
- **修改内容**：
  - `src/loop_kit/_core.py` `_run_in_worker`（:2994-3008）：改为 `for cid, base_url, api_key in channels:` 循环；每迭代构造 `DeepSeekHarness(provider=cid, model=model, max_tokens=..., cwd=..., dsh_home=..., env={"DSH_SESSION_ROOT": ...}, patches=..., base_url=base_url, api_key=api_key)` 后立即 `result_holder["harness"]=h`（供超时分支 close 当前渠道）；`h.run(prompt, session_id=normalized_sid)` 成功 → `result_holder["result"]=result; result_holder["channel"]=cid; return`；`except HarnessError as exc:` → `last_error=exc`，close h，`_log(f"[dsh] channel {cid} fault ({type(exc).__name__}): {exc}; falling back")`，`continue`；`except BaseException as exc:` → `result_holder["error"]=exc; return`。循环耗尽 → `result_holder["error"]=last_error or RuntimeError("no dsh channels"); result_holder["exhausted"]=True`。
  - `_run_dsh_sdk_dispatch` error 分支（:3026-3034）：`exhausted` 为真时返回 `("", f"dsh all channels failed (last: {type(exc).__name__}: {exc})", 1, False, normalized_sid)`；否则维持既有两分支。超时分支（:3019-3024）不动。
  - `tests/test_dsh_backend.py`：新增 `FakeFaultingHarness`（`run()` raise `FakeHarnessError`，构造成功）+ 按 `kwargs["base_url"]` 分流的工厂；测试①双渠道第一故障第二成功（returncode 0、session 取第 2 渠道、`len(FakeHarness.instances)==2`、两个 harness 的 base_url 分别为 deepseek/360ai）；②全渠道故障（returncode 1、stderr 含 "all channels failed"、`len==2`）；③非 HarnessError 异常（如 `RuntimeError`）→ 只用 1 渠道 fail-loud 不回退。
- **修改边界**：不触碰 finish_reason 业务分支（:3045-3048）；不引入 per-provider 超时；不改外层 join。
- **质量检查方式**：`uv run --group dev pytest tests/test_dsh_backend.py -q`
- **验收标准**：✅ 双渠道 fault→success 回退生效且两渠道 base_url 各异；✅ 全故障 returncode 1 + "all channels failed"；✅ 非 HarnessError 不回退；✅ 既有 8 测试仍绿。
- **潜在风险**：fake harness 分流逻辑（按 base_url）与真实 kwargs 键名耦合——用 kwargs 显式断言；`except HarnessError` 需捕获闭包内的 HarnessError（:2965 已导入，闭包可达）。
- **预留歧义标注**：[ ] 无歧义：回退谓词与循环边界已定。

### Phase 2: 语义收口 + 文档 + 回归

#### Task 2.1: 业务失败不回退 + usage_callback 单次 + docstring 修正
- **目标**：确认业务失败（`finish_reason=error`）是正常 return 不触发回退；usage_callback/summary_callback 仅赢渠道调用一次；修正 :2959-2962 docstring「config is a DeepSeekHarnessConfig dataclass」的漂移。
- **依赖**：T1.2
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**：
  - `src/loop_kit/_core.py` docstring（:2956-2962）：改为准确描述「多渠道 fallback：渠道列表 env `LOOP_DSH_PROVIDER_CHAIN`，故障类 HarnessError 回退下一渠道，业务 finish_reason 不回退」；移除「config is a DeepSeekHarnessConfig dataclass」误导句（:2996-3004 是 kwargs 直传）。
  - `src/loop_kit/_core.py`：确认 :3049-3052 usage_callback 与 :3053-3056 summary 循环保持在赢渠道 result 取得后的 return 路径（回退成功的渠道 result 即赢渠道 result，无需额外改动；仅需在代码注释标注「仅赢渠道」语义）。
  - `tests/test_dsh_backend.py`：新增①业务失败（`FakeRunResult(..., finish_reason="error")`）+ 双渠道 env → 断言 `len(FakeHarness.instances)==1`（不回退）、returncode 1；②双渠道第一故障第二成功 + usage_callback → 断言 callback 收到**一次**且来自第 2 渠道 events。
- **修改边界**：不改 `_normalize_token_usage`/`_runtime_cost_and_token_fields`/费率；不改 `_report_dispatch_result`。
- **质量检查方式**：`uv run --group dev pytest tests/test_dsh_backend.py -q`
- **验收标准**：✅ 业务失败单渠道、不回退；✅ usage_callback 仅赢渠道一次；✅ docstring 无「dataclass」误导句；✅ 既有测试绿。
- **潜在风险**：docstring 改动触及 :2959 原句需精确匹配——用 edit 精确 oldString。
- **预留歧义标注**：[ ] 无歧义。

#### Task 2.2: 配置解析矩阵 + 全量回归
- **目标**：env 解析边界硬化 + 全量回归（subprocess 后端零影响确认）。
- **依赖**：T2.1
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**：
  - `tests/test_dsh_backend.py`：新增配置解析矩阵测试——`LOOP_DSH_PROVIDER_CHAIN` 为 `deepseek,360ai`（两渠道）、`deepseek, 360ai`（空白容忍）、`deepseek,`（尾逗号丢弃空）、空串/未设（单 deepseek）、`360ai,deepseek`（顺序反转生效：第一 harness base_url=360）；`LOOP_DSH_BASE_URL_360AI` 覆盖生效；`LOOP_DSH_MODEL` 全局透传（两渠道 harness 的 model kwarg 一致）。
  - `src/loop_kit/_core.py`：无生产代码改动（仅测试），除非 resolver 解析空白/尾逗号有遗漏则补。
  - 回归确认：`register_backend` 区 :3060-3063 未动；subprocess 三后端（codex/claude/opencode）register 未动。
- **修改边界**：不改任何 subprocess 派发路径；不改 `_run_auto_dispatch`。
- **质量检查方式**：`uv run --group dev pytest`（全量）；`uv run ruff check src/loop_kit tests`；`uv run python -m py_compile src/loop_kit/_core.py`；`uv run python -c "from loop_kit.orchestrator import *"`
- **验收标准**：✅ 全量 pytest 绿（含既有 615+）；✅ ruff 0 error；✅ py_compile 通过；✅ 解析矩阵全通过。
- **潜在风险**：尾逗号/空白解析 bug——resolver 用 `[c.strip() for c in raw.split(",") if c.strip()]` 已覆盖。
- **预留歧义标注**：[ ] 无歧义。

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|------------|
| W1 | T1.1 | T1.1 | — |
| W2 | T1.2 | T1.2 | W1 |
| W3 | T2.1 | T2.1 | W2 |
| W4 | T2.2 | T2.2 | W3 |

（严格串行：每 task 都改 `_core.py` 的 `_run_dsh_sdk_dispatch` 区域，同文件同区，不可并行。）

## Post-Execution Verification

### Automated Verification（Dev Orchestrator 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量单测 | `uv run --group dev pytest` | exit 0，无失败 |
| V2 | 静态检查 | `uv run ruff check src/loop_kit tests` | 0 error |
| V3 | 编译检查 | `uv run python -m py_compile src/loop_kit/_core.py` | exit 0 |
| V4 | 导入检查 | `uv run python -c "from loop_kit.orchestrator import *"` | exit 0 |
| V5 | commit 范围负向验证 | `git diff --stat`（每次 commit 前） | 仅 `src/loop_kit/_core.py` + `tests/test_dsh_backend.py` |

### Probe (best-effort, run if available)

- [x] P1: `grep -n "LOOP_DSH_PROVIDER_CHAIN\|LOOP_DSH_BASE_URL_\|_resolve_dsh_channels" src/loop_kit/_core.py` 确认三符号落位 dsh 区，无拼写漂移。（回填 2026-10-13：本计划 Execution Log 已记 P1 PASS——三符号落位 _core.py:2845-3034）

### Manual（真正需要人工判断）

- [ ] M1: 真机联调（可选，follow-up）：设 `LOOP_DSH_PROVIDER_CHAIN=deepseek,360ai` + 两 key，断官网触发 360 回退，读 `_log` 输出确认「channel deepseek fault ... falling back」链路。属 follow-up，不阻塞本计划验收。

## 风险矩阵

| Risk | Impact | Mitigation |
|------|--------|------------|
| 网络故障以非 HarnessError 异常上抛（假设 2 错） | 回退漏捕，fallback 失效 | D3 谓词预留显式 tuple 位置；M1 真机联调确认 |
| SDK runtime 读非 `DEEPSEEK_*` env 名（假设 1 错） | 360 渠道密钥/端点不生效 | D5 注入方式可调；测试用 kwargs 断言隔离，改注入不改循环 |
| 悬挂渠道无法在预算内回退 | 超时场景无 fallback | D4 显式声明为已知限制（异常驱动，非时间切片） |

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（task 粒度/边界/契约） | 2 | 2 | 0 |
| R1.5 | 外部引用事实核查（行号/SDK 字段/测试锚点） | 3 | 3 | 0 |
| R2 | 可执行性（env 命名/异常谓词/线程语义） | 1 | 1 | 0 |
| R2.8 | LLM 可执行性（逐字段消除猜测） | 1 | 1 | 0 |
| R3 | 风险与边缘（回退/超时/向后兼容） | 2 | 2 | 0 |
| **终止** | **T4 — 全量回归绿 + 范围零漂移** | | | **0** |

## Execution Log

### Post-Execution Verification Log（2026-09-07，dev-orchestrator）

| ID | Command | Result |
|----|---------|--------|
| V1 | `uv run --group dev pytest` | ✅ PASS — 799 passed, 1 skipped (既有), 3 deselected (e2e) |
| V2 | `uv run ruff check src/loop_kit tests` | ✅ PASS — 0 error |
| V3 | `uv run python -m py_compile src/loop_kit/_core.py` | ✅ PASS — exit 0 |
| V4 | `uv run python -c "from loop_kit.orchestrator import *"` | ✅ PASS — exit 0 |
| V5 | 每 task commit 前 `git diff --stat` | ✅ PASS — 仅 `src/loop_kit/_core.py` + `tests/test_dsh_backend.py` |
| P1 | 符号落位 probe | ✅ PASS — 三符号均落 dsh 区（_core.py:2845-3034），无拼写漂移 |
| M1 | 真机联调（360 回退） | ⏸ follow-up（不阻塞验收） |

### Task 完成记录

- T1.1 ✅ `cdaf113`（前会话完成）
- T1.2 ✅ `b824ef1` — fault-driven fallback 循环 + 3 测试
- T2.1 ✅ `ab42e81` — docstring 修正 + 业务失败不回退 + winner-only usage + 2 测试
- T2.2 ✅ `e3a1a2a` — 配置解析矩阵 4 测试 + 全量回归

### 偏差清单（D1）

- [D1] T1.2: 既有 `test_dsh_run_fn_harness_error_returns_rc1` 断言更新（构造故障在 fallback 循环下必经 exhausted 路径，`"dsh HarnessError: ..."` → `"dsh all channels failed (last: ...)"`）— 行为由计划自身定义的新语义决定，范围一致，已记录。
- [D1] T1.2: 删除 `provider = os.environ.get("LOOP_DSH_PROVIDER", ...)` 读取行 — D5 落实（provider kwarg 改由渠道 id 派生），否则触发 ruff F841。
