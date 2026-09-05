# dsh 全链路真机验证报告（PM #3370）

- 日期：2026-09-05
- 前置：#2665（接线）、#3361（sandbox + bwrap userns）、#3364（bash 通道）、#3369（外层 commit 回退）
- 判定：**✅ 全链路 PASS — APPROVED at round 1**

## 结果

dsh backend 三件套（SDK 派发 + workspace-write 沙箱 + 外层 commit 回退）首次全链路真机运行**成功收敛**：

```
base: 93be75eb  head: a6d8264f   →   Reviewer: approve   →   APPROVED at round 1
```

## 证据链（运行时 log 原文）

| 阶段 | 证据 |
|------|------|
| worker 派发（dsh SDK + sandbox） | `Auto-dispatch done: role=worker backend=dsh attempts=1`（4 分 22 秒完成） |
| 外层 commit 回退触发 | `outer commit fallback: committing ['coupling/dsh-pilot/fib.py', 'coupling/dsh-pilot/test_fib.py'] on behalf of worker` |
| 回退 commit 成功 | `outer commit fallback: committed -> a6d8264f` |
| head_sha 前进 | `Worker done. head_sha=a6d8264f`（≠ base 93be75eb——#3364 的 no-change 阻断点解除） |
| 验收通过 | `Verification: PASS (exit=0)`（pytest 真实运行） |
| reviewer 收敛 | `Reviewer decision: approve`（dsh SDK 派发，47 秒） |
| 任务终结 | `Task terminal success via state contract at round=1 outcome='approved'` |

## 链路各环节状态

1. ✅ **dsh SDK 派发**：worker + reviewer 各 1 次真实 API 调用，均 attempts=1 成功
2. ✅ **sandbox 语义**：worker 在 workspace-write 沙箱内完成文件写入与测试执行（git commit 被沙箱拒绝——回退机制的设计前提如预期出现）
3. ✅ **外层 commit 回退**（#3369 交付物）：八重判据全部满足 → 显式路径 commit → head_sha 回填 → 落入正常 reviewer 流程
4. ✅ **reviewer 审查**：审查的正是外层 commit（a6d8264f），approve 通过
5. ✅ **状态机收敛**：round 1 approved，无重试、无 blocked

## 关键验证点

- **回退机制在真实场景触发**：worker 无法 git commit（sandbox 边界）→ 外层回退按设计介入——不是单测模拟，是端到端真实链路
- **无越界**：commit 集合 = 实测 dirty 精确集合（2 个文件，均在 owner_paths 白名单）
- **reviewer 链路零改动**：approve 决策基于外层 commit 的 diff，与 worker self-commit 的审查路径完全一致
- **预算**：2 次真实 dispatch（worker + reviewer），限额内

## 结论

**dsh backend 从「注册但不可用」（#2665 CONDITIONAL）到「全链路可用」的旅程完成**。`--worker-backend dsh --reviewer-backend dsh` + `LOOP_DSH_PATCHES` + `LOOP_OUTER_COMMIT_FALLBACK`（默认开）即可投入使用。

## 遗留（后续候选，不阻塞）

1. M4 成本口径事件形态（#3364 遗留，in-process 派发 cost 事件待查）
2. prompt 引导 worker 声明 untracked 新文件（files_changed 声明规范）
3. 多轮/lane_dispatch_enabled 模式的真机验证（本次为 serial 单轮）
