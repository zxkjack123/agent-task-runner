# dsh guard/approval 最小实现方案（PM #2665 follow-up 2 / #3359）

- 日期：2026-09-05
- 前置依据：任务 B（#3357）评估结论——**本机 kernel 7.0.0 支持 landlock（运行时探测 create_ruleset 成功）、bwrap 可用、sandbox-local 插件与 landlock-run addon 均在 SDK runtime 闭包内；启用路径 = cordis patches 注入 sandbox-local 条目**。

## 结论（TL;DR）

主方案 = **patches 启用 sandbox-local + approval 策略映射**（依赖已满足，只需注入条目 + 加载探测）；fallback = **宿主侧 deny 正则预检**（loop_kit 层，opencode 42 条 deny 同款语义）。本任务只出方案文档（含最小可执行步骤清单），不实现插件代码。

## 方案一（主）：patches 启用 dsh 原生 sandbox + approval

### 步骤清单（最小可执行）

1. **构造 sandbox patches 文件**（`coupling/dsh-pilot/cordis.sandbox.patch.yml`，形态参照 T3.1 ACP patches）：
   ```yaml
   - id: sandbox
     name: '@deepseek-ai/dsh-sandbox-local'
   ```
   （config 键需对照 `packages/sandbox/sandbox-local/README.md` 与 `docs/subsystems/sandbox.md` 核实；enforcement 默认 `workspace-write`。）
2. **零 API 加载探测**：`DeepSeekHarness(patches=(patch_path,)).start()`——成功判据 = 启动无 `SandboxUnavailableError`；随后 transcript 中出现 `sandbox/mode: workspace-write` 且 bash 调用不再被拒（可用一次 `echo OK` 工具调用验证，1 次 dispatch 预算）。
3. **approval 策略映射**（dsh 侧 `approval/policy` 旋钮，映射表骨架）：
   - opencode `--auto`（自动批准 + deny 例外）→ dsh `approval/policy: auto` + sandbox enforcement 承担 deny 的强制力
   - opencode 42 条命令级 deny → 由 sandbox confinement（landlock 文件系统写限制 + 无 root）承担等价强制——**如实声明：语义等价性为部分覆盖**（landlock 限制写路径 ≠ 禁止特定命令语法；`rm /etc/*` 类因无 root + landlock 写拒绝而失效，`reboot` 类因无权限失效，但如 `curl 外发` 类不在 landlock 覆盖内）
   - 剩余差距条目：外发网络（`webfetch` 类）、特定 agent 工具 deny（edit 等）→ 需 follow-up 自研 guard 插件（见方案二骨架）
4. **loop_kit 接线**（T1.1 已有基础）：`_run_dsh_sdk_dispatch` 的 `patches` 参数支持从 env `LOOP_DSH_PATCHES` 读取路径元组（当前硬编码为空）——约 5 行改动，使试点与后续 lane 可切换启用 sandbox。
5. **回滚**：不传 `LOOP_DSH_PATCHES` 即回滚到无 sandbox 状态（与 `--worker-backend dsh` 不传即回滚同构）。

### 风险与边界

- patches 注入失败（如 config 键形态漂移）→ 退方案二；不阻塞。
- sandbox 启用后 worker 执行能力需真机复验（1 次 dispatch 预算内）——这是 #2665 试点 CONDITIONAL 结论的翻转条件。
- 不伪装等价：映射表必须沿用权限映射文档的三栏格式（opencode 规则 / dsh 侧对应 / 差距声明）。

## 方案二（fallback）：宿主侧 deny 正则预检

若 patches 注入失败或 sandbox 强制力不足：

1. loop_kit `_run_dsh_sdk_dispatch` 入口增加预检函数 `_dsh_deny_precheck(prompt: str) -> str | None`：
   - 复用 opencode 42 条 deny 正则（命令级 20 条 + 路径级 17 条 + 工具级 5 条，来源 `docs/dsh-backend-permission-mapping.md` 附录）
   - 命中 → 返回错误信息（returncode 1，fail-closed，不进 API 调用）
   - 语义：**只对 prompt 文本做预检**，不拦截 agent 运行时生成的工具调用（诚实声明：这是静态预检，非运行时强制）
2. 该方案是弱保证（prompt 级），仅作主方案失败时的过渡；正式运行时强制仍依赖方案一或自研 guard 插件。

## follow-up（本方案不覆盖，列给后续任务）

1. 自研 guard 插件（dsh 侧 per-command regex deny 的运行时等价物）——依赖 dsh 插件 API 稳定
2. 网络外发管控（webfetch/websearch 的 dsh 等价 gate）
3. 42 条 deny 到 sandbox 语义的逐条映射验证（真机负向用例：构造越界工具调用 → 确认被拒）

## 与现有文档的关系

- 权限映射文档（`docs/dsh-backend-permission-mapping.md`）：差距声明的处置层更新为「方案一已启用 sandbox」或「方案二过渡中」
- 试点报告（`docs/dsh-pilot-report.md`）：follow-up 1/2 状态回写
