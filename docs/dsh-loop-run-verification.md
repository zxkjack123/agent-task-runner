# dsh backend 完整 loop run 复验报告（PM #3364）

- 日期：2026-09-05
- 前置：#3361（sandbox patches 验证 PASS，bwrap userns 已放行）

## 复验结论

**执行通道完整验证 PASS；lane 收敛 FAIL（git 集成缺口）**——worker 真实完成了全部开发动作（写文件 + pytest 9 passed + py_compile），唯一阻断是 `git commit` 需写主仓 `.git`（lane worktree 之外），被 sandbox workspace-write 正确拒绝。这是**沙箱正确行为与 loop_kit lane 模型的架构冲突**，非 dsh backend 缺陷。

## 证据链（transcript 实测）

| 阶段 | 结果 | 证据 |
|------|------|------|
| LOOP_DSH_PATCHES 接线 | ✅ | commit 1dc665c（env 冒号分隔 → patches 元组；单测 8 passed；全量 748 passed） |
| bash 执行通道 | ✅ | worker 真实执行 18 次 bash 调用（pwd/git status/pytest/py_compile） |
| 文件写入 | ✅ | write 工具 2 次成功落盘 `coupling/dsh-pilot/fib.py`（迭代 O(n)、ValueError、docstring 规范）+ `test_fib.py` |
| 测试执行 | ✅ | pytest 真实运行 **9 passed**（外层独立复跑同结果） |
| 沙箱语义 | ✅ | `git commit` 写主仓 `.git` → "read-only file system" 拒绝；`/tmp` 可写；escalation 无 approval 通道 fail-closed |
| lane 收敛 | ❌ | head_sha == base_sha → 证据门控正确判定 no-change → blocked（防伪造成功，行为正确） |

## 评测四指标

```
| M1 | transcript 完整性 | PASS | 22 类事件（zstd 解析全量） |
| M2 | 轮次通过率 | FAIL | 未收敛（git 缺口所致） |
| M3 | 失败模式分类 | PASS | 0 未分类 |
| M4 | 成本口径 | FAIL | cost_entries=0（in-process 派发事件形态待查） |
```

## 根因分析

**集成缺口**：loop_kit lane 模型要求 worker 在 lane worktree 内自 commit，但 `git commit` 的元数据写入落在主仓 `/home/gw/opt/agent-task-runner/.git`（worktree 共享对象库）——超出 sandbox 的 workspace 边界。opencode 后端无沙箱所以从不暴露此约束；dsh sandbox 忠实执行了 workspace-write 语义，暴露了架构假设。

## 后续路径（供决策，不属本任务）

| 路径 | 动作 | 评估 |
|------|------|------|
| A | loop_kit 适配：worker self-commit 失败时外层代为 commit（work_report 已建议 "PM/orchestrator should commit them from the outer process"） | 架构级改动，需单独任务 + 计划 |
| B | sandbox 配置放宽 git 元数据写（patches 加写允许） | 削弱隔离（跨 lane 共享 .git），不推荐 |
| C | dsh 用于 no-commit lane（如 reviewer 角色）先行 | 渐进启用，可行 |

## 合规

- 真实 dispatch：2 次（1 次超时重试计入 + 1 次完成）；用户授权预算内
- 只改 _core.py + tests + docs；无 fork 修改；无新 sudo
- 全量 748 passed（747 基线 + 1 新单测）0 回归；ruff 0 error

## 结论更新

dsh backend 能力链完整验证：loop_kit 接线 ✅ → bash 执行 ✅ → 文件写 ✅ → 测试跑 ✅ → 沙箱语义 ✅。唯一未通项是 lane git commit（架构冲突），**dsh backend 可在「不要求 worker 自 commit 的 lane 形态」下投入使用**（如 reviewer-only lane），完整 worker lane 需路径 A 的 loop_kit 适配任务。
