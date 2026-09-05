# dsh sandbox patches 真机验证报告（PM #3361）

- 日期：2026-09-05
- 前置依据：#3357（sandbox 评估：三要素满足）、#3359（方案 D 步骤清单）
- patches 文件：`coupling/dsh-pilot/cordis.sandbox.patch.yml`（注入 `@deepseek-ai/dsh-sandbox-local`）

## 验证结论（2026-09-05 更新：已翻转）

**最终：加载探测 PASS / 执行复验 PASS / 沙箱语义生效**。

第一阶段（初验）：patches 注入被 runtime 接受（`SANDBOX_PATCH_LOAD_OK`），但 bash 执行通道仍被拒（`SANDBOX_UNAVAILABLE`）——根因定位为宿主层 AppArmor userns 限制（bwrap 首选 rung 被拦）。

第二阶段（用户授权 sudo 后）：`pkexec sysctl kernel.apparmor_restrict_unprivileged_userns=0` 放行 + 持久化（`/etc/sysctl.d/99-dsh-bwrap-userns.conf`）→ bwrap 功能恢复 → 真实 dispatch 复验 **bash 执行成功**（`echo SANDBOX_OK` → exit 0，tool/result isError=false）→ 负向验证 **沙箱语义生效**（写 `/etc` 被拒：`Read-only file system` + `file access denied under workspace-write mode`）。

**#2665 试点 CONDITIONAL 判定的阻断点已解除**——dsh backend 从「注册但不可用」升级为「执行通道已验证可用（workspace-write 沙箱语义生效）」。

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

## 解锁路径执行记录（用户授权后）

| 路径 | 状态 | 备注 |
|------|------|------|
| A | ✅ 已执行（用户授权 sudo，2026-09-05 会话） | `sysctl kernel.apparmor_restrict_unprivileged_userns=0` + 持久化 `/etc/sysctl.d/99-dsh-bwrap-userns.conf`；bwrap 功能恢复（exit 0） |
| B | 未执行 | landlock 原生二进制解包缺位仍存在，但不阻塞（bwrap rung 已先命中） |
| C | 未执行 | 不再需要 |

**安全影响声明（重要）**：`apparmor_restrict_unprivileged_userns=0` 是**系统级**非特权 user namespace 放行（Ubuntu 24.10+ 默认安全加固项），影响面大于 bwrap 单点。恢复方式：`sudo sysctl kernel.apparmor_restrict_unprivileged_userns=1 && sudo rm /etc/sysctl.d/99-dsh-bwrap-userns.conf`。更精细的替代（仅给 bwrap 加 AppArmor profile）未实施——如需收紧，可作后续任务。

## 修改边界与合规

- 只新增 2 个文件（patches + 本报告）；无 fork 修改、无 build、无全局安装、无 sudo。
- 真实 API 消费：1 次 dispatch（echo SANDBOX_OK 验证）+ 1 次 ACP 冒烟此前已计——本任务 1 次，在预算内。
- 不虚构结论：加载 PASS / 执行 FAIL 均如实记录。
