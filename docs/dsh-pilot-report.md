# dsh Headless Backend 试点报告（PM #2665 T2.3）

- 日期：2026-09-05
- 执行仓库：agent-task-runner（worktree `.loop/worktrees/dsh-pilot`，分支 `pilot/dsh-t4`，已保留未合并）
- 试点 base_sha：`b8618e51d82017e2a617c3a4b759669c2592b4f2`（master @ T2.1 task card commit）；试点 head_sha：同为 b8618e5（worker 无执行通道无法提交，head_sha==base_sha 即本试点的核心证据链之一）
- 实施完成时 master HEAD：`72303f5`（9 个 #2665 commit）
- 试点 task：`dsh-pilot-T4`（coupling/dsh-pilot/ fib 模块微任务）
- 预算声明：总真实 dispatch ≤4；实际消耗 **1 次 worker dispatch（148s）+ 1 次 SDK 冒烟探针**（另有 2 次 ImportError 快速失败未触达 API）；`--dispatch-retries 0`、`--max-rounds 2`、`--dispatch-timeout 1800`、`max_tokens ≤ 49152`

## 环境摘要

| 项 | 值 |
|----|-----|
| deepseek-harness-sdk | 0.1.2rc1（PyPI，与计划撰写时的 fork 旧 API 有破坏性漂移，探针已记录） |
| model | deepseek-v4-flash（默认） |
| dsh CLI | 未安装（SDK-only 路径确认） |
| 真实 dispatch 次数 | 1（worker）+ 1 冒烟 |

## 四指标评测结果

```
| 指标 | 名称 | 判定 | 详情 |
|------|------|------|------|
| M1 | transcript 完整性对比 | CONDITIONAL | transcripts=3/1（zstd 压缩，stdlib 无法逐行解析事件类型） |
| M2 | 轮次通过率 | FAIL | outcome=single_round_failed rounds=1（未收敛） |
| M3 | 失败模式分类 | PASS | classified={} unclassified=0 |
| M4 | 成本口径 | FAIL | completed=0/1（dispatch 事件未含 backend 字段；cost=0 为费率未登记） |

VERDICT: FAIL（试点判定 = CONDITIONAL，见下）
```

**试点判定：CONDITIONAL**（计划降级路径 2——dsh dispatch 可用但运行时行为不可用）。技术接线成功，但 dsh SDK 运行时组合存在**阻断级环境缺口**（见下）。评测脚本 FAIL 反映的是该缺口而非 backend 接线缺陷。

## 核心发现：dsh 运行时无 bash 执行通道（阻断）

真机 work_report（`.loop/work_report.json`）实证记录：

> "Execution blocked by the environment: every bash invocation is refused by the harness sandbox (\"sandbox mode 'workspace-write' is requested but no sandbox backend is usable on this host\"); escalation to danger-full-access fails closed (no approval channel available); a background subagent probe hit the identical denial."

即：dsh SDK 0.1.2rc1 内置 cordis 组合的 bash/subprocess 执行在 sandbox-mode `workspace-write` 下请求可用的 sandbox backend，但本机无 backend → 所有命令执行被拒；无 approval 插件 → 升级通道 fail-closed。**这验证了权限映射文档（D5）的核心声明：dsh 组合无 sandbox/guard/approval 插件，其后果比预想更基础——连工作区内写文件+跑测试都无法执行**，不只是"危险命令无拦截"。

后果链：worker 无法 git commit → head_sha == base_sha → loop_kit 证据门控（#2911）正确判定 no-change 并 blocked。此判定是**正确行为**（防伪造成功），不是 backend 缺陷。

## 与 opencode 基线对比

| 维度 | opencode（基线） | dsh（本试点实测） |
|------|-----------------|------------------|
| 结构化 transcript | 行捕获（stdout JSON 流，无 session 持久层） | **zstd 压缩 JSONL 落盘**（`.loop/dsh-home/sessions/`，3 个 session，305KB 主 transcript）——结构化审计能力成立，但需 zstd 解压管线才能消费（stdlib 无 zstd） |
| 执行通道 | `--auto` + per-command deny（42 条实测） | **无可用 bash 执行通道**（sandbox backend 缺失，fail-closed） |
| 成本口径 | cost_cents 按注册费率写入 dispatch 事件 | dsh 费率未登记 → cost=0（报告如实标注，非零成本） |
| 权限模型 | deny 规则运行时强制 | 无消费方（差距如实声明，见权限映射文档） |

## 失败模式分类明细

- 主失败模式：**environment-blocked（bash 执行被 sandbox 拒绝）**——M3 分类脚本无此类别（计划 M3 未预见"整个执行通道缺失"），建议 follow-up 在评测脚本补该分类。
- 无越界工具调用证据（worker 无法执行任何工具，权限差距以"能力缺失"形态暴露而非"越界"形态）。

## 证据归档声明（验收 O3 修正）

试点运行证据（work_report.json、主 transcript、state.json、events.jsonl）位于已 prune 的 worktree `.loop/worktrees/dsh-pilot/.loop/` 内，**prune 时未单独归档，现已无法独立复核**。以下证据留存并可复核：
- 2 个 SDK 冒烟 session transcript（zstd，`/tmp/dsh-acp-smoke-home/sessions/` 与 `/tmp` 下 dsh-home）——验收独立实测解压后含 assistant/message + turn/end 事件
- 本报告引用自 work_report.json 的原文摘录（"Execution blocked by the environment…" 段）——该引用为 prune 前抄录，作为证据链的主文本
- ACP 冒烟 README（`coupling/dsh-acp-smoke/README.md`，ACP_OK + notifications=1987）

**Follow-up 建议**：后续 R6 类计划应增加「prune 前归档 transcript + work_report」步骤，避免审计证据随 worktree 清理丢失。

## 回滚说明

1. dsh backend 已注册但**不影响默认行为**：`--worker-backend dsh` 不传即回滚，默认 codex 不受影响。
2. 试点产物留在 `pilot/dsh-t4` 分支（未合并）；worktree 保留待人工清理：`git worktree remove .loop/worktrees/dsh-pilot`。
3. transcript 在 `.loop/dsh-home/`（gitignored），不入库。

## follow-up 清单

1. **sandbox backend 部署评估**（最高优先）：`packages/sandbox`（landlock）在本机可用性探测——这是解锁 dsh 执行能力的前置条件。
2. **dsh 自研 guard/approval 插件**：与 opencode 42 条 deny 的对价物。
3. **zstd 解压管线**：评测脚本 M1 支持 zstd transcript 逐行解析（当前仅计数）。
4. **费率登记**：dsh 费率确定后写入 `_BACKEND_TOKEN_COST_CENTS_PER_MILLION`。
5. **CLI 后端启用条件**：dsh CLI 安装后按 `_build_dsh_command` 文档化形态启用。
6. **评测脚本补 environment-blocked 分类**。

## 结论

dsh backend 的 **loop_kit 侧接线完整可用**（registry 第 4 槽、in-process 派发、事件流、work_report 回写、no-change 证据门控全部按设计工作），**dsh SDK 运行时侧存在环境阻断**（无 sandbox backend → 无执行通道）。在 follow-up 1 落地前，dsh backend 保持注册但不可用于真实 lane（本试点结论）。CHANGELOG 已记录。
