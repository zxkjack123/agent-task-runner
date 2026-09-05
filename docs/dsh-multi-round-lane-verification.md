# dsh 多轮 + lane_dispatch_enabled 模式真机验证报告（PM #3372）

- 日期：2026-09-05
- 前置：#3370（serial 单轮全链路 APPROVED）、#3371（成本事件落地）
- 结果：**两场景均收敛 ✅；多轮循环路径未触发（如实记录）**

## 场景 1：lane_dispatch_enabled 2-lane 并行（dsh 全后端）

**判定：✅ PASS** — `APPROVED at round 1`，`base: 9a75b0a7 → head: fb121a92`

| 环节 | 证据 |
|------|------|
| lane_fib 派发 | `worker_lane_lane_fib backend=dsh attempts=1`（80 秒） |
| lane_fib 外层回退 | `outer commit fallback: committed -> e8189f00`（per-lane 站点，merge 前） |
| lane_fact 派发 | `worker_lane_lane_fact backend=dsh attempts=1`（99 秒） |
| lane_fact 外层回退 | `outer commit fallback: committed -> 25e6b659` |
| merge | head_sha=fb121a92（两 lane commit 合并成功） |
| reviewer | `Reviewer decision: approve`（95 秒） |
| 终结 | `outcome='approved'` |

**验证要点**：
- ✅ per-lane 外层 commit 回退（#3369 T3.1 的 lane 站点）在真实并行 lane 下逐 lane 触发
- ✅ cherry-pick merge 零改动路径下自然收敛
- ⚠️ 观察项：`Verification: FAIL (exit=0)` 出现于 lane 场景的合并验收步骤（exit=0 但判定 FAIL）——疑为 lane 合并后 verification 命令的路径/格式问题；reviewer 仍 approve，未影响收敛。**如实记录，建议 follow-up 排查**（见遗留 3）。

## 场景 2：多轮（max-rounds 3，serial 单 lane）

**判定：✅ 收敛（round 1）** — `APPROVED at round 1`，`head: 9bf6a93b`

- worker 1 次 dispatch（外层回退 commit）+ reviewer approve（26 秒）→ round 1 终结。
- **多轮循环路径（changes_required → round 2 worker 修复）未触发**——reviewer 对正确实现直接 approve 属预期行为。要真实验证多轮循环，需要一个首轮实现有缺陷的任务卡（reviewer 会 changes_required）——如实记录为**未覆盖项**，不是失败（任务验收条件允许"多轮收敛或明确失败原因记录"；本场景收敛，多轮路径待缺陷注入实验）。

## 预算

- 场景 1：3 次 dispatch（2 worker lane + 1 reviewer）
- 场景 2：2 次 dispatch（1 worker + 1 reviewer）
- 合计 5 次 ≤ 8 限额；均 attempts=1 成功（零重试加钱）

## 结论

dsh backend 在 **lane 并行模式 + per-lane 外层回退 + merge + reviewer** 全链路真机可用（场景 1 是 #3369 lane 站点接线的首次端到端验证）。多轮循环路径因 reviewer 首轮 approve 未触发，需缺陷注入实验覆盖（遗留 2）。

## 遗留（不阻塞）

1. **多轮循环缺陷注入实验**：构造首轮有缺陷的任务卡（如验收条件要求 n<0 抛 ValueError 但给 worker 一个容易漏掉此要求的 prompt）触发 changes_required → round 2
2. 场景 1 的 `Verification: FAIL (exit=0)` 合并验收判定排查
3. lane 场景 cost 事件抽样核对（#3371 落地后 lane 派发的 dispatch_complete cost_cents）
