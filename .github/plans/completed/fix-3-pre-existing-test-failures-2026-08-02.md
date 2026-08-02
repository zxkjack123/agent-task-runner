---
goal: "修复 3 个 pre-existing 测试失败：T1 cost_cents 断言过时、T2 backend 断言过时、T3 硬编码日期时间腐烂"
scope_mode: "HOLD"
git_commit: "未指定（执行前由 TE 采集）"
generated_at: "2026-08-02"
linked_task: "PM #2234 (后置修复)"
related_plan: "agent-task-runner/.github/plans/atr-analysis-exec-fix-2026-08-01.md"
---

# 修复 3 个 pre-existing 测试失败（方案 A：修测试同步生产新行为）

> 本计划修复执行 `atr-analysis-exec-fix-2026-08-01.md` 时发现的 3 个 pre-existing 测试失败。三个均非生产代码 bug，而是测试与实现/时间不同步。根因分析已完成（见下）。

## 背景与目标

- **问题来源**：#2234 修复计划 Post-Execution Verification 阶段发现的 3 个 pre-existing 失败，均已在 HEAD 基线复现确认与 #2234 改动无关。
- **根因链**：snapshot commit `6783413`（"chore: snapshot working tree before ATR service start"）一次改了 3 个生产常量但**未同步测试**；另有 1 个测试数据随时间腐烂。
- **目标**：让 `tests/test_orchestrator.py` 从 "562 passed + 3 failed" 变为 "565 passed + 0 failed"。
- **非目标（不做什么）**：
  - 不改生产代码（`src/loop_kit/_core.py` 的 cost 表、默认 backend、stale 归零逻辑均正确）。
  - 不 skip/xfail 测试（断言的是真实行为，只是期望值过期）。
  - 不引入新依赖或重构测试结构。

## Scope Mode: HOLD

严格保持范围：只改 `tests/test_orchestrator.py` 中 3 个测试函数的断言/数据，不触碰其它测试与生产代码。

---

## 根因 → 修复映射（已验证）

| # | 测试 | 失败断言 | 根因（验证结论） | 修复 |
|---|------|---------|-----------------|------|
| T1 | `test_enrich_work_report_runtime_fields_sets_zero_cost_for_non_billed_backend`（L2120） | `cost_cents == 0`，实际 1 | snapshot `6783413` 将 `BACKEND_OPENCODE` 从 `(0,0)` 改为 `(43,87)`；`(5000×43+4000×87)/1e6=0.563→ceil→1`。测试名/断言过时 | 断言改为 `== 1`，改名/注释说明 opencode 计费 |
| T2 | `test_single_round_lane_dispatch_emits_lane_runtime_telemetry_and_report_fields`（L5832） | `backend == BACKEND_CODEX`，实际 opencode | snapshot `6783413` 将 `DEFAULT_WORKER_BACKEND` 从 `codex` 改为 `opencode`；测试不传 worker_backend → 默认 opencode。同测试 `cost_cents == 1` 已通过（半同步） | `BACKEND_CODEX` → `BACKEND_OPENCODE` |
| T3 | `TestCmdStatus::test_shows_context_file_stats`（L8499） | `high_confidence=1, stale=1`，实际 `0, 2` | 测试硬编码 `last_verified: "2026-04-01"` 已超 30 天 stale 窗口；`_normalize_pattern_entry` 对 stale 归零 confidence → 两条都 stale、都 <0.7 | 硬编码日期改相对时间（fresh=now-5天, stale=now-100天） |

**关键事实（R1.5 核查）**：
- cost 表 `_core.py:422-427`：`BACKEND_OPENCODE: (43, 87)`，注释 "deepseek-v4-pro via direct API"。opencode 计费是**有意的**（#2233 用 opencode）。
- 测试文件已有 6 处 `cost_cents == 1` 断言（L2105/2111/2117/5939/5942/5952）——T1 的 `== 0` 是孤例。
- 测试文件 L15 已 import `from datetime import UTC, datetime, timedelta`；L3856-3858 / L10823 已有 `old_iso`/`fresh_iso`/`stale_iso` 相对时间先例——T3 直接复用该模式。
- T2 的 fake dispatch 用 2000/1000 tokens → opencode (43,87) → `(2000×43+1000×87)/1e6=0.173→ceil→1`，与 `cost_cents == 1` 一致。

---

## 执行计划

### Phase 1: 修 T1 cost 断言

#### Task 1.1: 更新 T1 断言与测试语义
- **目标**：`test_enrich_work_report_runtime_fields_sets_zero_cost_for_non_billed_backend` 反映 opencode 当前计费行为。
- **依赖**：无
- **frontier**：是
- **执行者**：Simulation Builder（熟悉测试文件）
- **修改内容**：
  - 文件 `tests/test_orchestrator.py`：
    1. 函数名 `test_enrich_work_report_runtime_fields_sets_zero_cost_for_non_billed_backend` → `test_enrich_work_report_runtime_fields_computes_cost_for_billed_opencode_backend`（改名避免语义误导）
    2. L2137 `assert report["cost_cents"] == 0` → `assert report["cost_cents"] == 1`
    3. 函数 docstring 或注释：说明 opencode 现按 (43, 87) 计费，5000/4000 tokens → ceil(0.563) = 1 cent
- **修改边界**：只改这一个测试函数；不改 `_enrich_work_report_runtime_fields` 及其它测试。
- **质量检查方式**：
  - 检查项 1：改名后无其它代码引用旧函数名（grep）。
  - 检查项 2：断言值 1 与 `_estimate_backend_cost_cents` 计算一致。
- **验收标准**：
  - ✅ `timeout 60 uv run --group dev pytest tests/test_orchestrator.py::test_enrich_work_report_runtime_fields_computes_cost_for_billed_opencode_backend -q` 通过。
  - ✅ `grep -c "sets_zero_cost_for_non_billed_backend" tests/test_orchestrator.py` 返回 0（旧名清除）。
- **潜在风险**：极低（单断言 + 改名）。
- **预留歧义标注**：无。

### Phase 2: 修 T2 backend 断言

#### Task 2.1: 更新 T2 backend 期望值
- **目标**：`test_single_round_lane_dispatch_emits_lane_runtime_telemetry_and_report_fields` 的 backend 断言与当前默认后端一致。
- **依赖**：无
- **frontier**：是
- **执行者**：Simulation Builder
- **修改内容**：
  - 文件 `tests/test_orchestrator.py` L5936：`assert lane_report["backend"] == orchestrator.BACKEND_CODEX` → `assert lane_report["backend"] == orchestrator.BACKEND_OPENCODE`
  - （可选）在该行上方加注释：`# DEFAULT_WORKER_BACKEND is opencode since snapshot 6783413`
- **修改边界**：只改这一行断言；不改 fake dispatch、`_run_config`、`cost_cents` 断言。
- **质量检查方式**：
  - 检查项 1：`grep -c "lane_report\[\"backend\"\] == orchestrator.BACKEND_CODEX" tests/test_orchestrator.py` 返回 0。
  - 检查项 2：`grep -c "lane_report\[\"backend\"\] == orchestrator.BACKEND_OPENCODE" tests/test_orchestrator.py` 返回 1。
- **验收标准**：
  - ✅ `timeout 90 uv run --group dev pytest tests/test_orchestrator.py::test_single_round_lane_dispatch_emits_lane_runtime_telemetry_and_report_fields -q` 通过。
- **潜在风险**：低。⚠️ 若该测试还断言 `cmd[0] == "codex.exe"` 类命令行内容（需先 grep 确认），则需一并核对——但 L5832 测试的 fake dispatch 不构造真实 cmd，无此断言。
- **预留歧义标注**：无。

### Phase 3: 修 T3 时间腐烂数据

#### Task 3.1: T3 硬编码日期改为相对时间
- **目标**：`test_shows_context_file_stats` 不再随时间腐烂——fresh/stale 由当前时间动态推导。
- **依赖**：无
- **frontier**：是
- **执行者**：Simulation Builder
- **修改内容**：
  - 文件 `tests/test_orchestrator.py` L8508-8528（`patterns.jsonl` 构造处）：
    1. 在测试函数开头（`_configure_loop_paths` 之后）新增：
       ```python
       _now_utc = datetime.now(UTC)
       _fresh_iso = (_now_utc - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
       _stale_iso = (_now_utc - timedelta(days=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
       ```
    2. 第一条 pattern `"last_verified": "2026-04-01T12:00:00Z"` → `"last_verified": _fresh_iso`
    3. 第二条 pattern `"last_verified": "2025-01-01T00:00:00Z"` → `"last_verified": _stale_iso`
    4. 断言保持 `entries=2, high_confidence=1, stale=1` 不变
- **修改边界**：只改这一测试函数的数据构造；不改 `cmd_status` 生产逻辑、不改断言。
- **质量检查方式**：
  - 检查项 1：`grep -c "2026-04-01T12:00:00Z\|2025-01-01T00:00:00Z" tests/test_orchestrator.py` 在 L8508-8528 区间内为 0。
  - 检查项 2：`_fresh_iso`（5 天前）满足 `now - parsed < 30 天` → fresh；`_stale_iso`（100 天前）→ stale。
- **验收标准**：
  - ✅ `timeout 60 uv run --group dev pytest "tests/test_orchestrator.py::TestCmdStatus::test_shows_context_file_stats" -q` 通过。
  - ✅ 该测试**重复运行 2 次**仍通过（验证不再时间依赖——因 fresh/stale 都是相对当前时间，恒成立）。
- **潜在风险**：低。⚠️ 若测试断言中硬编码了具体日期字符串，需同步；已确认断言只含 `high_confidence=1, stale=1` 计数，无日期字面量。
- **预留歧义标注**：无。

### Phase 4: 回归验证

#### Task 4.1: 全量回归 + 交叉确认无其它时间/backend 依赖
- **目标**：确认 3 个修复后全绿，且未引入新回归。
- **依赖**：T1.1, T2.1, T3.1
- **frontier**：否
- **执行者**：Simulation Builder
- **修改内容**（无代码改动，仅执行验证与记录）：
  - 运行 3 个目标测试确认通过。
  - 运行整个 `test_orchestrator.py` 确认从 3 failed → 0 failed（562+3=565 passed）。
- **修改边界**：不得修改任何测试/生产代码。
- **质量检查方式**：
  - 检查项 1：3 个目标测试全绿。
  - 检查项 2：全量测试无新增失败。
- **验收标准**：
  - ✅ `timeout 300 uv run --group dev pytest tests/test_orchestrator.py -q` 全绿（565 passed, 0 failed）。⚠️ 若全量超 300s，则运行 `-k "enrich_work_report or lane_dispatch_emits or shows_context_file_stats"` 且确认 3 个目标通过，并记录全量超时原因。
- **潜在风险**：全量测试耗时长（约 5-10 分钟），需足够 timeout。
- **预留歧义标注**：无。

---

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|-----------|
| W1 | T1.1 / T2.1 / T3.1 | T1.1, T2.1, T3.1 | — |
| W2 | T4.1 | — | W1 (全部) |

> 注：T1.1/T2.1/T3.1 虽都在 `tests/test_orchestrator.py`，但改动的是**不同函数的不同行**，无重叠编辑区。若 TE 采用单 worker 串行，按编号顺序执行即可；若并行，需注意同一文件并发编辑冲突——建议**串行执行 3 个修改**（避免同文件并行编辑），W2 回归验证在全部修改后执行。

---

## Post-Execution Verification

Task Executor 在所有 plan task 执行完毕后运行以下验证。

### Automated Verification（TE 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | T1 目标测试 | `timeout 60 uv run --group dev pytest tests/test_orchestrator.py::test_enrich_work_report_runtime_fields_computes_cost_for_billed_opencode_backend -q` | exit 0，1 passed |
| V2 | T2 目标测试 | `timeout 90 uv run --group dev pytest tests/test_orchestrator.py::test_single_round_lane_dispatch_emits_lane_runtime_telemetry_and_report_fields -q` | exit 0，1 passed |
| V3 | T3 目标测试（跑 2 次验时间独立性） | `timeout 60 uv run --group dev pytest "tests/test_orchestrator.py::TestCmdStatus::test_shows_context_file_stats" -q` | exit 0，2 次均 1 passed |
| V4 | 旧名清除检查 | `cd /home/gw/opt/agent-task-runner && grep -c "sets_zero_cost_for_non_billed_backend" tests/test_orchestrator.py` | 0 |
| V5 | T2 backend 断言更新 | `cd /home/gw/opt/agent-task-runner && grep -c 'lane_report\["backend"\] == orchestrator.BACKEND_OPENCODE' tests/test_orchestrator.py` | ≥1 |
| V6 | T3 旧日期清除（函数内） | `cd /home/gw/opt/agent-task-runner && grep -n "2026-04-01T12:00:00Z\|2025-01-01T00:00:00Z" tests/test_orchestrator.py` | L8508-8528 区间内无匹配 |
| V7 | 全量回归 | `timeout 300 uv run --group dev pytest tests/test_orchestrator.py -q` | 565 passed, 0 failed（若超时降级为 -k 目标测试） |

### Probe（best-effort，run if available）
- [ ] P1: `cd /home/gw/opt/agent-task-runner && uv run python -c "from loop_kit._core import _estimate_backend_cost_cents; print(_estimate_backend_cost_cents(backend='opencode', input_tokens=5000, output_tokens=4000, total_tokens=9000))"` 应打印 1（印证 T1 新断言）。

### Manual（真正需要人工判断）
- [ ] M1: 人工复核 T1 改名后测试语义是否仍清晰（"computes_cost_for_billed_opencode_backend" 名称与行为一致）。
- [ ] M2: 人工确认 3 个修复未引入对生产代码的意外依赖（仅测试数据/断言改动）。

---

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（Phase 划分、文件边界、依赖图） | 1 | 1 | 0 |
| R1.5 | 外部引用事实核查（L2120/2137/5832/5936/8499/8514/8524, `_core.py:422-427/4446-4449`, import L15, `now_iso` 先例 L3856/10823） | 0 | 0 | 0 |
| R2 | 可执行性（测试命令、验收二元性） | 1 | 1 | 0 |
| R2.8 | LLM 可执行性（改哪些行、验证命令、边界） | 2 | 2 | 0 |
| R3 | 风险与边缘（T2 codex.exe 连带、T3 断言无日期字面量、同文件并行冲突） | 3 | 3 | 0 |
| **终止** | **[T4] — 3 个目标测试全绿 + 全量回归无新增失败** | | | **0** |

### R1 记录
- 发现：T1.1/T2.1/T3.1 同文件 `test_orchestrator.py`，存在并行编辑冲突风险 → Wave 表注明建议串行执行修改。

### R2 记录
- 发现：全量测试耗时长（5-10min），V7 需 300s timeout 或降级为 `-k` → 在验收标准注明降级路径。

### R2.8 记录
- 发现：T3 修改需精确定位 L8508-8528（`patterns.jsonl` 构造处）→ 提供确切行号 + 代码片段。
- 发现：T1 改名需确认无其它引用 → 提供 `grep -c` 验证命令。

### R3 记录
- 发现：T2 可能还有 `cmd[0] == "codex.exe"` 连带断言 → 已核实 L5832 测试的 fake dispatch 不构造真实 cmd，无此断言。
- 发现：T3 断言可能含硬编码日期 → 已核实断言只含计数（`high_confidence=1, stale=1`），无日期字面量。
- 发现：T3 修复后需验证"不再时间依赖" → 验收要求跑 2 次（fresh/stale 相对当前时间恒成立）。

---

## Execution Log
（Task Executor 执行过程中回写）

### [YYYY-MM-DD HH:MM] Task X.Y — [STATUS]
- 结果：...
- 错误/阻塞：...
- 备注：...

### [2026-08-02 09:40] 全部 4 个 Task — COMPLETED

- **结果**：3 个 pre-existing 测试失败全部修复，全量回归 565 passed / 0 failed。
- **Commit**：`607b698` (test/loop_kit: sync 3 stale test expectations) — 仅含 3 处测试改动（13+/5-）。
- **关键处理**：测试文件 `tests/test_orchestrator.py` 在会话期间被 ATR daemon（PID 11007/11138，活跃）以未提交的 253 行格式重构（ruff 多行拆分）污染。为遵守"只提交计划内改动 + 负向验证"，采用 `git update-index --cacheinfo` 暂存 **HEAD + 仅我 3 处改动**的纯净 blob；daemon 的未提交格式改动保留在工作树（未丢失）。commit 后已恢复 daemon 混合版到工作树。
- **端到端验证**：3 个目标测试通过（T1 改名后、T2、T3 跑 2 次验时间独立）；V1-V7 全绿；P1 probe cost=1 印证新断言。

```json
{
  "error_id": null,
  "error_type": null,
  "summary": "3 个 pre-existing 测试失败修复完成：T1 cost(43,87)计费断言、T2 默认backend=opencode断言、T3 相对时间戳",
  "root_cause_guess": "snapshot 6783413 改生产常量未同步测试；T3 硬编码日期时间腐烂",
  "confidence": "HIGH",
  "retry_suggestion": null,
  "affected_files": ["tests/test_orchestrator.py"],
  "blocked_downstream": [],
  "task_id": "T1.1-T4.1",
  "attempted_fixes": [],
  "timestamp": "2026-08-02T09:40:00Z"
}
```
