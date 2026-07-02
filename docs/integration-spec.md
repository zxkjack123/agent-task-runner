# agent-task-runner 集成规范 v1.0

> **目标读者:** AOM (agent-orchestrator-management) 开发者
> **定位:** AOM 通过本规范调用 agent-task-runner 的 PM→Worker→Reviewer 循环

---

## 1. 入口命令

```bash
python -m loop_kit run \
  --task    <task_card.json>      \  # 必填
  --worker-backend  opencode      \  # 必填（当前仅 opencode）
  --reviewer-backend opencode     \  # 必填
  --auto-dispatch                 \  # 必填
  --max-rounds    5               \  # 默认 3
  --timeout       600             \  # 单阶段超时秒数
  --dispatch-timeout 900          \  # worker/reviewer 超时
  --artifact-timeout 300          \  # work_report/review_report 等待超时
  --allow-dirty                   \  # 允许脏工作树
  --max-parallel-workers 1        \  # 直连模式（推荐，避免 worktree 分支 bug）
  --outcome-file   /path/outcome.json  # 输出结果路径
```

### 轮询命令

```bash
python -m loop_kit status --json                    # 完整状态
python -m loop_kit status --json --outcome-only     # 终端判断（仅返回 {outcome}）
```

---

## 2. task_card.json

```jsonc
{
  "task_id":        "T-42",                    // 必填 string，与 PM 任务 ID 一致
  "goal":           "实现 verify.py 验证脚本", // 必填 string
  "in_scope":       ["src/verify.py"],         // 必填 string[]
  "out_of_scope":   ["tests/", "docs/"],       // 必填 string[]
  "acceptance_criteria": [
    "verify.py 运行后返回 exit_code=0",
    "支持 --help 参数"
  ],                                            // 必填 string[]
  "constraints": [
    "不要修改现有文件"
  ],                                            // 必填 string[]
  "depends_on":     [],                        // 可选 string[]
  "lanes": [{
    "lane_id":          "lane_main",           // 必填
    "owner_paths":      ["src/verify.py"],     // 必填
    "backend_preference": "opencode"           // 必填
  }],
  "verification": {                            // 可选（Phase 3）
    "command":         "python verify.py",
    "expected_output": "OK",
    "timeout_sec":      30
  }
}
```

---

## 3. outcome.json（由 `--outcome-file` 产出）

```jsonc
{
  "task_id":       "T-42",
  "run_id":        "run-xxxx",
  "outcome":       "approved",               // 见下方 outcome 枚举
  "rounds":        2,                        // 实际轮数
  "exit_code":     0,                        // 0=成功，非0=失败
  "decision":      "approve",                // reviewer 决策
  "base_sha":      "abc123",
  "head_sha":      "def456",
  "files_changed": ["src/verify.py"],
  "review_blocking":    [],
  "review_non_blocking": ["建议添加类型注解"],
  "worker_notes":  "创建了 verify.py，实现了完整的 CLI",
  "duration_ms":   120000,
  "knowledge_updates": {
    "patterns": ["使用 argparse 处理 CLI 参数"],
    "pitfalls":  ["忘记处理空输入"],
    "facts":     ["本项目使用 Python 3.11+"]
  }
}
```

### outcome 枚举

| outcome | 含义 | 对应 PM status |
|---------|------|---------------|
| `approved` | reviewer 批准 | Done |
| `no_change_success` | worker 无需变更，已满足验收 | Done |
| `changes_required_retry` | reviewer 要求修改，已退回重试 | (中间态) |
| `validation_failure` | worker 产出无效 (noop_as_error) | NeedsAttention |
| `timeout` | worker/reviewer 超时 | Blocked |
| `interrupted` | 用户或系统中断 | Blocked |
| `config_error` | 配置/任务卡格式错误 | NeedsAttention |
| `dirty_worktree` | 工作树不干净 | Blocked |
| `lock_failure` | 锁获取失败 | Blocked |
| `max_rounds_exhausted` | 达到最大轮数未通过 | Blocked |
| `state_error` | 状态机错误 | NeedsAttention |

### exit_code 枚举

| exit_code | 含义 |
|-----------|------|
| 0 | 成功 (approved/no_change_success) |
| 1 | 通用错误 |
| 2 | 验证错误 (validation_failure/config_error) |
| 3 | 超时 |
| 4 | 脏工作树 |
| 5 | 锁失败 |
| 6 | 用户中断 |

---

## 4. status --json 输出（轮询用）

```jsonc
{
  "state":     "awaiting_review",     // idle|awaiting_work|awaiting_review|done
  "round":     2,
  "task_id":   "T-42",
  "run_id":    "run-xxxx",
  "outcome":   null,                  // null=未完成，approved|...=已完成
  "base_sha":  "abc123",
  "head_sha":  "def456",
  "sessions":  {},
  "started_at":"2025-01-01T00:00:00Z",
  "bus_files": {
    "work_report.json":   "exists",
    "review_report.json": "missing"
  }
}
```

### --outcome-only 简版

```json
// 仅在 outcome != null 时短路输出:
{"outcome": "approved"}
// 否则输出完整 status JSON
```

---

## 5. preflight.json（安全策略）

放置在 AOM 为 agent-task-runner 创建的 worktree 的 `.loop/preflight.json`:

```jsonc
{
  "forbidden_patterns": ["sudo", "rm -rf", "chmod 777"],
  "require_git_clean":  true,
  "max_file_size_mb":   10,
  "require_tests":      true
}
```

加载优先级: `.loop/preflight.json` > `.loop/preflight.yaml` > (无策略=宽松默认)

---

## 6. AOM 调用流程

```
AOM 侧:
  1. taskCard = TaskCardGenerator.Generate(task, project)  → task_card.json
  2. worktree = worktreeService.EnsureProvisioned(taskID, repoPath)
  3. 写入 worktree/.loop/preflight.json (from project policy)
  4. 复制 task_card.json → worktree/.loop/tasks/{taskID}_task_card.json
  5. 子进程调用:
     python -m loop_kit run \
       --task {worktree}/.loop/tasks/{taskID}_task_card.json \
       --outcome-file {worktree}/.loop/outcome.json \
       --worker-backend opencode --reviewer-backend opencode \
       --auto-dispatch --max-parallel-workers 1
  6. 等待子进程退出
  7. 读取 outcome.json
  8. 映射 outcome → taskStatus:
     approved/no_change_success → task.Close()
     其他 → task.Update(status=mappedStatus, notes=outcome.review_blocking)
  9. 清理 worktree (可选，或保留用于调试)
```

---

## 7. 安全注意事项

1. **verification 命令由 agent-task-runner 执行，不传给 LLM** — 安全沙箱（timeout 30s, output 截断 4KB）
2. **preflight 约束注入 worker prompt** — LLM 不接触原始策略文件
3. **worktree 隔离** — worker 的 commit 受 `GIT_DIR` 环境变量约束，不污染主分支
4. **outcome.json 覆盖全部失败路径** — 包括 interrupted/timeout/lock_failure
