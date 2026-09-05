# dsh sandbox patches 真机验证报告（PM #3361）

- 日期：2026-09-05
- 前置依据：#3357（sandbox 评估：三要素满足）、#3359（方案 D 步骤清单）
- patches 文件：`coupling/dsh-pilot/cordis.sandbox.patch.yml`（注入 `@deepseek-ai/dsh-sandbox-local`）

## 验证结论

**加载探测 PASS / 执行复验 FAIL**——patches 注入被 runtime 接受（`SANDBOX_PATCH_LOAD_OK`），但 bash 执行通道仍被拒（`SANDBOX_UNAVAILABLE`）。根因已在两个 rung 上精确定位，均为宿主/打包层问题，非 patches 形态错误。

## 证据链

### 1. 加载探测：✅ PASS（零 API）

```
DeepSeekHarness(patches=(cordis.sandbox.patch.yml,)).start()
→ SANDBOX_PATCH_LOAD_OK — runtime accepted the sandbox-local patch
→ CLOSE_OK
```

patches 形态正确（2 行条目，与 fork sandbox-local README 的 consumer 示例一致）。

### 2. 执行复验：❌ FAIL（1 次真实 dispatch）

prompt = "运行命令 echo SANDBOX_OK"；模型正确发起了 bash 工具调用（transcript 证据：`tool/call bash echo SANDBOX_OK`），但 tool/result 返回：

> `Error: sandbox mode "workspace-write" is requested but no sandbox backend is usable on this host; refusing to run the command unconfined. Install bubblewrap or run a Landlock-enforcing kernel (Linux)...`
> `{"name":"SandboxUnavailableError","code":"SANDBOX_UNAVAILABLE"}`

### 3. 根因定位（两个 rung 逐一定位）

**Rung 1 — bwrap（Linux chain 首选）**：
```
$ bwrap --ro-bind / / --dev /dev --proc /proc --unshare-pid true
→ bwrap: setting up uid map: Permission denied (exit 1)
$ cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns
→ 1
```
**本机 AppArmor 限制非特权 user namespace**（Ubuntu 24.10+ 安全策略）→ bwrap 的功能探测必然失败。

**Rung 2 — landlock（fallback）**：
- kernel 侧支持（#3357 已实证 `LANDLOCK_AVAILABLE`）
- 但 SDK 解包环境的 `@deepseek-ai/node-addon-landlock-run` 目录**只有 `entry-0.js` + `package.json`**（无 linux-x64 原生 `.node` 平台二进制）；`moduleFallback` 指向 `file:///snapshot/...` 单文件 exe 内部快照路径
- landlock launcher 探测在 SDK runtime 子进程中无法解析可执行的 landlock-run 二进制 → 判定 unusable

**结论**：chain `[bwrap, landlock]` 两 rung 全 unusable → `unavailable` → fail-closed（与 #2665 试点观察的拒绝行为同源，但现已定位到具体 rung）。

## 与 #2665 试点结论的关系

- #2665 的 CONDITIONAL 判定**维持**：执行通道阻断的根因从"未知"升级为"已定位"（AppArmor userns 策略 + SDK 打包缺原生二进制），但通道本身未解锁。
- #3357 评估的"三要素满足"需修正一处：kernel/bwrap 存在性满足，但 **bwrap 可用性不满足**（AppArmor 限制）——评估文档当时未覆盖此层（`which bwrap` 存在 ≠ 功能可用）。

## 解锁路径（后续候选，不属本任务）

| 路径 | 动作 | 可行性 |
|------|------|--------|
| A | 宿主级放行 bwrap：`sysctl kernel.apparmor_restrict_unprivileged_userns=0` 或给 bwrap 加 AppArmor profile | 需系统管理员权限（sudo），**需用户决策** |
| B | SDK 修复 landlock 原生二进制解包缺位 → 上游 issue | 上游问题，本机不可控 |
| C | dsh 消费方切 `danger-full-access`（无 sandbox 直跑） | 放弃沙箱语义，需明确接受风险才可用 |

## 修改边界与合规

- 只新增 2 个文件（patches + 本报告）；无 fork 修改、无 build、无全局安装、无 sudo。
- 真实 API 消费：1 次 dispatch（echo SANDBOX_OK 验证）+ 1 次 ACP 冒烟此前已计——本任务 1 次，在预算内。
- 不虚构结论：加载 PASS / 执行 FAIL 均如实记录。
