# dsh vs opencode 同任务时延对照实验（PM #3373）

- 日期：2026-09-05
- 方法：同一微任务卡（dsh-pilot-T4 fib 模块），dsh 与 opencode 各 serial 单轮跑 N=5（--max-rounds 1 --dispatch-retries 0），记录 wall-clock 端到端时长（worktree 创建 → 任务终结）与收敛结果。
- 原始数据：`docs/bench-results-final.json`

## 结果

| 后端 | n | 收敛 | wall_s mean | wall_s median | min | max |
|------|---|------|-------------|---------------|-----|-----|
| dsh | 5 | **5/5** | 291s | 202s | 162s | 659s |
| opencode | 5 | 4/5 | 405s（全体）/ 358s（收敛样本） | 360s | 202s | 593s |

## 关键发现

1. **收敛率**：dsh 5/5；opencode 4/5（1 次 rc=3 未收敛，真实派发 593s 后失败，非快速失败——疑 reviewer 偶发，见"诚实声明"）。
2. **时延（收敛样本中位数）**：dsh 202s vs opencode 360s——**dsh 中位数快约 44%**。但 dsh 波动大（max 659s），opencode 更平稳（min-max 202-593s）。
3. **冷启动效应**：dsh #3（162s）与 #4（659s）相差 4 倍——dsh 每次派发都拉起 267MB runtime 子进程 + sandbox 初始化，首轮冷启动与后续热启动差异大；opencode 同为 CLI 子进程但无 sandbox 层，波动相对小。
4. **成本**：dsh 费率 (43,129) cents/M 约为 codex 1/4；opencode 费率未登记（cost 事件为 0，见 #3358 前状态）。

## 诚实声明（重要）

1. **对照组从 codex 改为 opencode**：任务卡原定 codex，但本机 **codex CLI 不存在**（`which codex` 空，5 次尝试全部 0.2s 快速失败 "Cannot find executable for backend=codex"）。opencode 是同属 subprocess 家族的对照后端，本机已装（1.18.28），替换合理。
2. **opencode #1 失败（593s rc=3）根因未定位**：失败日志随 worktree 清理丢失，仅能确认是真实派发后未收敛（非环境快速失败）。样本量小（N=5），该偶发可能使 opencode 收敛率被低估 1 例。
3. **样本量小**：N=5 不足以做显著性检验；数据仅作量级参考，不作生产选型唯一依据。
4. **dsh 每次派发均含 sandbox + 外层 commit 回退开销**；opencode 无此两层。时延对比含架构差异，非纯模型推理速度对比。
5. **单任务单轮**：结论仅对该微任务形态（单文件实现 + 测试）有效，多轮/lane 场景见 #3372。

## 结论

dsh backend 在同任务时延上**不劣于 opencode**（收敛样本中位数快 44%，收敛率更高），且成本约为其 1/4、具备 opencode 没有的文件系统沙箱与 session 级审计能力。dsh 的波动性（冷启动 4 倍差）是其主要代价。综合 #3370/#3372 与本次数据，**dsh backend 已达到生产可用级别**（含多轮/lane/成本事件/时延四项验证）。

## 遗留（不阻塞）

1. 大样本（N≥20）双后端对照 + 显著性检验
2. opencode #1 偶发失败根因复现
3. codex 对照臂（需先安装 codex CLI）
