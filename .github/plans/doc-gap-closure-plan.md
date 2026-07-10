# 5 个文档缺口修复计划

## G1: AOM README 添加 agent-task-runner 集成说明

**文件:** `agent-orchestrator-management/README.md`

在 "Features" 段落后新增 `### 🤖 Agent Task Runner Integration` 小节：

- pipeline-loop 命令说明
- ATR provider 自动重定向
- 调用流程图（ASCII）
- outcome→status 映射表

**工作量:** 30min

---

## G2: 系统架构总览图

**文件:** 新建 `agent-task-runner/docs/system-architecture.md`

一张 ASCII 架构图 + 数据流说明，覆盖：
- PM systemd timer → bridge.py → ATR
- AOM pipeline-loop → ATR
- ATR → PM (summary.json / events.jsonl)
- opencode-tasks 独立调度

**工作量:** 30min

---

## G3: pm-atr 集成文档更新至 v4

**文件:** `project_management/docs/pm-atr-integration-design.md`

将版本从 v3 → v4，更新：
- P0: --outcome-file + summary.json 立即检测
- P1: OUTCOME_TO_PM_STATUS 映射表
- C1: events.jsonl 消费
- read_latest_events 函数说明
- pm_outcome_handler 说明

**工作量:** 20min

---

## G4: MCP 工具清单

**文件:** 新建 `project_management/docs/mcp-tool-reference.md`

重点标注哪些工具触发 ATR：
- pm_task_create (tags=["auto"]) → enqueue → dispatch_atr
- pm_task_complete → 结果确认
- 其他工具（只读/管理类）

**工作量:** 30min

---

## G5: pm-agent-runner 迁移指南

**文件:** `pm-agent-runner/docs/migration-to-bridge.md`

说明从 pm-agent-runner 迁移到 bridge.py 的路径：
- 旧方式 vs 新方式对比
- bridge.py 的调用方式
- 如何测试迁移结果

**工作量:** 20min

---

## 执行顺序

```
G1 (AOM README, 30min) → G2 (架构图, 30min) → G3 (PM doc v4, 20min) → G4 (MCP ref, 30min) → G5 (迁移指南, 20min)
```

**合计: 2h10min**
