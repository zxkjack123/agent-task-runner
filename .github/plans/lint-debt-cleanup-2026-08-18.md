---
plan_schema_version: "1.0"
topic: "lint-debt-cleanup"
scope_mode: "HOLD"
status: "ready"
linked_task: "PM #2749"
git_commit: "011d55e"
generated_at: "2026-08-18"
workspace: "/home/gw/opt/agent-task-runner"
---

# 执行计划：环境残留清理 + 104 个 ruff lint 错误修复（PM #2749）

> 修订说明：本计划为就地新建（无历史版本）。执行中如单批失败，用 `mode=improve` 回流本计划。
> 所有文件路径均为 repo-root-relative（基于 `/home/gw/opt/agent-task-runner`）。

## 背景与目标

- **问题**：
  1. `.loop/` 下残留 #2675 执行期的瞬态数据（`.state.json.bak`、`events.jsonl` 510KB、`archive/`、`handoff/`、`logs/` 等）
  2. `ruff check src/loop_kit tests` 报 **104 个 lint errors**（2026-08-18 实测；src/loop_kit 70、tests 34）
  3. CI 门禁 `.github/workflows/loop-ci.yml:67-68` 存在 ruff 检查（无 continue-on-error），当前必然红
- **目标**：
  - A：清除 .loop 瞬态残留，tracked 文件处置有明确决策
  - B：ruff 0 error；全量 pytest（`-m "not e2e"`）不新增失败
  - C：CI ruff 门禁红转绿（本地等价命令验证 + push 触发）
- **非目标**：不改函数签名/行为语义；不重构；不引入新依赖；不 git-track 化 `.loop/tests/e2e` fixture（记入后续建议）

## 关键事实基线（2026-08-18 实测）

| 项 | 值 | 核实方式 |
|----|----|---------|
| git HEAD | `011d55e`，工作区干净 | `git status` |
| lint 总数 | 104 errors（52 fixable by --fix） | `ruff check src/loop_kit tests` |
| 规则分布 | E501 35、RUF100 20、I001 16、F841 7、F401 7、RUF059 6、RUF022 3、E401 3、SIM105 2、E702 2、F541 1、SIM117 1、UP017 1 | 同命令 concise 输出统计 |
| F401 位置 | **全部 7 个在 tests/**；src 无 F401 | 逐条核对 |
| RUF100 位置 | 20 个全在 src 10 个子模块（每文件 2 处：L7 `# noqa: F401,F403`、L8 `# noqa: F401`） | 逐条核对 |
| ruff 配置 | `pyproject.toml [tool.ruff]` line-length=120，select E/F/W/I/UP/B/SIM/RUF | 读配置 |
| pytest 基线 | 615 passed / 0 failed（`uv run --group dev pytest -q`，addopts 排除 e2e） | 用户实测，T2.1 复核 |
| CI 门禁 | loop-ci.yml:67-68 `uv run --group dev ruff check src/loop_kit tests` | grep 核实 |
| B1 模拟 | 在 /tmp 副本实测 `ruff check --fix`：**52 fixed + 10 个 E501 顺带消除（I001 拆行），残留 42** | 2026-08-18 副本干跑 |
| .gitignore | 第 8 行 `.loop/` 整目录忽略 | grep 核实 |

## 关键设计决策（HOLD 姿态）

| 决策 | 备选 | 理由 | 风险与缓解 |
|------|------|------|-----------|
| D1: `.loop/tests/e2e/*.json` **保留** | 全部删除 | `tests/test_e2e_smoke.py:22` 定义 `E2E_TASK_CARDS_SRC = PACKAGE_ROOT / ".loop" / "tests" / "e2e"` 将其作为 fixture 源；删除会破坏 e2e 测试 | 无（保留即零风险） |
| D2: 10 个 git-tracked .loop 文件**保留** | 删除进 git diff | 均为仓库资产（`config.json`、`examples/task_card.json`、`tasks/README.md`、`templates/*.txt` 7 个） | 无 |
| D3: RUF100 的 `# noqa: F401` 删除**交给 ruff --fix** | 手动逐条删 | ruff 判定 noqa unused 即证明 F401 已因 `__all__` re-export 检测不再触发，fix 是精确删除；手动反而易错 | B1 后立即全量 ruff check 复核，若出现 F401/F403 复活（不应发生）则 revert 该 commit |
| D4: F841 修复采用"副作用感知"双规则 | 统一删整行 | `_core.py:12534` 的 `resolved_paths = _resolve_paths(paths)` 调用可能有内部副作用，保守保留调用删赋值 | 见 T3.1 |
| D5: B2 拆 8 个子 task（每 task ≤3 文件） | 合并大 commit | 满足"每 task ≤3 文件"粒度规则 + 失败可单独 revert | 每子批后全量 ruff + pytest |
| D6: A 批纯磁盘删除**无 git diff → 无 commit** | 空 commit | 物理上无可提交内容；验收改为"磁盘清单核对 + git status 保持 clean" | 无 |
| D7: 全流程**串行执行**（不并行） | 并行 wave | pytest 有模块全局状态（`test_orchestrator.py` 的 autouse fixture 快照/恢复全局），并行跑会互相污染；且逐批 commit 需顺序 | 串行增加墙钟时间，但本任务 12 个 task 均小 |

## 执行计划

### Phase 1 — A 批：环境残留清理（磁盘操作，无 git diff）

#### Task 1.1: 删除 .loop 瞬态残留（磁盘清理）

- **目标**：删除 #2675 执行期瞬态数据，保留仓库资产与 e2e fixture
- **依赖**：无
- **frontier**：是
- **执行者**：Task Executor
- **修改内容（modify_specs）**：

| action | file | target | description |
|--------|------|--------|-------------|
| delete-file | `.loop/.state.json.bak` | 整文件 | #2675 状态痕迹（266B，含 E2E-CHANGES-REQUIRED 痕迹） |
| delete-file | `.loop/events.jsonl` | 整文件 | 运行时事件流（510KB）；测试不依赖磁盘实体（test_pm_integration 用 tmp_path monkeypatch） |
| delete-dir | `.loop/archive/` | 整目录 | 含 `E2E-CHANGES-REQUIRED/r1_work_report.json`、`r1_state.json` |
| delete-dir | `.loop/context/` | 整目录 | `knowledge.sqlite3`（120KB 缓存）+ `pitfalls.md`（23 行，测试副产物 suggestion 列表，非手工资产） |
| delete-dir | `.loop/logs/` | 整目录 | 7 个 feed.jsonl 日志 |
| delete-dir | `.loop/handoff/` | 整目录 | 4 个 E2E handoff 目录（E2E-1PLUS1/E2E-CHANGES-REQUIRED/E2E-NOOP-SUCCESS/T-721） |
| delete-dir | `.loop/work_reports/` | 整目录 | lane_core.json、lane_main.json |
| delete-dir | `.loop/runs/` | 整目录 | 空目录 |
| delete-dir | `.loop/worktrees/` | 整目录 | 空目录 |
| delete-file | `.loop/lock` | 整文件 | 12B 锁文件；**删除前先执行 `pgrep -af "loop"` 确认无运行中的 loop 进程** |

- **修改边界**：
  - ⛔ **保留** `.loop/tests/e2e/*.json`（4 个 task_card.json，e2e fixture）
  - ⛔ **保留** 10 个 git-tracked 文件：`.loop/config.json`、`.loop/examples/task_card.json`、`.loop/tasks/README.md`、`.loop/templates/*.txt`（7 个）
  - ⛔ **保留** `.loop/examples/`、`.loop/tasks/`、`.loop/templates/`、`.loop/tests/` 目录本身
  - ⛔ 不得触碰 `.loop/` 之外的任何路径；不得修改任何 git-tracked 文件
- **质量检查方式**：
  - 检查项 1：删除清单逐条执行，`ls .loop/` 结果应仅含：`config.json`、`examples/`、`tasks/`、`templates/`、`tests/`
  - 检查项 2：`git status --short` 输出为空（删除项全在 .gitignore 覆盖下，无 git diff）
- **验收标准**：
  - ✅ `ls .loop/` 仅剩 5 项（config.json、examples、tasks、templates、tests），无 `.state.json.bak`、无 `events.jsonl`、无 `archive/`、`context/`、`logs/`、`handoff/`、`work_reports/`、`runs/`、`worktrees/`、`lock`
  - ✅ `git status --short` 为空（本 task 无 commit，验收以磁盘状态为准；此决策见 D6）
- **潜在风险**：若 ATR cron 正在运行，删除后可能重新生成 events.jsonl——删除前 pgrep 确认；若删除后重新出现，属运行时正常行为，不视为失败（在 T4.1 复查）
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

### Phase 2 — B1 批：机械 ruff --fix（62 项，1 commit）

#### Task 2.1: 执行 ruff --fix 修复 62 项（52 显式 fixable + 10 项 E501 顺带消除）

- **目标**：一次 `--fix` 修复 I001 16 + RUF100 20 + F401 7 + E401 3 + RUF022 3 + UP017 1 + SIM117 1 + F541 1 = 52 项显式 fixable；**外加 I001 import 重排顺带把 10 个子模块的超长 import 行拆为多行，消除其中 10 个 E501**（2026-08-18 /tmp 副本模拟实测：`Found 94 errors (52 fixed, 42 remaining)`）
- **依赖**：T1.1
- **frontier**：否（依赖 T1.1 完成，保持单变更源）
- **执行者**：Task Executor
- **修改内容（modify_specs）**：

| action | file | target | description |
|--------|------|--------|-------------|
| run-fix | 自动（预期 16 个文件） | 全部 fixable 项 | 执行 `uv run --group dev ruff check src/loop_kit tests --fix`；预期修改文件集合：src 11 个（`src/loop_kit/_core.py` + `config/dispatch/exceptions/file_bus/git_helpers/knowledge/paths/prompts/session/state.py` 10 个）+ tests 5 个（`tests/test_orchestrator.py`、`tests/test_pm_integration.py`、`tests/test_bout_to_gitr_coupling.py`、`tests/test_doc_pipeline_compat.py`、`tests/test_integration.py`） |

- **修改边界**：
  - ⛔ **禁止** `--unsafe-fixes` 参数（F841 的 unsafe fix 会删赋值，留给 B2 人工判定）
  - ⛔ **禁止** 手动修改任何文件——本 task 只允许 ruff 自动修复 + git commit
  - ⛔ RUF100 删除 noqa 后**不得**手工补充任何 `# noqa` 注释（若 ruff 报新错误，说明有意外，停下报告）
- **质量检查方式**：
  - 检查项 1：fix 后 `uv run --group dev ruff check src/loop_kit tests --output-format=concise` 输出应为 **42 errors**，且规则集合 ⊆ {E501, F841, RUF059, SIM105, E702}，分布 = E501 25（_core 11 + 子模块 `__all__` 10 + tests 4）+ F841 7 + RUF059 6 + SIM105 2 + E702 2
  - 检查项 2：`git diff --stat` 核对修改文件集合 ⊆ 预期 16 文件集合（**注意 edit 工具可能触发外部 format-on-save，diff 中若出现预期外文件/大范围格式漂移，先 `git checkout -- <意外文件>` 还原再排查**）
  - 检查项 3：`uv run --group dev pytest -q` 全量通过，结果为 615 passed / 0 failed（**执行前先跑一次确认基线 615**；B1 后必须仍为 615 passed，若 pytest 数变化需解释）
  - 检查项 4：`uv run python -c "from loop_kit.orchestrator import *"` exit 0（re-export 冒烟）
- **验收标准**：
  - ✅ ruff 残留 42 errors，全部属于 B2 规则集合
  - ✅ pytest 615 passed / 0 failed
  - ✅ import 冒烟 exit 0
  - ✅ 单独 commit，message：`fix(lint): B1 ruff --fix — 62 fixes (52 explicit + 10 E501 via I001 line-split)`
- **潜在风险**：RUF100 删除 noqa 后规则复活（低概率，见 D3）——若发生，`git revert` 本 commit 并上报 Plan Architect（mode=improve）
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

### Phase 3 — B2 批：手动语义修复（42 项，8 个子 task，各独立 commit）

> **B2 通用规则（所有 B2 task 适用）**：
> - 每个 task 第一步：重跑 `uv run --group dev ruff check <本task目标文件> --output-format=concise` **刷新实际行号**（B1 已改动行数；本文行号分两类：`src/loop_kit/_core.py` 与 `tests/test_orchestrator.py` 的行号经模拟确认 B1 后不变，可直接用；其余 tests 文件与 10 个子模块用下方"B1 后实测行号"，执行时仍以刷新报告为准）
> - **E501 修复双规则**：①超长行是表达式 → 括号包裹多行；②超长行含字符串字面量 → 拆为隐式拼接（`"a" "b"`）或括号内多字符串，**字符串内容必须逐字节不变（含空格）**；修复后确认行宽 ≤120
> - **F841 修复双规则**：①`var = <无副作用表达式>`（如 `state.get(...)`、`str(...)`）→ 删整行；②`var = <可能有副作用的函数调用>`（如 `_resolve_paths(...)`）→ **保留调用删赋值**，即改为表达式语句 `_resolve_paths(paths)`
> - **RUF059 修复规则**：解包未使用位置改 `_`（py3.11 允许同一表达式多个 `_`）；若变量名是 `paths`/`loop_dir` 等，直接替换该位置为 `_`，其余位置不动
> - **E702 修复规则**：`a = x; b = y` 拆为两行
> - **SIM105 修复规则**：`try:` → `with contextlib.suppress(<Exc>):`，删除 `except <Exc>:` 与 `pass:` 两行，**块体缩进保持不变**；若文件未 import contextlib，在 import 区添加 `import contextlib`
> - **禁止**：改动任何函数签名、字符串内容、控制流语义；禁止顺手重构

#### Task 3.1: B2a — `src/loop_kit/_core.py`（11 E501 + 3 F841 + 1 SIM105 = 15 项）

- **目标**：修复 _core.py 全部 B2 类残留
- **依赖**：T2.1
- **frontier**：是（B2a 完成后 B2b/B2c 可开工；但按 D7 串行）
- **执行者**：Task Executor
- **修改内容（modify_specs）**：

| action | file | target | description |
|--------|------|--------|-------------|
| edit | `src/loop_kit/_core.py` | 11 处 E501（基线行号 1113/3836/6530/7297/7471/8394/9254/10785/12301/13175/13201） | 按 E501 双规则换行；锚点内容：L1113 `timeout_sec = int(verification.get(...)`、L3836 `message=f"Knowledge auto-prune: ...`、L6530 `_STATE_CMP_KEYS = (...`、L7297 `overlap_paths = [...] if isinstance(...`、L7471 `lane_record["status"] = "applied_after_defer"...`、L8394 `if any(kw in line.lower() for kw in (...)`、L9254 `def cmd_status(*, tree: bool = False, ...`、L10785 `def _update_knowledge_on_approval(...`、L12301 `f"got task_id=... base_sha=... run_id=..."`、L13175 `run_p.add_argument("--clean-stale", ...`、L13201 `cmd_status(tree=bool(args.tree), ...` |
| edit | `src/loop_kit/_core.py` | F841 @`outcome = state.get("outcome")`（L12308，B1 后不变） | `dict.get` 无副作用 → 删整行 |
| edit | `src/loop_kit/_core.py` | F841 @`resolved_paths = _resolve_paths(paths)`（L12534，B1 后不变） | 保守规则②：改为表达式语句 `_resolve_paths(paths)` |
| edit | `src/loop_kit/_core.py` | F841 @`last_decision = "changes_required"`（L12535，B1 后不变） | 纯字面量 → 删整行 |
| edit | `src/loop_kit/_core.py` | SIM105 @`try:` / `except OSError: pass`（L8984-8999，B1 后不变） | 改为 `with contextlib.suppress(OSError):` 包裹 `_write_round_summary(...)` 调用；`_core.py` L15 已 import contextlib，无需新增 |

- **修改边界**：只允许上述 15 处修改；不得触碰 `_core.py` 其他任何行（含相邻的 `_dispatch_post_round` 逻辑）
- **质量检查方式**：
  - 检查项 1：`git diff src/loop_kit/_core.py` 人工核对 hunk 数 == 15 处修改点，无意外 hunk
  - 检查项 2：`uv run --group dev ruff check src/loop_kit/_core.py` → 0 errors
  - 检查项 3：`uv run --group dev pytest -q` → 615 passed / 0 failed
- **验收标准**：
  - ✅ 全量 ruff 残留 = 27 errors（42 − 15）
  - ✅ pytest 615 passed / 0 failed
  - ✅ commit：`fix(lint): B2a manual fixes in _core.py — 11 E501 + 3 F841 + 1 SIM105`
- **潜在风险**：L12534 若 `_resolve_paths` 实际无副作用，保留调用会产生一个无意义的表达式语句——可接受（lint 合规且行为不变）；L12301 与 L12308 相邻，注意 diff 时不混入
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

#### Task 3.2a: B2b — `exceptions.py` + `paths.py` + `state.py`（3 处 `__all__` E501）

- **依赖**：T3.1
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**：

| action | file | target | description |
|--------|------|--------|-------------|
| edit | `src/loop_kit/exceptions.py` | E501 @`__all__ = [...]`（B1 后实测 L19，163 字符） | 多行列表，每行一个字符串 |
| edit | `src/loop_kit/paths.py` | E501 @`__all__ = [...]`（B1 后实测 L154，3972 字符） | 多行列表，每行一个字符串 |
| edit | `src/loop_kit/state.py` | E501 @`__all__ = [...]`（B1 后实测 L58，1254 字符） | 多行列表，每行一个字符串 |

> 注：B1 的 I001 fix 已把各子模块的 import 行（原 L8）拆为多行，故 B2b 每文件只剩 `__all__` 1 处。
- **修改边界**：符号集合与顺序**必须逐字节不变**（B1 已排序 `__all__`，此处仅换行，不得增删符号）
- **质量检查方式**：`git diff` 逐 hunk 核对（每文件 1 hunk）；`uv run --group dev ruff check` 全量残留 = 24；pytest 615/0
- **验收标准**：
  - ✅ ruff 全量残留 24 errors（27 − 3）
  - ✅ `uv run python -c "from loop_kit.orchestrator import *"` exit 0
  - ✅ commit：`fix(lint): B2b-1 wrap __all__ lines — exceptions, paths, state`
- **潜在风险**：换行后若符号被意外删改，import 冒烟 + `git diff` 逐行核对可捕获
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

#### Task 3.2b: B2b — `file_bus.py` + `dispatch.py` + `session.py`（3 处 `__all__` E501）

- **依赖**：T3.2a
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**：同 T3.2a 模式，文件与 B1 后实测行号：`src/loop_kit/file_bus.py` L34（497 字符）、`src/loop_kit/dispatch.py` L31（675 字符）、`src/loop_kit/session.py` L22（283 字符），各 1 处 `__all__`
- **修改边界**：同 T3.2a
- **质量检查方式**：同 T3.2a；ruff 全量残留 = 21；pytest 615/0
- **验收标准**：
  - ✅ ruff 全量残留 21 errors（24 − 3）
  - ✅ commit：`fix(lint): B2b-2 wrap __all__ lines — file_bus, dispatch, session`
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

#### Task 3.2c: B2b — `config.py` + `prompts.py` + `knowledge.py`（3 处 `__all__` E501）

- **依赖**：T3.2b
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**：同 T3.2a 模式，文件与 B1 后实测行号：`src/loop_kit/config.py` L24（347 字符）、`src/loop_kit/prompts.py` L26（421 字符）、`src/loop_kit/knowledge.py` L99（2468 字符），各 1 处 `__all__`
- **修改边界**：同 T3.2a
- **质量检查方式**：同 T3.2a；ruff 全量残留 = 18；pytest 615/0
- **验收标准**：
  - ✅ ruff 全量残留 18 errors（21 − 3）
  - ✅ commit：`fix(lint): B2b-3 wrap __all__ lines — config, prompts, knowledge`
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

#### Task 3.2d: B2b — `git_helpers.py`（1 处 `__all__` E501）

- **依赖**：T3.2c
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**：同 T3.2a 模式，文件为 `src/loop_kit/git_helpers.py`，B1 后实测 L60（1284 字符），1 处 `__all__`
- **质量检查方式**：ruff 全量残留 = 17；pytest 615/0
- **验收标准**：
  - ✅ ruff 全量残留 17 errors（18 − 1）
  - ✅ commit：`fix(lint): B2b-4 wrap __all__ lines — git_helpers`
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

#### Task 3.3a: B2c — `tests/test_pm_integration.py`（3 E501 + 2 E702 + 2 F841 + 1 连锁 import = 8 项）

- **依赖**：T3.2d
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**（行号均为 B1 后实测值）：

| action | file | target | description |
|--------|------|--------|-------------|
| edit | `tests/test_pm_integration.py` | E501 @B1后 L223/225/228 | 按 E501 双规则换行（内容锚：以刷新后的 ruff 报告行号为准） |
| edit | `tests/test_pm_integration.py` | E702 @`ld = tmp_path / ".loop"; ld.mkdir(parents=True)`（B1后 L274、L298，两处同模式） | 拆为两行 |
| edit | `tests/test_pm_integration.py` | F841 @`now = datetime.now(tz=UTC)`（B1后 L216；B1 的 UP017 已把 import 改为 `from datetime import UTC`） | 纯调用无副作用 → 删整行 |
| edit | `tests/test_pm_integration.py` | F841 @`orig = orchestrator._normalize_pattern_entry`（B1后 L220） | 属性访问无副作用 → 删整行 |
| edit | `tests/test_pm_integration.py` | **连锁**：删除 L216 后模块级 `from datetime import UTC`（B1后 L4）唯一引用消失 → 删除 L4 整行；注意 L214 函数内局部 `from datetime import datetime` 保留不动 | 连锁修复，必须执行；完成后 `ruff check tests/test_pm_integration.py` → 0 errors 作最终校验 |

- **修改边界**：不得改动任何测试断言与测试逻辑；`monkeypatch.setattr` 语句不动
- **质量检查方式**：`git diff tests/test_pm_integration.py` 逐 hunk 核对；ruff 全量残留 = 10；pytest 615/0
- **验收标准**：
  - ✅ ruff 全量残留 10 errors（17 − 7）
  - ✅ pytest 615 passed / 0 failed
  - ✅ commit：`fix(lint): B2c-1 test_pm_integration — E501/E702/F841 + UTC import chain`
- **潜在风险**：L216 删除后若 `datetime` 也被连锁判 unused（文件中 L214 局部 import 存在，预期不会）——若 ruff 报新 F401 则按连锁规则处理
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

#### Task 3.3b: B2c — `test_doc_pipeline_compat.py`（3 RUF059）+ `test_integration.py`（1 E501 + 2 F841 + 2 RUF059）

- **依赖**：T3.3a
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**（行号均为 B1 后实测值）：

| action | file | target | description |
|--------|------|--------|-------------|
| edit | `tests/test_doc_pipeline_compat.py` | RUF059 @B1后 L41（`paths` 解包位置）、L76 两处（`loop_dir` 与 `paths` 解包位置） | 未使用解包位置改 `_` |
| edit | `tests/test_integration.py` | E501 @B1后 L41 | E501 双规则换行 |
| edit | `tests/test_integration.py` | F841 @`task_path = str(loop_dir / "tasks" / "T-INT-1_task_card.json")`（B1后 L38） | Path 运算无副作用 → 删整行 |
| edit | `tests/test_integration.py` | F841 @`paths = orchestrator._resolve_paths()`（B1后 L314） | 保守规则②：保留调用删赋值 → `orchestrator._resolve_paths()` |
| edit | `tests/test_integration.py` | RUF059 @B1后 L278（`stale`）、L290（`diag`） | 未使用解包位置改 `_` |

- **修改边界**：不得改动任何测试断言
- **质量检查方式**：ruff 全量残留 = 2；pytest 615/0
- **验收标准**：
  - ✅ ruff 全量残留 2 errors（10 − 8）
  - ✅ pytest 615 passed / 0 failed
  - ✅ commit：`fix(lint): B2c-2 doc_pipeline_compat + integration — RUF059/E501/F841`
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

#### Task 3.3c: B2c — `tests/test_orchestrator.py`（1 RUF059 + 1 SIM105）

- **依赖**：T3.3b
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**（行号经模拟确认 B1 后不变，仍以刷新报告为准）：

| action | file | target | description |
|--------|------|--------|-------------|
| edit | `tests/test_orchestrator.py` | RUF059 @L12947（`patterns_path` 解包位置） | 改 `_` |
| edit | `tests/test_orchestrator.py` | SIM105 @L13022（`try:`/`except Exception: pass`） | 改 `with contextlib.suppress(Exception):`；该文件无 contextlib import → import 区添加 `import contextlib` |

- **修改边界**：不得改动任何测试断言
- **质量检查方式**：`uv run --group dev ruff check src/loop_kit tests` → **0 errors**；pytest 615/0
- **验收标准**：
  - ✅ ruff 全量残留 0 errors（2 − 2）
  - ✅ pytest 615 passed / 0 failed
  - ✅ commit：`fix(lint): B2c-3 test_orchestrator — RUF059 + SIM105 → 0 lint errors`
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：[如有] 具体字段名与歧义描述

### Phase 4 — C：CI 门禁验证

#### Task 4.1: 全量验证 + push 触发 CI 门禁

- **依赖**：T3.3c
- **frontier**：否
- **执行者**：Task Executor
- **修改内容（modify_specs）**：无代码修改；执行验证与收尾：

| action | file | target | description |
|--------|------|--------|-------------|
| verify | — | 本地等价 CI 命令 | 依次执行：① `uv run --group dev ruff check src/loop_kit tests`（exit 0）；② `uv run python -m py_compile src/loop_kit/orchestrator.py`（exit 0）；③ `uv run python -c "from loop_kit.orchestrator import *"`（exit 0）；④ `uv run python -m loop_kit --help`（exit 0）；⑤ `uv run --group dev pytest -q`（615 passed / 0 failed） |
| verify | — | .loop 残留复查 | `ls .loop/` 确认无瞬态数据复活（若 pytest/CLI smoke 重新生成 events.jsonl 等，评估来源：若为 `python -m loop_kit --help` 等本地命令所致，删除并复验；若为 ATR cron 所致，记录但不阻塞） |
| push | — | master | `git push origin master` 触发 loop-ci.yml；**若用户明确指示不 push，则跳过本步并标注门禁以本地等价验证为准** |

- **修改边界**：不得新增任何代码修改；若验证失败，禁止绕过（直接 `git revert` 对应批次或上报 improve）
- **质量检查方式**：本地 5 命令逐一记录 exit code；push 后轮询 CI run 状态（`gh run list` / Actions 页面），确认 `Run Ruff` step 绿色
- **验收标准**：
  - ✅ 本地 5 命令全部 exit 0 / 预期输出
  - ✅ CI ruff 门禁绿（若已 push）；或本地等价验证通过 + 未 push 原因明确记录
  - ✅ `git status` clean，`git log --oneline -10` 含 8 个 lint 相关 commit（B1 + B2a + B2b×4 + B2c×3）
- **潜在风险**：CI 环境 ruff 版本与本地不一致导致 CI 红——本地与 CI 均经 `uv run --group dev` 走同一锁文件，风险低；若 CI 红且本地绿，收集 CI 日志后上报
- **预留歧义标注**：
  - [ ] 无歧义：所有字段可直接执行，无需额外推断
  - 歧义点：`push` 是否需要用户确认——默认执行 push（历史修复均为直接 commit+push master，见 011d55e/ff32f17），若会话上下文另有指示则跳过

## Execution Wave（串行执行，D7 已说明不并行原因）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|-----------|
| W1 | T1.1 | T1.1 | — |
| W2 | T2.1 | T2.1 | W1 |
| W3 | T3.1 | T3.1 | W2 |
| W4 | T3.2a→b→c→d | 无（串行链） | W3 起逐个 |
| W5 | T3.3a→b→c | 无（串行链） | W4 |
| W6 | T4.1 | T4.1 | W5 |

> 串行理由：①每 task 后跑全量 pytest，`test_orchestrator.py` 的 autouse fixture 快照/恢复模块全局，并行 pytest 进程互相污染；②逐批独立 commit 需顺序避免 index 冲突；③B2 锚点行号随前批漂移，需前一 commit 落盘后刷新。

## Post-Execution Verification

### Automated Verification（Task Executor 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量 lint 归零 | `uv run --group dev ruff check src/loop_kit tests` | exit 0，0 errors |
| V2 | 全量测试 | `uv run --group dev pytest -q` | 615 passed，0 failed |
| V3 | 编译检查（CI 同款） | `uv run python -m py_compile src/loop_kit/orchestrator.py` | exit 0 |
| V4 | import 冒烟（CI 同款） | `uv run python -c "from loop_kit.orchestrator import *"` | exit 0 |
| V5 | CLI smoke（CI 同款） | `uv run python -m loop_kit --help` | exit 0 |

### Manual Verification（三级分类）

### Deferred (needs restart / deployment)
- [ ] D1: push master 后 CI 门禁变绿（需 push 触发，属部署类检查；若未 push 则跳过并记录）

### Probe (best-effort, run if available)
- [ ] P1: `git log --oneline -10` 含 8 个 lint commit 且顺序为 B1→B2a→B2b×4→B2c×3

### Manual（真正需要人工判断）
- [ ] M1: 人工抽查 `git show <B2b commit>` 中一个 `__all__` 换行 diff，确认符号集合与排序未变
- [ ] M2: 人工确认 `.loop/` 清理后本地 loop 工具链（`python -m loop_kit --help`、ATR cron 状态）无异常

## 风险与回滚

| # | 风险 | 概率 | 影响 | 缓解/回滚 |
|---|------|------|------|----------|
| R1 | edit 工具触发外部 format-on-save，diff 混入意外格式漂移 | 中 | 中 | 每 task 提交前 `git diff --stat` 核对文件集合；意外文件 `git checkout -- <file>` 还原后重做 |
| R2 | RUF100 noqa 删除后 F401/F403 复活 | 低 | 中 | B1 后立即全量 ruff check；复活则 `git revert` B1 commit 并上报 improve |
| R3 | B2a L12534 `_resolve_paths` 副作用误判 | 低 | 低 | 保守规则保留调用删赋值，行为恒等价；pytest 全量回归兜底 |
| R4 | B2 换行误改字符串内容 | 低 | 高（语义破坏） | E501 双规则明确"逐字节不变"；`git diff` 逐 hunk 核对；pytest 615 兜底 |
| R5 | 行号锚点漂移导致改错位置 | 中 | 中 | 每 B2 task 第一步刷新 ruff 报告行号 + 内容锚双定位；git diff 核对 hunk 数 |
| R6 | 测试数基线漂移（非 615） | 低 | 中 | T2.1 先跑基线确认；若非 615 且与 lint 无关，停止并上报 |
| R7 | ATR cron 运行中删除 lock/events.jsonl 引发竞态 | 低 | 低 | 删除前 pgrep；删除后 T4.1 复查 |
| 回滚总则 | 每批独立 commit | — | — | 任一批失败：`git revert <该批 sha>` 恢复该批；A 批无 git 变更，磁盘删除不可回滚但全部为可再生的运行时数据 |

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性 | 2 | 2 | 0 |
| R1.5 | 外部引用事实核查 | 3 | 3 | 0 |
| R2 | 可执行性（含脚本干跑） | 4 | 4 | 0 |
| R2.8 | LLM 可执行性审查 | 2 | 2 | 0 |
| R3 | 风险与边缘（含跨轮一致性） | 2 | 2 | 0 |
| **终止** | **T3 — issue 全部清零** | | | **0** |

审查发现明细：
- R1-1：原 A 批把 `.loop/tests/e2e/` 列入删除 → 实测 `tests/test_e2e_smoke.py:22` 引用其为 fixture → 移入保留清单（D1）
- R1-2：A 批无 git diff 导致"每批独立 commit"落空 → 明确 D6（无 commit，磁盘验收替代）
- R1.5-1：F401 误判风险 → 实测确认 7 个 F401 全在 tests，src 的 20 个 RUF100 均为 `__all__` re-export 模式下 noqa F401 失效，删除安全（D3）
- R1.5-2：`context/pitfalls.md` 疑似手工资产 → 读内容确认为测试副产物（23 行 suggestion 列表），可删
- R1.5-3：SIM105 两处 contextlib import 状态 → 实测 `_core.py:15` 已 import；`test_orchestrator.py` 未 import → T3.3c 显式补 import
- R2-1：E501 无自动修复，需区分表达式/字符串两类换行 → 补充 B2 通用规则 E501 双规则
- R2-2：B1 UP017 与 B2 F841（L218）同处一行，且删行后 `timezone` import 连锁 unused → T3.3a 显式写连锁修复步骤
- R2-3：B1 修改 16 个文件会漂移 B2 行号 → B2 通用规则"每 task 先刷新 ruff 报告行号 + 内容锚双定位"
- R2-4：**B1 模拟实测推翻 52 残留假设** → /tmp 副本干跑发现 I001 拆行顺带消除 10 个 import 行 E501，实际残留 42（E501 25 而非 35）；B2b 每文件目标从 2 处降为 1 处 `__all__`，全链计数改为 42→27→24→21→18→17→10→2→0，tests 与子模块行号改用 B1 后实测值，T3.3a 连锁改为删除 `from datetime import UTC`（ruff 0.15 UP017 行为）
- R2.8-1：T3.1 的 11 处 E501 仅有行号无内容锚 → 补全全部 11 处内容锚（已实测抓取）
- R2.8-2：push 是否需要用户确认不明确 → T4.1 写死"默认 push，若会话另有指示则跳过并记录"
- R3-1：pytest 并行污染风险 → D7 全串行并给出理由
- R3-2：`python -m loop_kit --help` 可能在 .loop 写数据 → T4.1 复查步骤覆盖

## 后续建议（Out of Scope，不执行）

1. 将 `.loop/tests/e2e/*.json`（4 个 fixture）纳入 git-track 化，消除"新 clone 缺 e2e fixture"隐患
2. `.loop/` 运行时残留的自动清理机制（loop 启动时自清理 stale 数据，已有 `--clean-stale` 参数可评估扩展）
3. `ruff format` 全仓引入（当前无 format 配置，B 批仅动 lint 不碰 format）


## CT 审阅合入（2026-08-18，critical-thinking 裁定）

### 执行前必须修订
1. **T3.3a 连锁补第 3 环**：删除 L216（`now = datetime.now(tz=UTC)`）与 L4（`from datetime import UTC`）后，L214 局部 `from datetime import datetime` 的唯一引用消失 → ruff 新报 F401。modify_specs 修正为三环连锁：L216 → L4 → L214 一并删除（计数不变 17−7=10）。
2. **计划文件处置**：仓库惯例 plans 历来被 commit（git log 证实）；"git status clean"验收与计划文件未跟踪矛盾。处置：计划文件随 B1 批 commit 一并提交（或专用 housekeeping commit），验收标准保持"clean"。

### 可选改进（不阻塞）
3. F841 两处（_core.py:12534、test_integration.py:314）改删整行——_resolve_paths（_core.py:667-672）已实证为纯函数（无 I/O、无全局变更），"可能有副作用"前提证伪。
4. T1.1 进程检查不用 `pgrep -af "loop"`（实测误报 chromium --proxy-bypass-list 与 tmux 会话）——改用 lock 文件权威 PID：`ps -p $(cut -d: -f2 .loop/lock)`。

### 执行时注意
5. CI 红时 revert 非有效回退（基线 104 errors 本身也是红的）——唯一路径 fix-forward + 上报；计划已隐含，执行时写死此决策。
6. push 范围 = 26 个既有未推送 commit + 8 个 lint commit（fast-forward，实测无冲突）。
