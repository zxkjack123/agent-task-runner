---
topic: fix-preexisting-test-failures-2026-08-17
pm_task: 2748
pm_title: 修复 2 个预存在测试失败（test pollution 顺序依赖）
scope_mode: HOLD
repo: /home/gw/opt/agent-task-runner
git_commit: 7872db9
generated_at: 2026-08-17
status: draft
---

# 修复 2 个预存在测试失败（PM #2748）

## 背景与目标

- **问题**：`uv run --group dev pytest -m "not e2e" -q` 存在 2 个预存在失败：
  1. `TestCmdStatus::test_shows_context_file_stats` — **时间炸弹**（隔离运行即失败）
  2. `TestResetDefault::test_task_card_in_resettable_files` — **monkeypatch/模块全局污染**（顺序依赖，隔离运行通过）
- **根因（2026-08-17 已实测核实，与 task-fit-reviewer 记录一致）**：
  - 炸弹：`tests/test_orchestrator.py:8639` 硬编码 `"last_verified": "2026-04-01T12:00:00Z"` 作 fresh 样例，`PATTERN_STALE_DAYS=30`（`_core.py:440`）→ 已于 2026-05-02 过期
  - 污染：`tests/test_integration.py` 11 处直调生产函数 `orchestrator._configure_loop_paths()`（行 45/81/112/144/180/200/236/261/312/346/377），直改模块全局 `_stored_paths`（`_core.py:677`）无恢复；`tests/test_pm_integration.py` 另 3 处同类直调（行 27/278/302）。字母序 test_integration < test_orchestrator → 污染先发生；`test_orchestrator.py:62` 的 autouse fixture 快照到的已是污染值 → `TASK_CARD` 解析到 tmp 路径 ∉ import 时定值的 `_RESETTABLE_FILES`（`_core.py:744`）→ 断言失败
  - 同类隐患：`tests/test_orchestrator.py:3914` `"source_version": "2026-04-01T00:00:00Z"`（剪枝阈值 90 天，已于 2026-06-30 过期；`knowledge list` 路径暂不剪枝故未引爆）
- **目标**：全量 0 failed 且连续 2 次结果一致；两目标测试隔离运行通过；不引入新失败。
- **非目标**：不改被测代码（`src/loop_kit/**` 禁止）；不修 #2622 会话的任何文件；不新增依赖；不引入新测试。

## 关键已核实事实（Plan Architect 实测，含与简报差异修正）

| 项 | 值 | 备注 |
|---|---|---|
| HEAD | `7872db9` | ⚠️ 用户简报为 `7ab322b`，实际晚 1 个 commit |
| 脏工作区 | `M src/loop_kit/_core.py`、`M tests/test_orchestrator.py`（42 hunks，#2622 格式化+12 测试）、`M .github/plans/pm2622-doc-pipeline.md`、`?? traces/`、`?? .github/plans/backup/` | ⚠️ 简报漏列 `M .github/plans/pm2622-doc-pipeline.md`；**全部严禁卷入本任务 commit** |
| index | 空（无预 staged） | 合成补丁前提 ✓ |
| 炸弹锚点 | `tests/test_orchestrator.py:8639`，行内容 `"last_verified": "2026-04-01T12:00:00Z"` | 文件内唯一 |
| 隐患锚点 | `tests/test_orchestrator.py:3914`，行内容 `"source_version": "2026-04-01T00:00:00Z"` | 文件内唯一 |
| 污染泄漏源 | test_integration.py 11 处 + test_pm_integration.py 3 处直调生产 `_configure_loop_paths` | ⚠️ 简报只提 1 处（:378，实际 :377）；共 14 处 |
| conftest | **不存在**（`tests/conftest.py` 无，仓库根亦无） | 需新建 |
| pytest 配置 | `pyproject.toml`：testpaths=["tests"]，addopts=`-m "not e2e"`，markers: e2e/integration | 全量命令自带 e2e 排除 |
| dev 依赖 | pytest>=9.0.2、pytest-timeout、ruff | **无** freezegun/pytest-randomly/time-machine |
| 测试文件 import | `tests/test_orchestrator.py:16` 已有 `from datetime import UTC, datetime, timedelta` | 相对日期方案零新 import |
| 既有防护 | `test_orchestrator.py:62-84` 已有 file-scope autouse fixture（快照/恢复 8 全局） | conftest 方案的原型 |
| 非炸弹日期（不动） | `:3347-3456` failed_at/started_at "2026-01-01"（故意过期，测清理逻辑）；`:12372-12373` recent/older 相对排序纯函数；`:8646` stale 样例 "2025-01-01"（故意过期） | 见 T2.3 分类规则 |

## 修改方案

### DECISION 1 — 时间炸弹：相对日期方案（选定） vs 冻结时间方案（否决）

```
DECISION: 测试内运行时计算相对日期 —— fresh_last_verified = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
ALTERNATIVES: (a) monkeypatch 冻结时间；(b) 引入 freezegun
RATIONALE: 相对日期零新依赖、自文档化、永久免疫；冻结时间需 patch _core.py:8462 等内部的 datetime.now(UTC) 引用（耦合脆弱，且冻结值本身会成为新炸弹）；freezegun 需新增依赖（超出 HOLD 范围）。文件已 import UTC/datetime/timedelta。
RISK: 若未来 fresh 阈值（30 天）被改成 <5 天会再炸 —— 缓解：T2.3 扫描规则注明 margin 建议 ≥ 阈值一半；本次 5 天 << 30 天，安全余量充足。
```

### DECISION 2 — 污染修复：conftest autouse fixture（选定） vs 调用点 monkeypatch 逐一修复（否决）

```
DECISION: 新建 tests/conftest.py，suite 级 autouse fixture 快照/恢复与既有 file-scope fixture 相同的 8 个模块全局
ALTERNATIVES: 14 处调用点逐一改 monkeypatch（test_integration 11 + test_pm_integration 3）
RATIONALE: (1) 泄漏源实为 14 处（简报仅 1 处），逐点修复 churn 大且每处需核对该测试是否依赖 _stored_paths 被真实设置（非纯机械替换，:44 的 stub 模式不一定适用于全部 14 处）——conftest 在测试结束统一恢复，测试体内行为不变，零风险；(2) 根治同类问题（未来新增泄漏自动兜底）；(3) 与既有 file-scope fixture 同构、幂等（fixture 嵌套顺序：conftest 先 setup 后 teardown，两者快照值一致时双重恢复无副作用）；(4) 与 #2622 工作区零交集（新文件），stage 无 hunk 隔离负担。
RISK: 可能暴露依赖污染的隐性测试 —— 按验收条件 3：立即停止并回报，不擅自修复。缓解：T2.2 单独全量验证、T3.1 连续 2 次全量，任何第 3 个失败即刻阻断。
```

### DECISION 3 — source_version 隐患：同修（选定） vs 仅记录（否决）

```
DECISION: 本计划顺带修复（同 DECISION 1 相对日期化）
RATIONALE: 同类时间炸弹、同一文件、+1 行成本；90 天阈值下已于 2026-06-30 过期，任何路径一旦启用按 source_version 剪枝即引爆。task-fit-reviewer 亦建议同修。
RISK: 极低——该测试断言仅涉及 pattern 文本/category，与日期无关。
```

### DECISION 4 — commit 隔离：合成补丁 + `git apply --cached`（选定） vs `git add -p` 交互（否决）

```
DECISION: 先快照工作区文件 → 做编辑 → git diff --no-index 生成只含本任务改动的补丁 → git apply --cached 只把本任务 hunk 写入 index
RATIONALE: git add -p 为交互式，agent 无法可靠驱动；git add <file> 会把 #2622 的 42 hunks 一并卷入。合成补丁完全确定性。两处编辑锚点（:3914、:8639）经核实均距 #2622 最近 hunk ≥49 行，上下文与 HEAD 一致 → 补丁可干净 apply 到 index。
RISK: 若 #2622 会话在快照后、apply 前又改动同文件 → `git apply --cached --check` 会失败。缓解：--check 干跑门禁 + 新鲜快照重试一次 + 失败即升级（严禁退化为 git add 整文件）。
```

### 假设清单

1. `[假设: 执行期间 #2622 会话不改动 tests/test_orchestrator.py]` — 若改动，T3.2 的 --check 门禁捕获，走重试路径；影响有限。
2. `[假设: 执行期间 HEAD 仍为 7872db9]` — 同上。
3. `[假设: knowledge list 路径不按 source_version 剪枝]` — 已间接验证（该测试当前通过）；即便启用剪枝，相对日期方案同样安全，假设错误无影响。
4. `[假设: 全量套件运行时长为分钟级]` — bash 工具 timeout 需 ≥600s（见 V1）。
5. `[假设: 除已列 2 失败外无其它预存在失败]` — T1.1 基线验证；若不符，立即停止并回报。

### Red-Team 摘要（阶段 2.5 内审）

- RT-1 #2622 并发改写 → --check 门禁 + 重试 + 升级 ✓ 已入 DECISION 4
- RT-2 conftest 暴露隐性顺序依赖 → 验收条件 3 阻断 + T3.1 双跑 ✓
- RT-3 相对日期误在 import 期求值 → 插入行限定在测试函数体内（modify_specs 明确锚点）✓
- RT-4 时区/格式解析兼容 → `_parse_utc_iso8601` 已验证支持 "Z" 后缀；`%Y-%m-%dT%H:%M:%SZ` 与其输出 `_to_utc_iso8601` 格式一致 ✓
- RT-5 conftest 与 file-scope fixture 冲突 → 幂等（同集合快照）✓
- RT-6 其它隐藏炸弹 → T2.3 只读扫描 + 分类规则闭环 ✓
- RT-7 计划文件/临时文件被卷入 commit → T3.2 显式逐文件 stage + `git show --stat` 门禁 ✓
- RT-8 #2622 的 +12 测试将来 commit 后是否受 conftest 影响 → 其所在文件已有等价 autouse fixture，conftest 不改变其行为；记录于风险表 ✓

## 执行计划

### Phase 1: 基线确认（修复前）

#### Task 1.1: 基线全量 + 隔离差分复现

- **目标**：确认当前失败集合恰为 2 个已知失败；复现两种失败机理的差异特征。
- **依赖**：无
- **frontier**：是
- **执行者**：task-executor（直接执行，不走 ATR）
- **修改内容**：无（只读 + 跑测试）
- **modify_specs**：无
- **修改边界**：不得修改任何文件；不得 git add/commit
- **质量检查方式**：
  - 检查项 1：全量失败集合 == `{TestCmdStatus::test_shows_context_file_stats, TestResetDefault::test_task_card_in_resettable_files}`
  - 检查项 2：隔离运行炸弹测试 → FAIL（证明时间炸弹）；隔离运行污染测试 → PASS（证明顺序依赖）
- **验收标准**：
  - ✅ 全量输出失败名单与上述集合完全一致（若出现第 3 个失败 → **立即停止并回报，不得继续**）
  - ✅ 记录基线 passed/failed 计数与用时（供 T3.1 一致性比对参考，passed 计数不作为判据）
- **执行命令**（bash timeout 建议 ≥600s）：
  ```bash
  uv run --group dev pytest -m "not e2e" -q 2>&1 | tail -30
  uv run --group dev pytest -m "not e2e" -q "tests/test_orchestrator.py::TestCmdStatus::test_shows_context_file_stats"
  uv run --group dev pytest -m "not e2e" -q "tests/test_orchestrator.py::TestResetDefault::test_task_card_in_resettable_files"
  ```
- **潜在风险**：#2622 未提交的 +12 测试若自身失败会污染基线判断 → 若失败名单超出 2 个，停止并回报（勿尝试修复 #2622 内容）。
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：

### Phase 2: 修复实施

#### Task 2.1: 时间炸弹 + source_version 同修（tests/test_orchestrator.py 两处日期相对化）

- **目标**：消除 2 处硬编码 fresh 日期（时间炸弹 + 同类隐患），永久免疫。
- **依赖**：T1.1
- **frontier**：是
- **执行者**：task-executor（直接执行，不走 ATR）
- **修改内容**（**先做快照再编辑，快照供 T3.2 使用**）：
  1. 执行 `cp tests/test_orchestrator.py /tmp/tor.pre2748.py`（快照仅含 #2622 改动）
  2. 文件 `tests/test_orchestrator.py`（repo-root-relative）：**编辑前必须先用 grep 复核锚点字符串存在且唯一**，共 4 处修改（2 插入 + 2 替换）
- **modify_specs**：
  - `{file: tests/test_orchestrator.py, action: add, target: "test_shows_context_file_stats 函数体内 `(context_dir / \"patterns.jsonl\").write_text(` 语句之前", description: "插入一行（8 空格缩进，函数体内）: fresh_last_verified = (datetime.now(UTC) - timedelta(days=5)).strftime(\"%Y-%m-%dT%H:%M:%SZ\")"}`
  - `{file: tests/test_orchestrator.py, action: modify, target: "唯一字符串 `                    \"last_verified\": \"2026-04-01T12:00:00Z\",`（20 空格缩进）", description: "替换为 `                    \"last_verified\": fresh_last_verified,`（缩进不变）"}`
  - `{file: tests/test_orchestrator.py, action: add, target: "test_knowledge_list_prints_table_with_category_filter 函数体内 `_write_jsonl(\n            patterns_path,` 语句之前", description: "插入一行（8 空格缩进，函数体内）: fresh_source_version = (datetime.now(UTC) - timedelta(days=5)).strftime(\"%Y-%m-%dT%H:%M:%SZ\")"}`
  - `{file: tests/test_orchestrator.py, action: modify, target: "唯一字符串 `                    \"source_version\": \"2026-04-01T00:00:00Z\",`（20 空格缩进）", description: "替换为 `                    \"source_version\": fresh_source_version,`（缩进不变）"}`
  - ⛔ 禁止用模糊文件名——完整路径 `tests/test_orchestrator.py`
- **修改边界**：
  - 不得修改该文件其它任何行（尤其 #2622 的 42 个 hunk 区域）
  - 不得修改 `src/loop_kit/**`、`tests/test_integration.py`、`tests/test_pm_integration.py`
  - 不得修改 `:3347-3456`、`:12372-12373`、`:8646`（分类为非炸弹，见 T2.3）
  - 插入行必须位于**测试函数体内**（运行时求值），不得放模块级
- **质量检查方式**：
  - 检查项 1：`grep -n "2026-04-01T12:00:00Z\|2026-04-01T00:00:00Z" tests/test_orchestrator.py` → 无输出（旧字面量已消失）
  - 检查项 2：`grep -n "fresh_last_verified\|fresh_source_version" tests/test_orchestrator.py` → 各 2 处（定义 + 使用）
  - 检查项 3：`git diff --no-index /tmp/tor.pre2748.py tests/test_orchestrator.py | grep -c "^@@"` → == 2 个 hunk
- **验收标准**：
  - ✅ `uv run --group dev pytest -m "not e2e" -q "tests/test_orchestrator.py::TestCmdStatus::test_shows_context_file_stats"` → 1 passed
  - ✅ `uv run --group dev pytest -m "not e2e" -q "tests/test_orchestrator.py::TestKnowledgeCli"` → 全 passed
- **潜在风险**：若锚点字符串不唯一或行号漂移 → 停止，按字符串重新定位；严禁按旧行号盲改。
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：

#### Task 2.2: 污染根治 —— 新建 tests/conftest.py（suite 级 autouse fixture）

- **目标**：一次性消除跨文件模块全局污染（test_integration 11 处 + test_pm_integration 3 处直调泄漏）。
- **依赖**：T1.1
- **frontier**：是
- **执行者**：task-executor（直接执行，不走 ATR）
- **修改内容**：
  - 新建文件 `tests/conftest.py`，内容**逐字节使用附录 A**（不得改写）
- **modify_specs**：
  - `{file: tests/conftest.py, action: add, target: "新文件", description: "按附录 A 完整内容创建；fixture 名 _isolate_orchestrator_module_globals；快照/恢复 8 个模块全局（ROOT/_stored_paths/_FEED_TASK_ID/_FEED_ROUND/_FEED_RUN_ID/_FEED_TASK_ROUTE_POLICY/_LOGS_DIR_ENSURED/_LOGS_DIR_ENSURED_PATH），恢复顺序与 test_orchestrator.py:62-84 既有 fixture 一致"}`
- **修改边界**：
  - 不得修改任何既有测试文件；不得修改 `src/loop_kit/**`
  - conftest.py 内不得引入新依赖、不得 import 除 `pytest` 与 `loop_kit.orchestrator` 之外的模块
- **质量检查方式**：
  - 检查项 1：`uv run python -m py_compile tests/conftest.py` → exit 0
  - 检查项 2：fixture 恢复集合与 `tests/test_orchestrator.py:62-84` 完全一致（逐字段比对）
- **验收标准**：
  - ✅ `uv run --group dev pytest -m "not e2e" -q tests/test_integration.py tests/test_pm_integration.py "tests/test_orchestrator.py::TestResetDefault::test_task_card_in_resettable_files"` → 1 passed（两泄漏文件在前序运行仍通过）
  - ✅ 全量 `uv run --group dev pytest -m "not e2e" -q` → 失败名单 **恰好只剩** `TestCmdStatus::test_shows_context_file_stats`（时间炸弹由 T2.1 负责；若出现第 3 个失败 → **立即停止并回报**）
- **潜在风险**：conftest 暴露隐性顺序依赖（验收条件 3 场景）——按要求阻断回报，不擅自修复。
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：

#### Task 2.3: 同类日期炸弹扫描（只读审计）

- **目标**：确认仓库中不存在其它"fresh 期望 + 硬编码日期"炸弹；对全部日期字面量给出分类结论。
- **依赖**：无
- **frontier**：是
- **执行者**：task-executor（直接执行，不走 ATR）
- **修改内容**：无（只读）
- **modify_specs**：无
- **修改边界**：只读；不得修改任何文件（发现新炸弹也**只报告**，不擅自修复）
- **质量检查方式**：
  - 检查项 1：扫描命令覆盖 tests/ 全目录：`grep -rnE '20[2-9][0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-6][0-9]:[0-6][0-9]Z?' tests/`
  - 检查项 2：对每个命中按分类规则判定并留档
- **分类规则（确定性判定）**：
  - **炸弹（fresh 期望 + 硬编码日期）**：若日期字段用于"未过期"语义（last_verified/source_version 期望 fresh）且距执行日 > 对应阈值（30/90 天）→ 必须报 `BOMB`。已知 2 处（:8639、:3914）由 T2.1 修复，本任务复核确认无第 3 处。
  - **安全（故意过期）**：日期用于"已过期"语义（stale 清理/心跳过期断言，如 :3347-3456、:8646 的 2025-01-01）→ `OK-STALE`，永久稳定，不动。
  - **安全（纯排序/纯函数）**：日期仅参与相对排序无 now 比较（:12372-12373 recent/older）→ `OK-RELATIVE-ONLY`，不动。
  - **安全（非时效字段）**：failed_at/started_at 等仅作数据回显或非阈值比较 → `OK-NON-TEMPORAL`，不动。
- **验收标准**：
  - ✅ 产出分类清单（写入任务报告，不落盘）且 BOMB 类 == 2（即 T2.1 的两处）；若有第 3 处 BOMB → 停止并回报（不擅自扩范围）
- **潜在风险**：无（只读）。
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：

### Phase 3: 联合验证与提交

#### Task 3.1: 全量/隔离/组合三套验证（连续 2 次一致）

- **目标**：满足全部验收条件。
- **依赖**：T2.1、T2.2、T2.3
- **frontier**：否
- **执行者**：task-executor（直接执行，不走 ATR）
- **修改内容**：无（只读 + 跑测试）
- **modify_specs**：无
- **修改边界**：不得修改任何文件
- **验收标准**（全部满足，bash timeout ≥600s）：
  - ✅ V1：`uv run --group dev pytest -m "not e2e" -q` 连续 2 次 → 两次均 **0 failed**，且两次输出**完全一致**（failed/passed/error 计数逐项一致；passed 绝对数与 T1.1 基线可不同，因 #2622 未提交状态浮动）
  - ✅ V2（隔离）：两个目标测试各自隔离运行 → 各 1 passed：
    - `uv run --group dev pytest -m "not e2e" -q "tests/test_orchestrator.py::TestCmdStatus::test_shows_context_file_stats"`
    - `uv run --group dev pytest -m "not e2e" -q "tests/test_orchestrator.py::TestResetDefault::test_task_card_in_resettable_files"`
  - ✅ V3（组合，污染回归）：`uv run --group dev pytest -m "not e2e" -q tests/test_integration.py tests/test_orchestrator.py` → 0 failed（integration 先序运行制造污染，orchestrator 必须全绿）
  - ✅ V4（第二泄漏源回归）：`uv run --group dev pytest -m "not e2e" -q tests/test_pm_integration.py tests/test_orchestrator.py` → 0 failed
  - ✅ 任何一次出现计划外失败 → 停止并回报（验收条件 3）
- **潜在风险**：V1 两次之间若有环境抖动（pytest-timeout 边界）→ 第三次复跑确认；仍不一致则回报。
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：

#### Task 3.2: 合成补丁 hunk 级 commit + PM #2748 同步

- **目标**：只把本任务的 2 个文件改动 commit；#2622 工作区文件零卷入。
- **依赖**：T3.1（全部验收通过后执行）
- **frontier**：否
- **执行者**：task-executor（直接执行，不走 ATR）
- **修改内容**：仅 git 操作（附录 B 命令序列，逐条执行、逐条验证）
- **modify_specs**：无（文件修改已在前置任务完成）
- **修改边界**：
  - 🚫 禁用：`git add -A`、`git add .`、`git commit -am`、`git commit --include`、`git stash`、`git reset --hard`、`git checkout -- tests/test_orchestrator.py`（任何 checkout 会毁掉 #2622 未提交改动）
  - 只允许 stage：`tests/conftest.py`（整文件，新文件）+ `tests/test_orchestrator.py` 中经合成补丁的 2 个 hunk
- **验收标准**：
  - ✅ `git diff --cached --stat` == 恰好 `tests/conftest.py` + `tests/test_orchestrator.py`（后者 2 个 hunk、约 4 行）
  - ✅ `git diff --cached tests/test_orchestrator.py | grep -c "^@@"` == 2
  - ✅ commit 成功；`git show --stat HEAD` 只含上述 2 文件
  - ✅ commit 后 `git status --short` 仍显示 #2622 全部脏项原样存在：`M .github/plans/pm2622-doc-pipeline.md`、`M src/loop_kit/_core.py`、`M tests/test_orchestrator.py`（残留 #2622 hunks，`git diff tests/test_orchestrator.py | grep -c "^@@"` 与基线 42 一致）、`?? traces/`、`?? .github/plans/backup/`
  - ✅ commit message 含 `#2748`（post-commit hook 自动同步 PM；随后用 `pm_task_get(2748)` 复核 progress 已更新——若 hook 未同步，委派 PM Coordinator 更新 #2748 status/progress）
- **commit message**：`fix(tests): relative-date freshness samples + suite-wide path-global isolation (#2748)`
- **潜在风险**：`git apply --cached --check` 失败（#2622 并发改写）→ 按附录 B 重试路径；重试仍失败 → 升级回报，**严禁**退化为 `git add tests/test_orchestrator.py`。
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|-----------|
| W1 | T1.1 | T1.1 | — |
| W2 | T2.1, T2.2, T2.3 | T2.1, T2.2, T2.3（T2.1 改 tests/test_orchestrator.py，T2.2 新建 tests/conftest.py，T2.3 只读——三者无文件冲突，可并行） | W1 |
| W3 | T3.1 | —（需 T2.1+T2.2+T2.3 全部完成） | W2 |
| W4 | T3.2 | —（需 T3.1 全绿） | W3 |

## Post-Execution Verification

Task Executor 在全部 plan task 执行完毕后**必须**运行本节验证命令。

### Automated Verification（Task Executor 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量双跑一致性（主判据） | `uv run --group dev pytest -m "not e2e" -q`（连续 2 次，timeout ≥600s） | 两次均 0 failed 且输出一致 |
| V2 | 目标测试隔离运行 | `uv run --group dev pytest -m "not e2e" -q "tests/test_orchestrator.py::TestCmdStatus::test_shows_context_file_stats"` 与 `"...::TestResetDefault::test_task_card_in_resettable_files"` | 各 1 passed |
| V3 | 组合运行（污染回归） | `uv run --group dev pytest -m "not e2e" -q tests/test_integration.py tests/test_orchestrator.py` | 0 failed |
| V4 | 第二泄漏源回归 | `uv run --group dev pytest -m "not e2e" -q tests/test_pm_integration.py tests/test_orchestrator.py` | 0 failed |
| V5 | commit 内容边界 | `git show --stat HEAD` | 仅 tests/conftest.py + tests/test_orchestrator.py |
| V6 | #2622 工作区零卷入 | `git status --short` + `git diff tests/test_orchestrator.py \| grep -c "^@@"` | 脏文件集合与基线一致；残留 42 hunks |

### Deferred (needs restart / deployment)
- （无）

### Probe (best-effort, run if available)
- [ ] P1: `git log --oneline -1` 确认含 `#2748`；`pm_task_get(2748)` 确认 hook 已同步 progress —— 若未同步，委派 PM Coordinator 补齐
- [ ] P2: `/tmp/tor.pre2748.py`、`/tmp/tor.2748.patch` 清理（`rm` 临时文件，属 /tmp 自清理区，可选）

### Manual（真正需要人工判断）
- [ ] M1: 若任一验证出现**计划外失败**（第 3 个失败）→ 停止执行并上报（不擅自顺带修复）；由人工判断是否与 #2622 未提交状态相关
- [ ] M2: 计划执行完毕后，由 doc-maintainer 将本计划归档至 `.github/plans/completed/`（异步，非本任务阻塞项）

## 风险与回滚

| 风险 | 概率 | 影响 | 缓解/回滚 |
|------|------|------|-----------|
| #2622 会话在 T2.1 快照后、T3.2 apply 前改写 tests/test_orchestrator.py | 低 | 中 | `--check` 干跑门禁；新鲜快照重试 1 次；仍失败 → 升级（禁 git add 整文件） |
| conftest 暴露隐性顺序依赖（新失败） | 低 | 中 | 验收条件 3 阻断；T2.2 单独全量验证先行定位；回报人工 |
| T2.1 编辑时行号漂移/字符串非唯一 | 低 | 中 | 编辑前 grep 复核唯一性；按字符串锚定，禁按旧行号盲改 |
| 全量套件超时（pytest-timeout/整体时长） | 中 | 低 | bash timeout ≥600s；必要时 V1 分批（test_orchestrator.py 单独一包）复跑确认 |
| commit 回滚需求 | 低 | 低 | **未 commit**：`git apply -R /tmp/tor.2748.patch`（tests/test_orchestrator.py）+ `rm tests/conftest.py`。**已 commit**：`git revert <sha>`（我方 hunk 上下文与 #2622 改动区域不相交，3-way 应用可干净落回）；若 revert 冲突 → 手动反向编辑 + 新 commit（fix-forward）。🚫 任何情况下禁止 `git reset --hard` / `git clean`（毁 #2622 工作区） |

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（任务粒度/边界/frontier） | 2（简报与实际 HEAD/脏文件不符；污染源 14 处而非 1 处） | 2 | 0 |
| R1.5 | 外部引用事实核查（锚点行号、fixture、函数存在性、pyproject 配置、依赖清单、index 状态） | 1（简报 :378 → 实际 :377；:3914/:8639 唯一性已验） | 1 | 0 |
| R2 | 可执行性（命令逐条核验；合成补丁机制推演 + `git apply --cached` 流程检查） | 1（`git diff --no-index` 退出码 1 需容错） | 1 | 0 |
| R2.8 | LLM 可执行性审查（逐字段消除歧义：modify_specs 锚点/插入位置/缩进/禁止清单/回滚路径全显式） | 0 | 0 | 0 |
| R3 | 风险与边缘（RT-1..8 红队；跨 task 一致性：T2.1 快照与 T3.2 补丁衔接、T3.1 依赖顺序） | 1（回滚路径补充 fix-forward 分支） | 1 | 0 |
| **终止** | **[T1] — 审查 issue 全部清零，计划输出** | | | **0** |

## 附录 A：tests/conftest.py 完整内容（逐字节复制，不得改写）

```python
"""Suite-wide isolation for loop-kit module-global path state.

The production function ``loop_kit.orchestrator._configure_loop_paths()``
mutates module-level globals (``_stored_paths``, ``_LOGS_DIR_ENSURED``,
``_LOGS_DIR_ENSURED_PATH``) and several test files call it directly without
restoring afterwards (tests/test_integration.py, tests/test_pm_integration.py).
Without a suite-level autouse fixture that state leaks across test files within
the same pytest session (files run in alphabetical order), so later files
observe polluted paths — the pre-existing failure tracked in PM #2748.

This fixture generalizes the file-scoped ``_isolate_orchestrator_path_globals``
fixture in tests/test_orchestrator.py to the whole suite: it snapshots the same
set of mutable module globals before every test and restores them afterwards.
Restoring is idempotent with the file-scoped fixture (both restore their own
snapshots, which are equal when the suite state is clean).
"""

from __future__ import annotations

import pytest

from loop_kit import orchestrator


@pytest.fixture(autouse=True)
def _isolate_orchestrator_module_globals() -> None:
    original_root = orchestrator.ROOT
    original_stored_paths = orchestrator._stored_paths
    original_feed_task_id = orchestrator._FEED_TASK_ID
    original_feed_round = orchestrator._FEED_ROUND
    original_feed_run_id = orchestrator._FEED_RUN_ID
    original_feed_route_policy = orchestrator._FEED_TASK_ROUTE_POLICY
    original_logs_ensured = orchestrator._LOGS_DIR_ENSURED
    original_logs_ensured_path = orchestrator._LOGS_DIR_ENSURED_PATH
    yield
    orchestrator.ROOT = original_root
    orchestrator._stored_paths = original_stored_paths
    orchestrator._set_feed_task_id(original_feed_task_id)
    orchestrator._set_feed_round(original_feed_round)
    orchestrator._set_feed_run_id(original_feed_run_id)
    orchestrator._set_feed_task_route_policy(original_feed_route_policy)
    orchestrator._LOGS_DIR_ENSURED = original_logs_ensured
    orchestrator._LOGS_DIR_ENSURED_PATH = original_logs_ensured_path
```

## 附录 B：T3.2 合成补丁 commit 命令序列（逐条执行、逐条验证）

```bash
# ── 前置确认 ──────────────────────────────────────────────
git rev-parse --short HEAD                          # 期望 7872db9（若漂移→记下新 HEAD 并回报）
git diff --cached --stat                            # 期望空（index 无预 staged）

# ── 步骤 1：生成只含本任务改动的补丁（快照必须与当前工作区“本任务编辑前”状态一致）──
# 注意：/tmp/tor.pre2748.py 快照在 T2.1 已生成；若期间 #2622 又改过该文件，先重新快照：
#   cp tests/test_orchestrator.py /tmp/tor.pre2748.py
git diff --no-index -- /tmp/tor.pre2748.py tests/test_orchestrator.py > /tmp/tor.2748.patch; true
sed -i '1s|a/tmp/tor\.pre2748\.py|a/tests/test_orchestrator.py|' /tmp/tor.2748.patch

# ── 步骤 2：补丁自检（必须全过，任一不过→重新快照重试 1 次→仍不过→升级回报）──
grep -c '^@@' /tmp/tor.2748.patch                   # 期望 2（恰好 2 个 hunk）
grep '^+' /tmp/tor.2748.patch | grep -v '^+++'      # 期望仅 4 行新增（2 个 fresh_* 定义 + 2 处使用替换的 + 行）
grep -n "2026-04-01T12:00:00Z\|2026-04-01T00:00:00Z" /tmp/tor.2748.patch  # 期望无输出（旧字面量不出现）
git apply --cached --check /tmp/tor.2748.patch      # 干跑门禁：必须无输出、exit 0

# ── 步骤 3：只把本任务改动写入 index ──────────────────────────
git apply --cached /tmp/tor.2748.patch
git add tests/conftest.py                           # 新文件整文件 stage（安全）

# ── 步骤 4：stage 边界核验（必须全过，任一不过→git reset（仅 unstage，禁止 --hard）后排查）──
git diff --cached --stat                            # 期望仅 tests/conftest.py + tests/test_orchestrator.py
git diff --cached tests/test_orchestrator.py | grep -c '^@@'   # 期望 2
git diff --cached | grep -E '^\+' | grep -v '^+++'  # 人工目检：仅 4 行新增 + conftest 内容

# ── 步骤 5：提交 ─────────────────────────────────────────────
git commit -m "fix(tests): relative-date freshness samples + suite-wide path-global isolation (#2748)"

# ── 步骤 6：提交后核验（必须全过）──────────────────────────────
git show --stat HEAD                                # 仅 tests/conftest.py + tests/test_orchestrator.py
git status --short                                  # #2622 脏项原样：M .github/plans/pm2622-doc-pipeline.md、M src/loop_kit/_core.py、M tests/test_orchestrator.py、?? traces/、?? .github/plans/backup/
git diff tests/test_orchestrator.py | grep -c '^@@' # 期望 42（#2622 残留 hunks 与基线一致）

# ── 步骤 7：PM 同步核验 ──────────────────────────────────────
git log --oneline -1                                # 含 #2748
# pm_task_get(2748) 复核 progress 已由 post-commit hook 更新；
# 若未更新 → 委派 PM Coordinator：pm_task_update(2748, progress=100, status=review)
```

> 🚫 全程禁止：`git add -A` / `git add .` / `git commit -am` / `git stash` / `git reset --hard` / `git clean` / `git checkout -- tests/test_orchestrator.py`。


## CT 审阅合入（2026-08-17，critical-thinking 裁定）

### 🔴 W2 波次与验收标准冲突（必须执行）
1. **T2.3 移入 W1**（只读、无依赖，其验收仅在 pre-T2.1 状态下有意义）
2. **T2.2 全量验收改为状态感知判据**：失败名单 ∈ {∅, {TestCmdStatus::test_shows_context_file_stats}} 均通过（取决于并行 T2.1 是否已落地）；出现任何其他失败 → STOP 回报
3. 若 T2.1/T2.2 实际并行执行，以"修复后最终全量 0 failed"为唯一硬判据，中间态名单不触发 STOP

### 🟡 执行时注意
1. D4 风险归因修正：`git apply --cached` 应用对象是 index（=HEAD），不是工作区——#2622 未提交编辑不会导致 --check 失败；真正拦截面是补丁自检（`grep -c '^@@' == 2` 与 `grep '^+' == 4 行`），该自检已覆盖
2. 非炸弹日期清单补齐：:10424-10425、test_integration.py:59/:272、test_pm_integration.py:225 均为非炸弹，T2.3 分类时留档即可
3. T2.3 grep 用 `grep -I` 排除 __pycache__/*.pyc 噪声

## Execution Log

### Post-Execution Verification Log（2026-08-17，task-executor）

| ID | Result |
|----|--------|
| V1 | ✅ PASS — 全量双跑均 `614 passed, 1 skipped, 3 deselected, 1 warning, 0 failed`，输出一致（T3.1 两跑 + 提交后两跑共 4 次全量一致） |
| V2 | ✅ PASS — 两目标测试隔离运行各 1 passed |
| V3 | ✅ PASS — `tests/test_integration.py tests/test_orchestrator.py` → 578 passed, 0 failed |
| V4 | ✅ PASS — `tests/test_pm_integration.py tests/test_orchestrator.py` → 588 passed, 0 failed |
| V5 | ✅ PASS — commit `768ffb1` 仅含 tests/conftest.py + tests/test_orchestrator.py（+47/-2） |
| V6 | ✅ PASS — #2622 脏项原样（M×3 + ?? traces/ backup/），残留 42 hunks |
| P1 | ✅ PASS — commit message 含 #2748；pm_task_get(2748) 确认 hook 已同步 status=done, progress=100 |
| P2 | ✅ PASS — /tmp/tor.pre2748.py、/tmp/tor.2748.patch 已清理 |
| M1 | ✅ 无需人工判断 — 全程无计划外失败（失败名单始终 ∈ {∅, {bomb}}） |
| M2 | ⏸ 待 doc-maintainer 归档（异步，非阻塞） |

**执行偏差记录**：
1. 附录 B 步骤 2 `grep -c '^@@'` 期望 2 实得 3：diff 算法在 source_version 区域将"插入+替换"拆为 2 个 hunk（变更点间隔 9 行 > 6 行合并阈值）；last_verified 区域合并为 1 个 hunk。补丁内容经人工核验纯净（+4 行全为本任务 fresh_* 内容），非错误。
2. 附录 B 步骤 2 `grep -n "2026-04-01..."` "期望无输出"表述不严谨：旧字面量正确出现在 `-` 删除行（2 处），`+` 新增行零旧字面量——已按正确判据执行。
3. 附录 B sed 命令（`sed -i '1s|...|'`）仅替换补丁第 1 行路径，`---` 旧路径行未替换导致 `git apply --cached --check` 报 `tmp/tor.pre2748.py: does not exist in index`。已改用 `sed -i 's|...|...|g'` 全局替换补丁路径后通过门禁（落实附录 B 本意，非计划外操作）。
4. `git status --short` 存在 2 个计划未列出的未跟踪文件（`.github/plans/_project-snapshot.md`、`.github/plans/fix-preexisting-test-failures-2026-08-17.md`），均为执行环境产物，未卷入 commit。
