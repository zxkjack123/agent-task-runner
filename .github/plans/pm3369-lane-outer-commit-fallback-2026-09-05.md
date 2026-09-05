---
plan_topic: pm3369-lane-outer-commit-fallback
task_id: "3369"
workspace: /home/gw/opt/agent-task-runner
priority: medium
scope_mode: HOLD
generated_at: 2026-09-05
git_commit_at_generation: a370ec1
linked_taskfit: verdict=valid HIGH（锚点已实测；3 项待验证已由 PA 规划期消解，见「消解结论」节）
revision: 1
status: ready
---

# PM #3369 执行计划：lane 收敛适配 — worker 沙箱内无法 commit 时外层代为 commit

## 背景与目标

- **问题**：#3364 复验暴露 dsh 集成缺口——dsh sandbox 忠实执行 workspace-write 语义，正确拒绝 worker 写主仓共享 `.git`（lane worktree 的 commit 元数据落在主仓 `.git`，超出 sandbox 边界）→ worker 完成了全部开发动作（写文件、跑测试）但无法 commit → `head_sha == base_sha` → #2911 证据门控正确判定 no-change → blocked。
- **用户裁决**：路径 A——worker self-commit 失败时，外层（orchestrator，无沙箱）代为 commit。
- **目标**：在 loop_kit 中新增「外层代为 commit」回退机制：当 worker 声明了变更但未产生 commit 时，外层对 worker 作用域内的实际 dirty 文件执行 commit，并用新 head_sha 回填，使轮次正常收敛。
- **硬约束**：
  1. 只改 agent-task-runner 仓（`/home/gw/opt/agent-task-runner`），不触碰任何外部仓库；
  2. 不新增 CLI 参数（开关走 env）；
  3. 不削弱 lane 隔离；
  4. 保持 #2911 evidence gating 语义（真 no-change 仍 blocked）；
  5. 保持 #3155 repo 锁 / #3263 watchdog 行为；
  6. 全量 748 passed 基线不回归；
  7. 不卷入 untracked 遗留（5 个 plan 文件 + `data/`）。

## 非目标（Out of Scope）

- 不修改 worker / reviewer prompt 模板（files_changed 声明规范为 follow-up，建议记入 PM 备注）；
- 不修改 `_dispatch_single_round_phase` 注册表结构（:14542）；
- 不改动 `_cherry_pick_lane_reports` / `_merge_lane_work_reports` 合并机制本身；
- lane_dispatch_enabled 模式下不新增 13081 合并门后置处理（per-lane 回退在 merge 之前完成，见 D4）；
- 不为 `--single-round` 直跑模式补锁（见 V1 消解结论）；
- 不提交 `.github/plans/pm3369-*.md` 本计划文件、其它 5 个遗留 plan 文件、`data/`。

## 3 项待验证消解结论（PA 规划期已消解；T1 执行时复核锚点）

### V1：repo 锁所有权链 → 消解：正常流程锁由父进程持有，回退 commit 落在子进程内是被覆盖的

实测事实（本会话读取）：
- `cmd_run`（:13841）在 `not single_round` 时才获取 repo 锁（:13865-13875 `repo_lock = _acquire_repo_lock(...)`），锁顺序 repo → loop-dir（:13859）。
- :13860-13861 注释明确：**single-round 子进程由已持有两把锁的父循环 spawn，跳过获取以避免自死锁**。
- 正常 `loop run` 流：父 `cmd_run` 持有 repo flock → `_main_loop`（:13792）→ `_run_multi_round_via_subprocess`（:13338）→ 每轮 `Popen(python -m loop_kit run --single-round --round N ...)`（:13572-13594，`_single_round_subprocess_cmd` :11386）→ 子进程 `cmd_run(single_round=True)` 跳过锁 → `_run_single_round`（:12124）。
- `_acquire_repo_lock`（:1515）为 `/tmp/loop-kit-repo-locks/<sha256(root)>.lock` 上的 flock，sole authority，绝不 unlink。

**结论**：外层 commit 落点 `_run_single_round` 内（serial 站点 + lane 站点）**执行于 single-round 子进程**。正常流程下父进程全程持有 repo 锁 → 回退 commit 处于父进程临界区内，锁语义（对其它并发 loop run 的互斥）完整保留。直接 `--single-round` 直跑（调试/人工路径）时无人持锁——与现有 worker 自 commit 在该模式下同样无锁的语义一致，不构成新的绕过。**禁止在子进程内再次获取 repo 锁**（自死锁）；无需改任何锁代码，但需测试 + 文档固化该语义（T2 测试 + T5 文档）。

### V2：merged lane work_report 是否携带 lane_id → 不携带（:8164-8172 实测）

`_merge_lane_work_reports`（:8090-8193）的 merged 结果只含 `task_id/run_id/head_sha/round/lane_metrics/duration_ms/cost_cents`（及条件字段 files_changed/tests/notes/merge_provenance），**无顶层 `lane_id`**；lane 归属只存在于 per-lane `lane_metrics`。`work["lane_id"]` 仅 serial enrich 路径（:13024-13037）写入 `_SERIAL_LANE_ID`。

**结论**：13081 合并门处无法从 merged report 反推 per-lane owner_paths → **lane 模式的回退必须插入 merge 之前的 per-lane 位置**（`_dispatch_lane` 内，lane.owner_paths 与 handle.path 直接可见），而非 13081 门。

### V3：worktree 作用域 git 调用 helper 形态 → `_git_at(cwd: Path, *args)` = `git -C <cwd>`（:7536-7550 实测）

`_git_at` 是既有 worktree 作用域 git 调用形态；`_create_lane_worktree`（:7888）即「`_git("worktree","add",...)`（主仓）＋ `_git_at(lane_path, "checkout", "-B", ...)`（worktree）」组合。

**结论**：外层 commit 统一走 `_git_at(worktree, "add", "--", *paths)` → `_git_at(worktree, "commit", "-m", msg)` → `_git_at(worktree, "rev-parse", "HEAD")`。不新增 git 调用方式。

## 关键设计决策

- **D1 — commit 执行位置**：全部落点在 `_run_single_round` 内（即 single-round 子进程）：① lane 模式在 `_dispatch_lane` 内、`lane_work = cast(WorkReport, artifact)`（:12433）之后、`_enrich_work_report_runtime_fields`（:12435）之前（per-lane，merge 前）；② serial 模式在 `if head_sha == base_sha:`（:13081）判定之前、`resolve_git_refs` 块（:13055-13080）之后。两个站点共享同一个核心 helper `_try_outer_commit_fallback`。锁语义见 V1。
- **D2 — 触发判据形态**（全部满足才 commit，任一不满足 → `None` → 走原路径，原 noop 分支一字不改）：
  1. env 逃生阀开启（`LOOP_OUTER_COMMIT_FALLBACK != "0"`，默认开）；
  2. whitelist 非空（lane 模式 = lane.owner_paths；serial 模式 = lanes owner_paths 并集，无 lanes 则 `in_scope`，均无则禁触发）；
  3. files_changed 非空；
  4. files_changed ⊆ whitelist（用 `_owner_paths_overlap` 前缀语义）；
  5. in-scope dirty（含 untracked，worktree 作用域实测 `git -C <wt> status --porcelain`）非空；
  6. in-scope dirty ⊆ files_changed（dirty 实测比对 = 唯一防伪造手段）；
  7. 无 out-of-scope **tracked** dirty（越界阻断）；out-of-scope **untracked** 容忍（本仓遗留 5 plan 文件 + `data/` 不误伤）。
  commit 集合 = in-scope dirty 精确集合（`git add -- <explicit paths>`，绝不 `git add -A`）。
- **D3 — 开关形态**：环境变量 `LOOP_OUTER_COMMIT_FALLBACK`，helper 内 `os.getenv` 直读（默认 "1"，"0" 关闭）。无新 CLI 参数、无 RunConfig schema 变更；Popen 默认继承 env → 父进程设置的开关自动穿透 single-round 子进程。
- **D4 — 双调用点**：lane 站点（修复 #3364 主路径：per-lane commit 后 merge 机制 `_cherry_pick_lane_reports` :8386-8389 的 "noop" 分支自然变为 "applied"）+ serial 站点（统一语义：ATR `max_parallel_workers=1` 或无 lanes 场景）。serial 站点条件 `not lane_dispatch_enabled`，lane 模式 merged 门不重复处理。
- **D5 — head_sha 回填**：仿 :13079-13080 resolve 回写模式——`work["head_sha"] = new_head` + `_atomic_write_json(work_report_path, work)`（lane 站点回写 `lane_local_report`）。回填后 :13081 判定自然为 False，落入既有 diff → reviewer 流程，reviewer 审查的正是外层 commit。
- **D6 — 语义变化文档化**：worker「故意不 commit 仅声明 files_changed」的行为从 blocked 变为自动 commit——该语义变化写入 helper docstring + 本计划，不动 CHANGELOG（commit scope 限制）。

## 执行计划

> 通用纪律（每任务适用）：
> - 每 Phase 首步「基线漂移重检」：`git rev-parse HEAD` + `git status --porcelain` 实测；若与下方锚点漂移（行号移动 / 目标文件被改），先重定位锚点再动手。
> - 每任务独立 commit，message 格式 `<type>: <描述> (#3369)`（repo 惯例，见 git log）；**只 stage `src/loop_kit/_core.py` 与 `tests/test_outer_commit_fallback.py`，绝不 `git add -A`**；commit 前 `git diff --cached --stat` 确认只有声明文件。
> - 不触碰 untracked 遗留（`.github/plans/pm*.md` × 5 + `data/` + `.loop/` 运行时产物）。

### Phase 0: 基线漂移重检 + 消解复核（T1）

#### Task 1.1: 读代码复核 3 项消解结论与锚点
- **目标**：复核本计划「消解结论」节的 3 项结论对当前 HEAD 仍成立；记录实际行号锚点；确认测试构造模式。
- **依赖**：无
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**：无代码修改。只读验证：
  - ① 锁链：read `_core.py` 13841-13930（`cmd_run` 锁获取 + single_round 跳过注释 13860-13861）与 13572-13594（Popen spawn）、`_acquire_repo_lock` :1515-1534；确认「父进程持锁、子进程跳过、禁止子进程再获取」结论。
  - ② merged lane_id：read `_core.py` 8090-8193（`_merge_lane_work_reports` 返回值无顶层 lane_id）。
  - ③ git helper：read `_core.py` 7536-7555（`_git_at` = `git -C`）。
  - ④ 补充复核（PA 新增，供 T2/T4 使用）：`_parse_porcelain_path` :8579-8585、`_owner_paths_overlap` :8752-8757、`_SERIAL_LANE_ID` :422、`_atomic_write_json` :7283、`WorkReport.files_changed` :130、`_task_lane_ids` :7520-7533。
  - ⑤ 测试构造模式复核：read `tests/test_orchestrator.py` 中 tmp_path + `_configure_loop_paths` 用法与 `tests/conftest.py` autouse 隔离 fixture，确认新测试文件的 paths 构造方式（用显式 `LoopPaths`/`_configure_loop_paths(tmp_path)` + 依赖 conftest 自动恢复）。
- **修改边界**：不写任何代码。
- **质量检查方式**：`grep -n` 逐项命中锚点；结论与代码一致。
- **验收标准**：
  - ✅ 3 项结论 + 5 个补充锚点全部在当前 HEAD 实测确认（grep 命中，行号记录到本任务 commit message 或执行日志）
  - ✅ `git status --porcelain` 仅见已知 untracked 遗留（5 plan + `data/`），无意外改动
  - ✅ 输出消解复核记录（若锚点漂移，先更新本计划对应行号再进入 T2）
- **潜在风险**：行号漂移导致后续任务锚点失效 → 已用 grep 语义锚（函数名/注释串）而非裸行号。
- **预留歧义标注**：
  - [ ] 无歧义

### Phase 1: 核心 helper + 单元测试（T2）

#### Task 2.1: 外层 commit 回退 helper 族（实现 + 单元测试，同任务提交）
- **目标**：新增 4 个模块级 helper（纯函数、可独立测试），暂不接任何调用点。
- **依赖**：T1.1
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**：`src/loop_kit/_core.py`（唯一文件）：
  1. 在 `_task_lane_ids`（:7520-7533）之后新增 `_serial_outer_commit_whitelist(task_card: TaskCard) -> list[str]`：`lanes` 为 list → 收集各 lane `owner_paths` 并集；否则 `in_scope` 为 list → 其 str 元素；否则 `[]`。
  2. 在 `_dirty_tracked_paths`（:8588-8604）之后新增 3 个函数：
     - `_outer_commit_fallback_enabled() -> bool`：`os.getenv("LOOP_OUTER_COMMIT_FALLBACK", "1").strip() != "0"`（默认开；Popen 继承 env 自动穿透子进程）。
     - `_worktree_dirty_split(worktree: Path, whitelist: list[str]) -> tuple[list[str], list[str]]`：单次 `_git_at(worktree, "status", "--porcelain")`；逐行 `_parse_porcelain_path(raw[3:])`；跳过空路径与 `.loop/` 前缀；`any(_owner_paths_overlap(p, w) for w in whitelist)` → in_scope，否则 `xy != "??"` → out_tracked；返回 `(sorted(set(in)), sorted(set(out)))`。**untracked out-of-scope 静默忽略**（遗留容忍）；**tracked out-of-scope 上报**（越界阻断）。
     - `_try_outer_commit_fallback(*, worktree, whitelist, files_changed, task_id, round_num, lane_id, paths=None) -> str | None`，严格按 D2 判据：
       1. `not _outer_commit_fallback_enabled()` → None；2. `not whitelist` → None；3. `not _is_git_repo_root(worktree)` → None；4. fc 归一化后为空 → None；5. `not all(any(_owner_paths_overlap(p, w) for w in whitelist) for p in fc)` → None（fc ⊆ owner_paths）；6. `_worktree_dirty_split` → `dirty_in` 为空 → None；7. `not set(dirty_in) <= set(fc)` → None（dirty ⊆ fc）；8. `out_tracked` 非空 → None；9. 否则 commit：msg = `f"[loop] task {task_id} round {round_num} lane {lane_id}: outer commit fallback (worker could not commit) [outer-commit]"`；`_git_at(worktree, "add", "--", *sorted(dirty_in))` → `_git_at(worktree, "commit", "-m", msg)` → 返回 `_git_at(worktree, "rev-parse", "HEAD").strip()`；`except RuntimeError` 时 `_log` 警告并返回 None（优雅降级，绝不引入新失败模式）。
     - 触发/跳过/失败三态均 `_log`；docstring 中显式写明 D6 语义变化（故意不 commit 仅声明 files_changed → 自动 commit）。
- **修改边界**：不改 `_dirty_tracked_paths` 本体；不改 `_acquire_repo_lock` / lock 路径；不接调用点（T3/T4 才接）。
- **质量检查方式**：
  - 检查项 1：`uv run ruff check src/loop_kit/_core.py` → 0 error
  - 检查项 2：`uv run python -m py_compile src/loop_kit/_core.py` → exit 0
- **验收标准**：
  - ✅ `uv run python -c "from loop_kit.orchestrator import _try_outer_commit_fallback, _worktree_dirty_split, _serial_outer_commit_whitelist, _outer_commit_fallback_enabled"` exit 0
  - ✅ 本任务测试部分全部通过（见下）
- **潜在风险**：helper 误吞异常导致静默不收敛 → 三态 `_log` 保证可观测。
- **预留歧义标注**：
  - [ ] 无歧义

**Task 2.1 测试部分**（新建 `tests/test_outer_commit_fallback.py`，与实现同任务提交；style 参照 `tests/test_dsh_backend.py`：`from loop_kit import orchestrator` + monkeypatch；不触真实 git）：
  - `test_enabled_default_true_and_env_zero_disables`（monkeypatch.setenv）
  - `test_serial_whitelist_from_lanes_union` / `test_serial_whitelist_from_in_scope` / `test_serial_whitelist_empty`
  - `test_dirty_split_includes_untracked_in_scope`（porcelain `??` 行）
  - `test_dirty_split_reports_tracked_out_of_scope`（` M` 行越界）
  - `test_dirty_split_ignores_untracked_out_of_scope`（遗留容忍）
  - `test_dirty_split_filters_loop_dir`
  - `test_fallback_positive_commit_and_head_backfill`（monkeypatch `orchestrator._git_at`：status→2 行 in-scope dirty；记录 add/commit/rev-parse 调用；断言 `add` argv == `["add", "--", *sorted(paths)]`、commit msg 含 `[outer-commit]` + task_id/round/lane_id；返回 new sha）
  - `test_fallback_negative_true_no_change`（fc 空 + dirty 空 → None，未以 commit 调 `_git_at`）
  - `test_fallback_negative_fc_outside_whitelist`
  - `test_fallback_negative_dirty_not_declared`（dirty ⊄ fc → None）
  - `test_fallback_negative_out_of_scope_tracked_dirty_blocks`
  - `test_fallback_negative_no_dirty_in_scope`（phantom 声明 → None）
  - `test_fallback_tolerates_untracked_out_of_scope_noise`（越界 `??` 不阻断，正向仍触发）
  - `test_fallback_commit_failure_returns_none`（"commit" 抛 RuntimeError → None）
  - `test_fallback_never_acquires_repo_lock`（monkeypatch `orchestrator._acquire_repo_lock` 为记录 sentinel → 断言未被调用，固化 V1 锁语义）
  - `test_fallback_env_zero_returns_none`（env 逃生阀）
- **测试部分边界**：只新增本测试文件；不改其它测试文件；不新建 conftest。
- **测试部分验收**：
  - ✅ `uv run --group dev pytest tests/test_outer_commit_fallback.py -q` exit 0，新增 ≥ 16 测试，0 skipped
  - ✅ `uv run ruff check tests/test_outer_commit_fallback.py` → 0 error
  - ✅ `uv run --group dev pytest tests/test_orchestrator.py tests/test_dsh_backend.py -q` 不回归

### Phase 2: lane 调用点接线 + 包装层测试（T3）

#### Task 3.1: lane 包装函数 + `_dispatch_lane` 调用点（实现 + 测试，同任务提交）
- **目标**：lane 模式 per-lane 外层 commit（修复 #3364 主路径）。
- **依赖**：T2.1
- **frontier**：是（与 T3.1 同波，均只依赖 T2.1；同文件不同区域，见波次表建议串行）
- **执行者**：Task Executor
- **修改内容**：`src/loop_kit/_core.py`：
  1. 新增 `_lane_outer_commit_fallback(lane_work: dict, lane: TaskLane, handle: LaneWorktreeHandle, *, base_sha: str, task_id: str, round_num: int, paths: LoopPaths | None = None) -> str | None`（纯查询，不改状态）：`lane_head = str(lane_work.get("head_sha", "")).strip()`；`lane_head` 非空且 `!= base_sha` → None；否则调 `_try_outer_commit_fallback(worktree=handle.path, whitelist=cast(list[str], lane.get("owner_paths", [])), files_changed=cast(list[str], lane_work.get("files_changed", [])), task_id=..., round_num=..., lane_id=str(lane.get("lane_id", "")), paths=paths)`。
  2. 在 `_dispatch_lane` 内 `lane_work = cast(WorkReport, artifact)`（grep 锚：`lane_work = cast(WorkReport, artifact)`）之后、`artifact_written_latency_ms = ...`（:12434）之前插入：
     ```python
     fallback_head = _lane_outer_commit_fallback(
         lane_work, lane, handle, base_sha=base_sha, task_id=task_id, round_num=round_num, paths=resolved_paths,
     )
     if fallback_head is not None:
         lane_work["head_sha"] = fallback_head
         _atomic_write_json(lane_local_report, lane_work)
         _log(f"Lane {lane_id}: outer commit fallback committed worker changes -> {fallback_head[:8]}")
     ```
  3. 语义注：回填后 `_enrich_work_report_runtime_fields`、`lane_reports[lane_id] = lane_work`、`_cherry_pick_lane_reports` 的 `lane_head == base_sha → "noop"` 分支（:8386-8389）自然变为 `applied`，merge 机制零改动。
- **修改边界**：不改 `_cherry_pick_lane_reports` / `_merge_lane_work_reports`；不改线程池调度结构；不碰 serial 路径（T4）。
- **质量检查方式**：
  - 检查项 1：`uv run ruff check src/loop_kit/_core.py` → 0 error
  - 检查项 2：`uv run python -m py_compile src/loop_kit/_core.py` → exit 0
- **验收标准**：
  - ✅ `uv run python -c "from loop_kit.orchestrator import _lane_outer_commit_fallback"` exit 0
  - ✅ 本任务测试部分全绿（见下）；现有 lane 相关测试（`uv run --group dev pytest tests/test_integration.py tests/test_e2e_smoke.py -q`，e2e 由 addopts 自动排除）不回归
- **潜在风险**：`base_sha` 闭包可见性——`_dispatch_lane` 定义于 :12379，`base_sha` 为 `_run_single_round` 局部（lane 模式在 :12357-12367 已 resolve），闭包读取更新值，无需 nonlocal。
- **预留歧义标注**：
  - [ ] 无歧义

**Task 3.1 测试部分**（追加至 `tests/test_outer_commit_fallback.py`）：
  - `test_lane_fallback_triggers_when_head_equals_base`（fake lane/handle/work，monkeypatch `_try_outer_commit_fallback` 返回 sha → 包装返回 sha）
  - `test_lane_fallback_triggers_when_head_empty`
  - `test_lane_fallback_skips_when_head_advanced`（head != base → 不调用核心 helper）
  - `test_lane_fallback_callsite_contract`（monkeypatch `_try_outer_commit_fallback`，断言传入 worktree==handle.path、whitelist==lane owner_paths、files_changed==work 声明、lane_id==lane["lane_id"]——契约级测试，代替深挖嵌套闭包）
- **测试部分验收**：
  - ✅ `uv run --group dev pytest tests/test_outer_commit_fallback.py -q` exit 0，新增 ≥ 4 测试，0 skipped
  - ✅ `uv run --group dev pytest -q`（全量）exit 0、failed=0（见 V1 基线口径）

### Phase 3: serial 调用点接线 + 测试（T4）

#### Task 4.1: serial 包装函数 + 13081 判定前调用点（实现 + 测试，同任务提交）
- **目标**：serial 模式（`max_parallel_workers=1` / 无 lanes）统一外层 commit 语义。
- **依赖**：T2.1
- **frontier**：是（与 T3.1 同波并行，均只依赖 T2.1）
- **执行者**：Task Executor
- **修改内容**：`src/loop_kit/_core.py`：
  1. 新增 `_serial_outer_commit_fallback(work: dict, task_card: TaskCard, *, base_sha: str, task_id: str, round_num: int, paths: LoopPaths | None = None) -> str | None`：`str(work.get("head_sha", "")).strip() != base_sha` → None；`whitelist = _serial_outer_commit_whitelist(task_card)`；调 `_try_outer_commit_fallback(worktree=ROOT, whitelist=whitelist, files_changed=..., task_id=..., round_num=..., lane_id=str(work.get("lane_id") or _SERIAL_LANE_ID), paths=paths)`；成功则 `work["head_sha"] = new_head` + `_atomic_write_json(resolved_paths.work_report, work)`（仿 :13079-13080 回写）并返回 new_head。
  2. 在 `_run_single_round` 中 `if head_sha == base_sha:`（grep 锚：`if head_sha == base_sha:`，唯一命中在 :13081 附近）之前插入：
     ```python
     if head_sha == base_sha and not lane_dispatch_enabled:
         fallback_head = _serial_outer_commit_fallback(
             work, task_card, base_sha=base_sha, task_id=task_id, round_num=round_num, paths=resolved_paths,
         )
         if fallback_head is not None:
             _log(f"Serial worker: outer commit fallback committed changes -> {fallback_head[:8]}")
             head_sha = fallback_head
     ```
  3. 语义注：回填后 :13081 判定为 False → 自然落入 :13109 `_diff(base, head)` / reviewer 流程；:13141 patch 任务 `_verify_plan_patch_scope` 对新 commit 照常生效（fail-closed 正确）；原 noop 分支一字不改（真 no-change 仍走 #2911 evidence gating）。
- **修改边界**：不改 noop handler（`_single_round_handle_worker_noop` :14268）；不改 phase 注册表；不改 lock/watchdog。
- **质量检查方式**：
  - 检查项 1：`uv run ruff check src/loop_kit/_core.py` → 0 error
  - 检查项 2：`uv run python -m py_compile src/loop_kit/_core.py` → exit 0
  - 检查项 3：`grep -n "worker_noop_as_error\|worker_noop_evidence_gating" src/loop_kit/_core.py` 确认 #2911 路径未被触碰
- **验收标准**：
  - ✅ `uv run python -c "from loop_kit.orchestrator import _serial_outer_commit_fallback"` exit 0
  - ✅ 本任务测试部分全绿（见下）
- **潜在风险**：serial 模式 ROOT 脏文件含其它进程残留 → whitelist + out-of-scope tracked 阻断 + untracked 容忍已覆盖；`work` 为 merged report 的场景由 `not lane_dispatch_enabled` 排除。
- **预留歧义标注**：
  - [ ] 无歧义

**Task 4.1 测试部分**（追加至 `tests/test_outer_commit_fallback.py`；用 tmp_path + 显式 LoopPaths/`_configure_loop_paths` 构造，参照 T1.1 复核的既有模式；`work_report` 路径指向 tmp 下文件）：
  - `test_serial_fallback_positive_backfills_work_and_rewrites_report`（monkeypatch `_try_outer_commit_fallback` 返回 sha；断言返回 sha、`work["head_sha"]` 已回填、work_report 文件 JSON 含新 head_sha）
  - `test_serial_fallback_skips_when_head_differs_from_base`
  - `test_serial_fallback_env_zero_disabled`（monkeypatch.setenv `LOOP_OUTER_COMMIT_FALLBACK=0` + 真实 helper 链 → None，不写文件）
  - `test_serial_fallback_no_whitelist_returns_none`（空 task_card）
  - `test_serial_fallback_does_not_acquire_repo_lock`（monkeypatch `_acquire_repo_lock` sentinel，走真实 helper 链一次触发路径 → sentinel 未被调用）
- **测试部分验收**：
  - ✅ `uv run --group dev pytest tests/test_outer_commit_fallback.py -q` exit 0，新增 ≥ 5 测试，0 skipped
  - ✅ `uv run --group dev pytest tests/test_orchestrator.py -q` 不回归（noop/证据门控既有测试全绿 = 真 no-change 语义保持的机器证明）

### Phase 4: 全量验证与文档收口（T5）

#### Task 5.1: 全量回归 + 语义文档确认 + 提交纪律复核
- **目标**：748 基线不回归确认；D6 语义文档在代码内完整；提交范围合规。
- **依赖**：T2.1、T3.1、T4.1
- **frontier**：否（收口）
- **执行者**：Task Executor
- **修改内容**：无新功能代码；如 T2-T4 遗留 docstring 缺口在此补齐（仅 `_core.py` 注释/docstring）。
- **修改边界**：不改功能逻辑。
- **质量检查方式**：
  - 检查项 1：`uv run --group dev pytest -q`（预期：exit 0，failed=0，passed ≥ 748 + 本计划新增测试数）
  - 检查项 2：`uv run ruff check src/loop_kit/_core.py tests` → 0 error
  - 检查项 3：`uv run python -m py_compile src/loop_kit/_core.py` → exit 0
  - 检查项 4：`uv run python -c "from loop_kit.orchestrator import *"` → exit 0
  - 检查项 5：`git diff --cached --stat` 每任务 commit 前只含声明文件
- **验收标准**：
  - ✅ V1-V6 全部通过（见下）
  - ✅ 每任务独立 commit 已落（`git log --oneline -6 | grep 3369` ≥ 4 个 commit，分别对应 T2/T3/T4/T5 范围）
- **潜在风险**：把 T5 的 commit 混入代码改动 → T5 原则上无代码改动，仅 docstring 缺口可例外（仍属 `_core.py`）。
- **预留歧义标注**：
  - [ ] 无歧义

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier（无人挡即刻开工） | 依赖已完成 |
|------|------------|--------------------------|------------|
| W1 | T1.1 | T1.1 | — |
| W2 | T2.1 | T2.1 | W1 |
| W3 | T3.1 / T4.1 | T3.1、T4.1 | T2.1（W2） |
| W4 | T5.1 | — | T2.1、T3.1、T4.1 |

> 并行约束：T3.1 与 T4.1 均只依赖 T2.1，可并行——但两者都写 `src/loop_kit/_core.py`（不同区域），若并行需分 worktree 或串行提交避免冲突；建议 T3.1 与 T4.1 串行执行。

## Post-Execution Verification

Dev Orchestrator 在所有 plan task 执行完毕后**必须**运行本节中的验证命令。

### Automated Verification（Dev Orchestrator 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量测试（默认排除 e2e） | `uv run --group dev pytest -q` | exit 0；failed=0；passed ≥ 748 + 本计划新增测试数（约 25） |
| V2 | 目标文件 lint | `uv run ruff check src/loop_kit/_core.py tests/test_outer_commit_fallback.py` | exit 0，0 error |
| V3 | 语法编译 | `uv run python -m py_compile src/loop_kit/_core.py` | exit 0 |
| V4 | 公共导入面 | `uv run python -c "from loop_kit.orchestrator import *"` | exit 0 |
| V5 | 提交范围合规 | `git log --oneline -6 --grep="#3369"` 且每 commit `git show --stat --name-only <sha>` | 每个 #3369 commit 只含 `src/loop_kit/_core.py` 与/或 `tests/test_outer_commit_fallback.py` |
| V6 | noop 语义机器证明 | `uv run --group dev pytest tests/test_orchestrator.py -q` | exit 0（真 no-change 仍 blocked 的既有测试全绿） |

### Manual Verification（三级分类）

### Deferred (needs restart / deployment)

- [ ] 无（本任务无服务重启/部署项）

### Probe (best-effort, run if available)

- [ ] P1: `grep -n "LOOP_OUTER_COMMIT_FALLBACK" src/loop_kit/_core.py` 命中 helper 定义（env 开关存在性）
- [ ] P2: `grep -n "\[outer-commit\]" src/loop_kit/_core.py tests/test_outer_commit_fallback.py` 命中 commit message 标记与断言（标记贯穿实现+测试）
- [ ] P3: `git status --porcelain` 确认 untracked 遗留（5 plan 文件 + `data/`）未被任何 #3369 commit 卷入

### Manual（真正需要人工判断）

- [ ] M1: 阅读 `_try_outer_commit_fallback` docstring，确认 D6 语义变化（worker 故意不 commit 仅声明 files_changed → 自动 commit）文档完整、无歧义
- [ ] M2: 阅读 T2.1 `test_fallback_never_acquires_repo_lock` 与 V1 消解结论，确认锁语义（父进程持锁覆盖、子进程不获取）理解正确

## 风险表

| Risk | Impact | Mitigation |
|------|--------|------------|
| 误 commit 越界文件（lane 隔离削弱） | 高 | fc ⊆ owner_paths + out-of-scope tracked dirty 阻断 + `git add -- <explicit paths>` 显式路径（绝无 `-A`） |
| #2911 证据门控语义回归（真 no-change 不再 blocked） | 高 | 回退仅在三重判据（dirty 非空 ∧ dirty ⊆ fc ∧ fc ⊆ whitelist）满足时触发；否则原 noop 分支一字不改；V6 机器证明 |
| dirty 实测与声明不一致导致误触发（伪造 files_changed） | 中 | commit 集合 = 实测 dirty ∩ 声明 ∩ whitelist；phantom 声明无 dirty 时判据 6 直接 None |
| serial 模式 ROOT untracked 遗留误伤 | 中 | out-of-scope untracked 容忍（`_worktree_dirty_split` 只上报 out-of-scope tracked） |
| 子进程内 commit 与 repo 锁交互（#3155） | 中 | V1 消解：正常流程父进程持 flock 覆盖子进程 commit；子进程禁止再获取（自死锁）；T2.1 锁语义测试固化 |
| 并行 lane commit 并发写共享 .git | 低 | git 自身 index.lock 串行化；与现有 worker 自 commit 的并行度一致，无新增并发模式 |
| 748 基线回归 | 中 | V1/V6 全量 + 分文件回归；每任务独立 commit 可 `git revert` 定点回滚 |
| 行号锚点漂移 | 低 | 全部锚点用 grep 语义锚（函数名/注释串），Phase 首步强制基线重检 |
| worker 未声明 untracked 新文件 → 回退不触发（仍 blocked） | 中（操作性） | 判据严格性所致（防伪造优先）；prompt 引导为 follow-up（本计划非目标，建议记 PM 备注） |
| 跨项目依赖 | — | 无：仅 agent-task-runner 仓内 `_core.py` + tests |

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（任务粒度 ≤3 文件/任务、Phase 划分、波次依赖） | 1 | 1 | 0 |
| R1.5 | 外部引用事实核查（全部行号/函数/常量本会话直接读取实测：13841/13081/14268/8090/7536/8588/8752/422/7283/130 等） | 0 | 0 | 0 |
| R2 | 可执行性（pytest collect 实测 749/752-3 deselected；ruff 配置实测；uv 命令实测） | 0 | 0 | 0 |
| R2.8 | LLM 可执行性（逐字段消除猜测：helper 签名、插入锚点、commit message 格式、staging 纪律全部显式化） | 0 | 0 | 0 |
| R3 | 风险与边缘（锁语义/并发/遗留文件/证据门控/patch 模式交互） | 2 | 2 | 0 |
| **终止** | **T5 all green — 全量 pytest + ruff + py_compile + import 面 + 提交范围 V5 全过** | | | **0** |

## 附：本计划与 PM #3369 硬约束逐条对照

| 硬约束 | 满足方式 |
|--------|---------|
| 只改 agent-task-runner 仓 | 修改范围仅 `src/loop_kit/_core.py` + `tests/test_outer_commit_fallback.py` |
| 不新增 CLI 参数 | 开关 = env `LOOP_OUTER_COMMIT_FALLBACK`（D3），无 argparse/RunConfig 变更 |
| 不削弱 lane 隔离 | fc ⊆ owner_paths + 越界 tracked 阻断 + 显式路径 add |
| #2911 语义保持 | 回退未触发时原 noop 分支零改动；V6 证明 |
| #3155 锁 / #3263 watchdog 保持 | 不改锁代码、不改 watchdog；锁语义见 V1 |
| 748 基线不回归 | V1 全量门槛 |
| 不卷入 untracked 遗留 | 提交纪律（只 stage 声明文件）+ P3 核查 |


## Execution Log

### [2026-09-05] 执行完成（Dev Orchestrator，5/5 任务 ✅）

- **T1.1 ✅**（只读复核）：3 项消解结论全部对当前 HEAD（a370ec1）成立——repo 锁父进程持有（:13867 仅 not single_round 获取）、merged lane report 无顶层 lane_id（:8090）、_git_at = git -C（:7536）。5 个补充锚点（_parse_porcelain_path :8579、_owner_paths_overlap :8752、_SERIAL_LANE_ID :422、_atomic_write_json :7283、_task_lane_ids :7520）全命中。
- **T2.1 ✅**（commit e27ab17）：helper 族落地（_serial_outer_commit_whitelist/_outer_commit_fallback_enabled/_normalize_declared_path/_worktree_dirty_split/_try_outer_commit_fallback）+ 20 单测。**CT 两项 🟡 已折入**：① glob in_scope 条目过滤（_serial_outer_commit_whitelist）；② 声明路径归一化（_normalize_declared_path 与 whitelist 归一化）。
- **T3.1 ✅**（commit 6be611b）：_lane_outer_commit_fallback 包装 + _dispatch_lane 内 per-lane 调用点（merge 前）+ 4 契约测试。全量 772 passed。
- **T4.1 ✅**（commit eaf4e61）：_serial_outer_commit_fallback 包装 + 13289 no-change 门前的 serial 调用点 + 5 测试。全量 777 passed。
- **T5.1 ✅**：V1 全量 777 passed/1 skipped/3 deselected（基线 748 + 29 新增）；V2 ruff 0 error；V3 py_compile OK；V4 import OK；V5 3 个 #3369 commit 均仅 2 文件；V6 noop 语义机器证明 692 passed；P1 env 开关命中；P2 [outer-commit] 标记贯穿实现+测试；P3 tracked 干净。

**偏差汇总**：
- [D1] T2.1：whitelist 尾斜杠（"coupling/"）使 _owner_paths_overlap 失配——whitelist 条目统一经 _normalize_declared_path 归一化（超出计划原文的最小修正，行为与计划意图一致）
- [D1] T4.1：测试 LoopPaths 为 frozen dataclass，work_report 不可直接赋值——改用 _configure_loop_paths 后直接写 paths.work_report 路径
- 计划 CT 阶段（critical-thinking）verdict=MINOR，2 项 🟡 已折入实现口径
