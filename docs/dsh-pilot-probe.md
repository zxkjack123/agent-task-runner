# dsh SDK 环境探针报告（PM #2665 T4 试点 T0.1）

- 日期：2026-09-05
- 执行仓库：agent-task-runner（/home/gw/opt/agent-task-runner）

## 环境表

| 项目 | 值 |
|------|-----|
| uv | 0.12.0 |
| opencode | 1.18.28（计划记录 1.18.18，已升级，不影响本试点） |
| deepseek-harness-sdk | **0.1.2rc1**（PyPI 最新，计划撰写时基于 fork SESSION_FORMAT_VERSION=0 的旧 API） |
| deepseek-harness-runtime-bin | 0.1.2rc1（同版本） |
| venv runtime 目录 | `.venv/lib/python3.13/site-packages/deepseek_harness_runtime/runtime/` |
| dsh CLI | **未安装**（`which dsh` 空，与计划预期一致 → SDK-only 路径确认） |
| DEEPSEEK_API_KEY | SET（len 35，不打印明文） |

## 安装结论

**PASS** — SDK 与 runtime-bin 同版本 0.1.2rc1 装入 uv venv（未触碰 pyproject.toml/uv.lock，`git status` 无变更）。

## ⚠️ API 漂移记录（重要，T1.1/T1.2 实施必须适配）

计划（2026-08-16）基于 fork 旧 SDK 形态，安装的 0.1.2rc1 有破坏性 API 演进。逐项实测：

| 计划假设 | 0.1.2rc1 实际 | 适配方向 |
|----------|---------------|----------|
| `DeepSeekHarness(provider, model, max_tokens, cwd, session_root, cordis, env, ...)` 位置参数 | `DeepSeekHarness(config: DeepSeekHarnessConfig \| None, **kwargs)`；`DeepSeekHarnessConfig` 是 dataclass | 用 dataclass 或 kwargs 构造 |
| `session_root` 参数 | **已移除**。session 落盘由 sessions 插件 `root: !!js process.env.DSH_SESSION_ROOT ?? './.sessions'` 控制；`dsh_home`（→env `DSH_HOME`）为运行时主目录，**必填**（HarnessConfig 校验非空，否则 ValueError） | env 注入 `DSH_SESSION_ROOT=<绝对路径>` 达成 D6 隔离目标 |
| `cordis` 参数 | **已移除**，改为 `profile`（默认 "sdk"）+ `patches: tuple[str, ...]` | 默认 profile 走 SDK 内置 cordis；试点模板改为 patches 文件（T1.2 适配） |
| `RunResult(session_id, final_response, finish_reason, events, notifications, session_root)` 6 字段 | **5 字段**：无 `session_root` | 事件流/映射逻辑不变，session 路径由 env 控制 |
| `run(input, session_id=None)` | `run(input, *, session_id=None, on_notification=None)` 一致 | 直接可用 |
| `errors.HarnessError` 基类 + SdkProtocolError/JsonRpcError/TransportClosedError | 实测存在 ✓ | 异常映射按计划 |
| `harness.close()` / context manager | `__enter__/__exit__/start/close/start_session` 实测存在 ✓ | 超时护栏用 `close()` 解除阻塞调用，与计划一致 |

## 事件类型实测表（api.py 引用行号）

| 事件类型 | 证据（api.py 行号） |
|----------|--------------------|
| `assistant/message` | api.py:212（`event.get("type") != "assistant/message"`） |
| `turn/end` | api.py:236-245（`data.reason.kind` 必须为字符串） |
| `agent/inbox/spliced` | api.py:195（`event.get("type") != "agent/inbox/spliced"`） |

事件通过 `Notification(method="session.event", payload)` 流式到达，`RunResult.events` 为根会话事件列表——与计划的事件类型假设一致。

## venv runtime cordis 模板路径

venv 内 runtime 是单文件二进制（267MB），无独立 cordis.yml。fork 源码只读参考路径：
`/home/gw/opt/deepseek-harness/python/sdk-runtime/src/deepseek_harness_runtime/runtime/cordis.yml`（sessions 插件 `root: !!js process.env.DSH_SESSION_ROOT ?? './.sessions'`）。

**T1.2 适配**：SDK 内置 cordis 无 compression 配置键（新版 session-persistence-jsonl 默认行为待 T2.3 真机实证），试点模板的"compression:none"目标需在真机 transcript 落盘后实测格式再决定是否需要 patches 覆盖——探针无法在零 API 调用下确定。

## 事实记录

- `uv --version` → 0.12.0
- `opencode --version` → 1.18.28
- `DEEPSEEK_API_KEY` → SET / len 35
- `which dsh` → 空（CLI 缺席）
