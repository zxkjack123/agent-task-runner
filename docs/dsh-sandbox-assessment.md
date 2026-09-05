# dsh Sandbox Backend（landlock）本机可用性评估（PM #2665 follow-up 1 / #3357）

- 日期：2026-09-05
- 调研性质：只读（未 build、未修改 dsh fork、未全局安装）

## 结论（TL;DR）

**三要素全部满足，landlock 路径本机可用**：kernel 层 ✅ + SDK 闭包层 ✅ + 启用方式已探明（cordis patches 注入 sandbox-local 条目）。解锁 dsh 执行能力的前置条件已满足，下一步是 patches 注入验证（真机一次 SDK 加载探测即可确认）。

## 三要素证据

### 1. kernel 层支持结论：✅ 可用

| 探测 | 命令/方法 | 结果 |
|------|-----------|------|
| kernel 版本 | `uname -r` | `7.0.0-30-generic`（远高于 landlock 最低要求 5.13） |
| landlock syscall | `/proc/kallsyms` | `__x64_sys_landlock_add_rule` / `__do_sys_landlock_restrict_self` 存在 |
| 运行时探测 | Python `syscall(444, …)` = landlock_create_ruleset | **`LANDLOCK_AVAILABLE: create_ruleset fd=3`**（errno 0，成功创建 ruleset） |

### 2. sandbox 插件启用方式：✅ 已探明

- fork 结构：`packages/sandbox/`（服务+升级词汇）、`packages/sandbox/sandbox-local/`（本地平台后端：Linux landlock / macOS Seatbelt / Windows ACL）、`packages/sandbox/sandbox-policy/`（会话级策略）。
- landlock 后端 = `@deepseek-ai/node-addon-landlock-run`（原生 addon launcher）+ `landlockProfileArgs`；不可用时**fail-closed**（`SandboxUnavailableError`）——试点观察到的拒绝行为正是该 fail-closed 语义。
- **SDK runtime 闭包已含全部所需组件**（`strings` 探测 267MB 二进制）：
  - `@deepseek-ai/dsh-sandbox-local` ✅（strings 命中）
  - `@deepseek-ai/node-addon-landlock-run` + `-linux-x64` 平台包 ✅（strings 命中）
- **组合层缺口**：SDK 内置 cordis（profile=sdk）**未注册 sandbox 条目**——这是试点的真实阻断点。启用方式 = 与 T3.1 ACP 冒烟相同的 `patches` 机制注入条目：
  ```yaml
  # coupling/dsh-pilot/cordis.sandbox.patch.yml（示例形态，未验证）
  - id: sandbox
    name: '@deepseek-ai/dsh-sandbox-local'
  ```
  具体 config 键以 `packages/sandbox/sandbox-local/README.md` 与 `docs/subsystems/sandbox.md` 为准（patches 注入后需 SDK 加载探测确认，一次零 API 调用验证）。

### 3. 替代方案（若 patches 注入失败）

- **bwrap backend**：`which bwrap` = `/usr/bin/bwrap` ✅ 可用。sandbox-local 的 Linux 链含 bwrap 探测路径（`spawnSync('bwrap', …)` 功能探测）——即使 landlock addon 加载失败，bwrap 是成熟的第二选择。
- **宿主侧包装**（最后手段）：loop_kit 层在 dsh 派发前用 opencode 同款 42 条 deny 正则预检 prompt/工具调用——无运行时强制力，仅作计划失败 fallback（见任务 D 方案文档）。

## 实验证据汇总

```
$ uv run python -c "syscall(444, landlock_create_ruleset, …, 0)" → LANDLOCK_AVAILABLE: create_ruleset fd=3
$ which bwrap → /usr/bin/bwrap
$ strings <sdk-runtime-bin> | grep landlock → node-addon-landlock-run + linux-x64 平台包（闭包内）
$ strings <sdk-runtime-bin> | grep dsh-sandbox-local → 插件本体（闭包内）
```

## 修改边界

- 本评估零代码修改（纯调研）；fork 未 build、未修改；无全局安装。
- 后续验证动作（不属本任务）：构造 sandbox patches 文件 → `DeepSeekHarness(patches=(…,)).start()` 加载探测 → 确认 `sandbox/mode: workspace-write` 不再触发 "no sandbox backend" 拒绝。零 API 调用即可完成（start 级验证）。

## 与任务 D（#3359）的衔接

本评估结论为「landlock 可用 + patches 注入是启用路径」→ 任务 D 的 guard/approval 方案应以「patches 启用 sandbox + approval 策略映射」为主方案，宿主侧包装为 fallback。
