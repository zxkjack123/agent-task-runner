# Plan: 为 ATR 的 opencode dispatch 设置合理 timeout

> **状态**: 待执行  
> **范围**: 1 repo — `project_management`  
> **改动量**: 1 个 task，约 3 行代码

---

## 背景与根因

### 问题链

1. **bridge.py 未传 `--dispatch-timeout` 给 loop_kit** → loop_kit 使用默认值 `DISPATCH_DEFAULT_TIMEOUT_SEC=0`
2. **`_collect_streamed_process_output` L2766**: `deadline = None if timeout_sec <= 0 else ...` — timeout=0 意味着无限等待
3. **opencode 在 agent-task-runner cwd 中启动慢**: 需要 ~60s+ 才能输出第一行 JSON event。包括：
   - 加载 1125 行 `opencode.jsonc` 中的 MCP 工具定义
   - `git rev-parse --show-toplevel` + `git remote get-url origin` + `git diff`
   - 连接 5 个本地 MCP 服务端口（8014 crawl4ai, 8766 zotero, 9122 tikz-writer 等）
4. **DeepSeek API 的 governor 波动** — 是瞬时的 401 问题，不是 timeout 根因

### 测量数据

在 agent-task-runner cwd 中，opencode 从 Popen 到第一行 JSON 输出：~2-3s（当在 shell 中直接测试时），但在 subprocess.Popen + stdin pipe 上下文中最坏可达 60s+。

### 修复策略

**在 bridge.py 的 dispatch_atr 中添加 `--dispatch-timeout` 参数，设一个对 opencode 启动友好的初始值。**

- 当前值: `--dispatch-timeout 0`（默认，无限等待）
- 新值: `--dispatch-timeout <ATR_DISPATCH_TIMEOUT>`，默认 600秒（10分钟）

10 分钟提供足够的余量来容纳：
- opencode 首次启动延迟（最多 60s）
- LLM 响应时间（最多几分钟）
- 重试 3 次（每次 dispatch_retry_base_sec=5s → 5+10+20=35s 总重试间隔）
- 文件 I/O 写入 artifact

### 与 `--timeout` 的区别

| 参数 | 作用域 | 现有值 |
|------|--------|--------|
| `--timeout` | loop_kit 总运行时限 | 1800s (30min) |
| `--dispatch-timeout` | opencode 子进程单次 dispatch 时限 | 0 (无限) → **改为 600s** |
| `--artifact-timeout` | 等待 Worker 产出 work_report | 300s (5min) |

`--dispatch-timeout` 针对**每次 Worker draft 调用**的 timeout。它在 `_collect_streamed_process_output` 中触发 `proc.terminate()`，然后重试逻辑启动下一次调用。

---

## 修改方案

### Task 1: bridge.py 添加 dispatch-timeout 参数

**文件**: `/home/gw/opt/project_management/src/auto_task/bridge.py`

**修改**:

1. L34 添加 `_DISPATCH_TIMEOUT_SEC` 常量（环境变量 `ATR_DISPATCH_TIMEOUT`，默认 600）:
   ```python
   _DISPATCH_TIMEOUT_SEC = int(os.environ.get('ATR_DISPATCH_TIMEOUT', '600'))
   ```

2. L369 之后（`"--artifact-timeout", "300"` 行后面）添加:
   ```python
   "--dispatch-timeout", str(_DISPATCH_TIMEOUT_SEC),
   ```

**边界**: 不修改 `_TIMEOUT_SEC`、`_IDLE_TIMEOUT_SEC`、`_HEARTBEAT_TIMEOUT_SEC` 或其他 timeout 参数。不修改 loop_kit 源码。

**验收**:
- ✅ `python -m py_compile` pass
- ✅ `--dispatch-timeout 600` 在 cmd 中出现
- ✅ 环境变量 `ATR_DISPATCH_TIMEOUT` 可覆盖

---

## 执行计划

### Phase 1: bridge.py 修改

#### Task 1.1: 添加 `_DISPATCH_TIMEOUT_SEC` + 在 cmd 中使用

- **目标**: 为 loop_kit 的 opencode dispatch 设置 600s timeout（可覆盖）
- **依赖**: 无
- **修改文件**:
  - `/home/gw/opt/project_management/src/auto_task/bridge.py`
- **具体修改**:
  1. L34 后（`_HEARTBEAT_TIMEOUT_SEC` 定义行后）插入:
     ```python
     _DISPATCH_TIMEOUT_SEC = int(os.environ.get('ATR_DISPATCH_TIMEOUT', '600'))
     ```
  2. L369 后（`"--artifact-timeout", "300"` 行后）插入:
     ```python
     "--dispatch-timeout", str(_DISPATCH_TIMEOUT_SEC),
     ```
- **验收标准**:
  - ✅ `python -m py_compile` pass
  - ✅ `dispatch_atr` 生成的 cmd 包含 `--dispatch-timeout 600`
- **潜在风险**: 
  - timeout 600s 对复杂 LLM 任务可能不够 — 通过环境变量 `ATR_DISPATCH_TIMEOUT` 覆盖
  - opencode 在首次调用时（warm-up）慢于后续调用 — 后续调用缓存 MCP 连接和 git 状态，延迟显著降低

---

## Post-Execution Verification

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | py_compile | `python -m py_compile /home/gw/opt/project_management/src/auto_task/bridge.py` | exit 0 |
| V2 | runtime check | `python -c "from src.auto_task.bridge import _DISPATCH_TIMEOUT_SEC; print(_DISPATCH_TIMEOUT_SEC)"` | 600 |
| V3 | env override | `ATR_DISPATCH_TIMEOUT=300 python -c "from src.auto_task.bridge import _DISPATCH_TIMEOUT_SEC; print(_DISPATCH_TIMEOUT_SEC)"` | 300 |

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性 — 1 个常量 + 1 个命令行参数 | 0 | — | 0 |
| R1.5 | 外部引用 — `--dispatch-timeout` 是 loop_kit 的有效 CLI 参数（L12979），`DEFAULT_DISPATCH_TIMEOUT_SEC=0` 被 L2766 正确处理 | 0 | — | 0 |
| R2 | 可执行性 — 仅 2 行代码，明确插入位置 | 0 | — | 0 |
| R2.8 | LLM 可执行性 — 零歧义 | 0 | — | 0 |
| R3 | 风险 — opencode 冷启动延长 600s 对于 LLM 任务可能偏小；可通过环境变量覆盖 | 已记录 | — | 0 |
| **终止** | **T4 — 全部 0 issue** | | | **0** |
