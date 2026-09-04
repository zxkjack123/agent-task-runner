# dsh ACP 连通性冒烟结果（PM #2665 T3.1，stretch）

- 日期：2026-09-05
- 结果：**ACP_OK**（连通性验证通过）

## 冒烟记录

| 项 | 值 |
|----|-----|
| 前置探测 | subagent-acp 插件在 SDK runtime 二进制闭包内（strings 命中 `@deepseek-ai/dsh-subagent-acp`）✅ |
| opencode acp server | `opencode acp` 可用（opencode 1.18.28）✅ |
| 组合加载 | `DeepSeekHarness(patches=(cordis.patch.yml,))` start 成功 ✅ |
| 冒烟 prompt | 委派 opencode 子代理执行 `echo ACP_OK` |
| 结果 | final_response 含 `ACP_OK` ✅；notifications=1987（含 session.event/session.status/subagent 通知流） |
| 观察 | 根会话仍有 sandbox backend 警告（bash 通道限制），但 ACP 委派的子代理执行成功——ACP 路径绕开了根会话的 sandbox 限制 |

## 证据路径

- patches 文件：`coupling/dsh-acp-smoke/cordis.patch.yml`
- 命令形态：`opencode acp`（providerName=acp, command=opencode, args=["acp"], permission=reject）

## 结论

dsh（SDK 运行时 + subagent-acp 插件）作为 ACP client 委派 opencode acp server 的连通性**验证通过**（initialize + prompt 级）。未接入主流程（本 task 为 stretch，不改变 backend 注册形态）。
