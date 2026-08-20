---
plan_id: nochange-evidence-gating-2026-08-20
pm_task: "#2911"
scope_mode: HOLD
generated_at: "2026-08-20"
repos:
  - name: agent-task-runner
    path: /home/gw/opt/agent-task-runner
    git_commit: f3be362
    files:
      - { path: src/loop_kit/_core.py, sha256: 9042d8e9cfc1232c1cddd1e9694ea01658b3481f506a07e5946c158aa9bdfc37 }
      - { path: tests/test_orchestrator.py, sha256: 51c14021b35cb0f85fbbe059bf615788e0bb3cb6824b05d60d736f28c976850a }
      - { path: README.md, sha256: 1c8cf2b0b52da97daad152c1773ac1c5ad99c44c56f93f9a57f75b9f1b7dcdc3 }
  - name: project_management
    path: /home/gw/opt/project_management
    git_commit: 7b09153
    files:
      - { path: src/auto_task/bridge.py, sha256: c485d9f6a453811a0d861ce9a314c12be096bbe4f811e41bc13a033fc2675b12 }
---

# 执行计划：loop_kit no-change 语义证据门控（PM #2911）

## 背景与目标

- **问题描述**：worker 幂等确认"任务已完成"（产物已存在且已提交，无可改 → head_sha == base_sha）时，loop_kit 默认判定为 `validation_failure`（rc=3）。本任务在默认路径上增加**证据门控**：有历史证据 → 成功路径（`no_change_success`）；无证据 → 维持失败（防偷懒 worker 蒙混）。
- **已核实基线**（2026-08-20 实测，工作区干净）：
  - 判定点 `src/loop_kit/_core.py:11866`（`head_sha == base_sha`）→ 分发 `_single_round_handle_worker_noop`（:12654，分发表 :12950）→ 默认 raise `ValidationError` rc=3（:12703）；调用方 catch 在 :11878-11888。
  - **已有无条件逃生舱**（早于本任务，禁止移除）：`--worker-noop-as-success` → `no_change_success` terminal success（:12705-12729）；`README.md:178-180` 已文档化；bridge 已映射 `no_change_success → done`（`bridge.py:765/784`，`_SUCCESS_OUTCOMES`）。
  - 证据源（loop 侧跨轮持久）：`archive/<task_id>/r{N}_work_report.json` 与 `r{N}_state.json`（`_archive_bus_file` :938-941、`_archive_state_for_round` :1076、`_task_archive_dir` :770；`WorkReport` 含 `run_id` 字段 :127）、`state.round_details[].worker_notes`（:12675 carry-forward）。ATR 重试复用同一 `loop_dir`（bridge re-enqueue 不清 loop_dir）。
  - ⚠️ bridge `_detect_artifact_evidence`（`bridge.py:902`）git log 窗口基期 = `started_at - _EVIDENCE_WINDOW_SEC(21600)`（:915-918）→ 跨 run 上一轮 commit 可能漏检。队列表已有 `created_at` 列（`bridge.py:213`）。
  - 状态机：`STATE_TRIGGER_WORKER_NO_CHANGE_SUCCESS` 的 `default_updates` 硬编码 `outcome=no_change_success`（:6374-6380）→ 复用该 outcome 则零迁移改动。
- **目标**：默认路径证据门控（flag/env 管道 + kill-switch）、bridge 证据窗口基期修正 + loop archive 证据消费、双路径单测、README 文档化、双仓独立 commit。
- **非目标（不做什么）**：不改 reviewer 对真实改动的评审语义；不新增 outcome 枚举；不改 ATR 调度/重试策略；不将 worker LLM stdout 文本作为证据（U4 口径）；不迁移 loop_dir；不新增依赖。

## 修改方案

### 关键设计决策（trade-off 记录）

**D1 — 证据门控默认内嵌开启 + kill-switch（选） vs 仅 opt-in flag**
- 选：`DEFAULT_WORKER_NOOP_EVIDENCE_GATING=True` 默认内嵌于默认路径；`--worker-noop-no-evidence-gating` / `LOOP_WORKER_NOOP_EVIDENCE_GATING=false` 为 kill-switch。
- 理由：任务 notes 明示"默认路径……有证据 → 成功路径"；T-2902 场景零配置即修复；opt-in 需改 ATR 调用点，多系统耦合。
- 风险：默认行为变化 → 独立 commit 可 revert + kill-switch + 双路径单测锁定。

**D2 — 复用 `no_change_success` outcome（选） vs 新增 `no_change_evidence_success`**
- 理由：bridge `_SUCCESS_OUTCOMES`/`OUTCOME_TO_PM_STATUS` 零改动、状态机迁移规则零改动、既有测试零破坏；验收条件明确允许 `no_change_success`。可观测性由 `round_detail["no_change_evidence"]` 补偿（summary.json 内嵌 round_details，bridge 可消费）。
- 风险：外部无法从 outcome 区分无条件/证据门控成功 → round_detail 证据字段 + feed event 字段补偿。

**D3 — 证据判定非致命：读归档异常一律跳过该工件，绝不 raise**
- 理由：证据是旁路信号，归档损坏/版本漂移绝不能引入新失败模式。
- 风险：漏读证据 → 误判失败（安全侧，与旧行为一致）。

**D4 — bridge 窗口基期改为 `created_at`，窗口长度不变（选） vs 单纯放大 `_EVIDENCE_WINDOW_SEC`**
- 理由：`created_at` 覆盖队列全生命周期（含全部重试间隙），语义正确、不放大误报面；老行 `created_at` NULL → fallback `started_at`。
- 风险：证据命中面变大，但仅用于 `partial_success` 兜底救援路径（#2742 既有机制），不影响 done 判定。

### 证据充分性判定规则（优先级从高到低，命中即停）

| 优先级 | 来源 | 判定条件 | 强度 |
|--------|------|----------|------|
| P1 | `archive/<task_id>/r{N}_work_report.json`（历史工件） | `files_changed` 非空 或 `notes` strip 后非空 | files_changed=STRONG / notes=MEDIUM |
| P2 | `archive/<task_id>/r{N}_state.json`（历史工件） | 顶层 `outcome` ∈ `_TERMINAL_SUCCESS_OUTCOMES` 或 其 `round_details` 任一 `review_decision=="approve"` | STRONG |
| P3 | `state.round_details`（内存态，跨轮 carry-forward） | 条目 `round != 当前轮` 且（`review_decision=="approve"` 或 `worker_notes` 非空） | MEDIUM |
| P4 | bridge git evidence（扩窗后） | `dirty_files` / `commits`（created_at 基期窗口）/ `output_files` / `loop_archive` 任一命中 | STRONG（bridge 侧消费） |

**排除规则**：`round == 当前轮 AND payload.run_id == 当前 run_id` 的归档工件不参与判定（防当前轮自我认证）；round_details 仅取 `round != 当前轮` 条目。证据 verdict 结构：`{"source": "archive_work_report"|"archive_state"|"round_details", "round": int, "run_id": str|null, "detail": str}`。

## 执行计划

### Phase 1: loop_kit 证据门控核心（agent-task-runner，commit C1）

#### Task 1.1: 证据判定函数 + noop handler 集成 + RunConfig 字段
- **目标**：默认路径在 no-change 时执行证据门控，有证据走成功路径。
- **依赖**：无
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**（全部在 `src/loop_kit/_core.py`）：
  - 在 `:351` `DEFAULT_WORKER_NOOP_AS_ERROR = True` 之后新增 `DEFAULT_WORKER_NOOP_EVIDENCE_GATING = True`。
  - 在 `:601` RunConfig 字段 `worker_noop_as_error` 之后新增 `worker_noop_evidence_gating: bool = DEFAULT_WORKER_NOOP_EVIDENCE_GATING`。
  - 在 `:8602-8609` bool 校验元组追加 `("worker_noop_evidence_gating", config.worker_noop_evidence_gating)`。
  - 在 `_single_round_handle_worker_noop`（:12654）之前新增三个模块级私有函数，复用现有 `_archive_rounds_for_task`（:9631）、`_load_archived_round_artifact`（:9494）、`_TERMINAL_SUCCESS_OUTCOMES`（:411）：
    - `_noop_evidence_from_archive(task_id, round_num, run_id, paths) -> dict | None`：遍历 `_archive_rounds_for_task` 返回的轮次；对 `("work_report", "state")` 逐一 `_load_archived_round_artifact`（try/except `(ValidationError, ConfigError, json.JSONDecodeError, OSError)` → continue）；跳过 `r == round_num and payload.get("run_id") == run_id` 的工件；按 P1/P2 规则判定，命中即返回 verdict。
    - `_noop_evidence_from_round_details(state, round_num) -> dict | None`：按 P3 规则判定。
    - `_resolve_noop_evidence(state, task_id, round_num, run_id, paths) -> dict | None`：依次调用 archive → round_details，返回首个命中。
  - 重构 `_single_round_handle_worker_noop` 分支（签名不变；**不修改**调用方 :11870-11888 与分发表 :12950）：
    - 函数开头（round_detail 构造前）插入：`evidence = _resolve_noop_evidence(state, task_id, round_num, run_id, resolved_paths) if (config.worker_noop_as_error and config.worker_noop_evidence_gating) else None`
    - `take_success = (not config.worker_noop_as_error) or evidence is not None`
    - round_detail 中：`review_decision` 取 `"skipped_no_change_evidence"`（evidence 非 None）否则 `"skipped_no_change"`；`round_outcome` 取 `"no_change_success"`（take_success）否则 `"validation_failure"`；evidence 非 None 时 `round_detail["no_change_evidence"] = evidence`。
    - 失败分支条件由 `if config.worker_noop_as_error:` 改为 `if config.worker_noop_as_error and evidence is None:`；失败分支内容不变，仅 raise 消息尾部追加 `" (evidence gating enabled but no historical evidence found)"`。
    - 成功分支内容不变；`_feed_event` 的 data 在 evidence 非 None 时增加 `"no_change_evidence": evidence`。
- **修改边界**：不得修改 `_apply_state_transition`、`STATE_TRIGGER_WORKER_NO_CHANGE_SUCCESS` 迁移规则（:6374-6380）、`--worker-noop-as-success` 分支行为、调用方 :11870-11888、分发表 :12950；不得新增 outcome 字符串。
- **质量检查方式**：`uv run python -m py_compile src/loop_kit/_core.py`；`uv run ruff check src/loop_kit`；定向跑 4775/4843 两测试不回归。
- **验收标准**：
  - ✅ 新常量/字段/三函数存在；无证据时 `_resolve_noop_evidence` 返回 None
  - ✅ `test_single_round_no_change_can_be_terminal_success` 与 `test_single_round_no_change_default_is_validation_failure` 通过
- **潜在风险**：round_detail 结构变化被既有断言依赖 → 已核实测试仅断言 `state.outcome`/`summary.outcome`，无 `skipped_no_change` 字符串断言（grep 0 命中）。
- **预留歧义标注**：[x] 无歧义：所有字段可直接执行

#### Task 1.2: CLI flag 对 + env + outer-loop 传播管道
- **目标**：证据门控可配置/可关断，内外循环语义一致。
- **依赖**：T1.1
- **frontier**：否
- **执行者**：Task Executor
- **修改内容**（`src/loop_kit/_core.py`）：
  - `:523` `_KNOWN_CONFIG_KEYS` 增加 `"worker_noop_evidence_gating"`。
  - `:8657-8659` 模式新增 env 捕获：`LOOP_WORKER_NOOP_EVIDENCE_GATING` → `env_cfg["worker_noop_evidence_gating"]`。
  - `:10069` env defaults 元组增加 `("worker_noop_evidence_gating", True)`。
  - `:10246-10249` outer-loop cmd 传播：`if config.worker_noop_evidence_gating: cmd.append("--worker-noop-evidence-gating") else: cmd.append("--worker-noop-no-evidence-gating")`。
  - `:13196`（`--worker-noop-as-success` 之后）新增两个 argparse 参数（`store_true`，`default=None`）：
    - `--worker-noop-evidence-gating`（help: Enable evidence gating on the default no-change failure path (default)）
    - `--worker-noop-no-evidence-gating`（help: Disable evidence gating; no-change without --worker-noop-as-success always fails）
  - `:13312-13320` 模式：两 flag 同设 → raise ValidationError；`evidence_gating_cli = True/False/None` 解析。
  - `:13389-13395` RunConfig 构造增加 `worker_noop_evidence_gating=_coerce_bool_config(_cfg_val(evidence_gating_cli, "worker_noop_evidence_gating", DEFAULT_WORKER_NOOP_EVIDENCE_GATING), field_name="worker_noop_evidence_gating")`。
- **修改边界**：不修改 `--worker-noop-as-error`/`--worker-noop-as-success` 既有 flag 语义与互斥检查；不改 env 解析 helper 本身。
- **质量检查方式**：`uv run python -m py_compile src/loop_kit/_core.py`；`uv run ruff check src/loop_kit`；既有 flag 传播测试（7056/7092）不回归。
- **验收标准**：
  - ✅ `python -m loop_kit run --help` 输出含两个新 flag（可用 `uv run python -c "..."` 触发 argparse 帮助，或跑 `test_main_run_parses_worker_noop_flags` 系列）
  - ✅ 两 flag 同设时抛 ValidationError（互斥）
- **潜在风险**：`_cfg_val` 对 None 与默认值的三级解析顺序 → 严格照 `worker_noop_as_error` 现有模式实现。
- **预留歧义标注**：[x] 无歧义

#### Task 1.3: 双路径单测（tests/test_orchestrator.py）
- **目标**：锁定证据门控双路径 + flag 管道 + 排除规则。
- **依赖**：T1.1、T1.2
- **frontier**：否
- **执行者**：Task Executor
- **修改内容**（`tests/test_orchestrator.py`，追加在 4843 附近）：
  - `test_single_round_no_change_with_archive_evidence_is_success`：`_configure_loop_paths` 后预置 `orchestrator.LOOP_DIR / "archive" / "T-604" / "r1_work_report.json"`（内容含 `task_id/round:1/run_id:"prev-run"/head_sha:"old"/files_changed:["src/x.py"]`）；照 4775 模式 monkeypatch `_wait_for_file`/`_is_git_repo_root`/`_resolve_commit_oid`/`_diff`/`_log_oneline`；`cmd_run(_run_config(str(task_path), allow_dirty=True), single_round=True, round_num=1)`（默认 config，gating 默认开）→ 断言 `state["outcome"]=="no_change_success"`、`state["state"]==STATE_DONE`、`summary["round_details"][-1]["no_change_evidence"]["source"]=="archive_work_report"`、review_request.json 不存在。
  - `test_single_round_no_change_with_archive_notes_evidence_is_success`：同上但 `files_changed:[]`、`notes:"verified artifacts exist"` → 成功（P1 MEDIUM）。
  - `test_single_round_no_change_with_archive_state_evidence_is_success`：预置 `r1_state.json`（`outcome:"approved"`，含 task_id/round/run_id）→ 成功，source=="archive_state"。
  - `test_single_round_no_change_without_evidence_still_fails`：无归档 → `state["outcome"]=="validation_failure"`、rc=3（`cmd_run` 抛 ValidationError 或 state 断言，照 4843 断言方式）。
  - `test_single_round_no_change_evidence_gating_disabled_fails_with_evidence`：预置证据 + `_run_config(..., worker_noop_evidence_gating=False)` → validation_failure。
  - `test_single_round_no_change_ignores_current_run_artifacts`：monkeypatch `_new_run_id` 返回固定 `"cur-run"`；预置 `r1_work_report.json` 的 `run_id=="cur-run"` → 排除 → validation_failure。
  - `test_main_run_parses_worker_noop_evidence_gating_flags`（照 3766 模式）：`--worker-noop-evidence-gating` → True；`--worker-noop-no-evidence-gating` → False；无 flag → 默认 True。
  - `test_main_run_rejects_conflicting_worker_noop_evidence_gating_flags`（照 3796 模式）。
  - `test_outer_loop_propagates_worker_noop_evidence_gating_flag`（照 7056 模式，双向断言）。
- **修改边界**：不改任何既有测试函数；新测试不得依赖网络/真实 git。
- **质量检查方式**：`uv run --group dev pytest tests/test_orchestrator.py -q -k "no_change or noop or evidence"`。
- **验收标准**：
  - ✅ 新增测试全绿；既有 4775/4843/7056/7092/7440/7654/9153 全绿
  - ✅ `uv run --group dev pytest -m "not e2e" -q` = 615 passed + 2 预存在失败（test_shows_context_file_stats、test_task_card_in_resettable_files），0 新增失败
- **潜在风险**：预置归档路径需与 `_configure_loop_paths` 设置的 LOOP_DIR 一致（该 helper 已存在，照 4775 用法）；`_archive_state_for_round` 的 `if dest.exists(): return dest` 会保留预置 r1_state.json（不影响断言）。
- **预留歧义标注**：[x] 无歧义

### Phase 2: README 文档化（agent-task-runner，commit C2）

#### Task 2.1: README no-change 证据门控段落
- **目标**：文档化证据门控规则，与既有 178-180 段衔接。
- **依赖**：T1.2（flag 名称最终确定）
- **frontier**：否
- **执行者**：Task Executor
- **修改内容**（`README.md`，:178-180 段落之后）：
  - 更新 no-change 语义要点列表：default 行改为"terminal `validation_failure`；若证据门控开启且存在历史证据 → `no_change_success`（reviewer 跳过）"。
  - 新增小节 `### Worker no-change evidence gating`：P1-P3 证据源与优先级、排除规则（当前轮工件/当前 run 排除）、flag 一览（`--worker-noop-evidence-gating` / `--worker-noop-no-evidence-gating` / `LOOP_WORKER_NOOP_EVIDENCE_GATING`）、kill-switch 说明、与 bridge `partial_success` 兜底的关系（P4）。
- **修改边界**：不改 178-180 既有 `--worker-noop-as-success` 措辞；不删任何既有段落。
- **质量检查方式**：`git diff README.md` 人工核对渲染。
- **验收标准**：
  - ✅ `grep -n "evidence gating" README.md` 命中新小节
  - ✅ 既有 `--worker-noop-as-success` 文档行原样保留
- **潜在风险**：低。
- **预留歧义标注**：[x] 无歧义

### Phase 3: bridge 证据窗口修正 + loop archive 证据（project_management，commit C3）

#### Task 3.1: bridge 证据窗口基期 + loop archive 证据消费
- **目标**：跨 run commit 不漏检；loop 侧归档证据可直接支撑 partial_success。
- **依赖**：无（独立仓库）
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**（`src/auto_task/bridge.py`）：
  - `_collect_entry_evidence`（:935-950）：SELECT 增加 `created_at`；调用改为 `_detect_artifact_evidence(str(loop_dir), started_at, created_at)`。
  - `_detect_artifact_evidence`（:902-930）：签名改为 `(loop_dir_str: str, started_at: str | None, created_at: str | None = None)`；窗口基期 `window_base = created_at or started_at`（created_at 恒 ≤ started_at；两者皆 None → 跳过 commits 检测）；`since_dt = datetime.fromisoformat(str(window_base).replace(" ", "T")) - timedelta(seconds=_EVIDENCE_WINDOW_SEC)`。
  - 新增模块级函数 `_loop_archive_evidence(loop_dir: Path, task_id: str) -> list[dict]`：glob `archive/<task_id>/r*_work_report.json` 与 `r*_state.json`；work_report 中 `files_changed` 非空或 `notes` strip 非空 → 条目 `{"file": name, "round": r, "kind": "work_report", "signal": "files_changed"|"notes"}`；state 中 `outcome` ∈ `_SUCCESS_OUTCOMES` → `{"kind": "state", "signal": "outcome"}`；读取异常跳过；上限 5 条。
  - `_detect_artifact_evidence` 末尾（output_files 之后）：`task_id = card.get("task_id")`；非空时 `ev["loop_archive"] = _loop_archive_evidence(loop, str(task_id))`；最终判定条件改为 `if ev["dirty_files"] or ev["commits"] or ev["output_files"] or ev.get("loop_archive"): return ev`。
  - `_build_partial_success_body`（:953-970）：在产物证据渲染后增加 `loop_archive` 段落（逐条 `- r{N} work_report: files_changed`）。
- **修改边界**：不改 `_SUCCESS_OUTCOMES`/`OUTCOME_TO_PM_STATUS`/`_mark_partial_success`/`_mark_failed` 判定逻辑；不改 `_EVIDENCE_WINDOW_SEC` 默认值；不改 `_git_log_since` 签名。
- **质量检查方式**：`python -m py_compile src/auto_task/bridge.py`；`python -m pytest tests/test_bridge_partial_success.py -q` 不回归。
- **验收标准**：
  - ✅ 函数签名/新增 helper 存在；`created_at or started_at` 基期逻辑生效
  - ✅ 既有 `tests/test_bridge_partial_success.py` 全绿
- **潜在风险**：`created_at` 格式与 `started_at` 相同（均为 `datetime('now')` 默认值 SQLite 格式）→ 直接复用现有 `replace(" ", "T")` 解析，无需新解析器。
- **预留歧义标注**：[x] 无歧义

#### Task 3.2: bridge 证据单测（project_management）
- **目标**：锁定扩窗基期与 loop archive 证据行为。
- **依赖**：T3.1
- **frontier**：否
- **执行者**：Task Executor
- **修改内容**（`tests/test_bridge_partial_success.py`，追加测试函数）：
  - `test_detect_artifact_evidence_uses_created_at_window_base`：tmp_path 真实 git repo，commit 时间早于 `started_at - 6h` 但晚于 `created_at - 6h`；构造 task_card（workspace_path 指向 repo）+ loop_dir；调 `_detect_artifact_evidence(loop_dir, started_at=now, created_at=10h前)` → `ev["commits"]` 非空（旧逻辑会 miss）。
  - `test_detect_artifact_evidence_falls_back_to_started_at`：`created_at=None` → 行为与旧一致。
  - `test_detect_artifact_evidence_reads_loop_archive`：loop_dir 下构造 `archive/T-1/r1_work_report.json`（files_changed 非空）→ `ev["loop_archive"]` 非空且 ev 非 None。
  - `test_detect_artifact_evidence_loop_archive_state_outcome`：`r1_state.json` outcome="approved" → 命中。
  - `test_loop_archive_evidence_skips_malformed_files`：坏 JSON 文件 → 不 raise，跳过。
- **修改边界**：不改既有测试函数；复用文件内 `_QUEUE_DDL` 与 import 结构。
- **质量检查方式**：`python -m pytest tests/test_bridge_partial_success.py -q`。
- **验收标准**：
  - ✅ 新测试全绿；既有测试不回归
- **潜在风险**：真实 git repo 构造需 `git init`/`git config user`/commit（既有测试已有同类构造可参照）。
- **预留歧义标注**：[x] 无歧义

### Phase 4: 双仓回归与交付（无代码改动）

#### Task 4.1: 全量回归 + 提交记录核对
- **目标**：双仓全量验证，确认三 commit 隔离干净。
- **依赖**：全部前置任务
- **frontier**：否
- **执行者**：Task Executor
- **修改内容**：无代码改动；执行下方 Post-Execution Verification 全部命令；核对 git log 三 commit 存在且不互相污染（`git diff HEAD~1..HEAD --stat` 范围仅限声明文件）。
- **修改边界**：不得再改任何代码（发现问题回对应 task 修复）。
- **质量检查方式**：命令见 Post-Execution Verification。
- **验收标准**：
  - ✅ V1-V5 全部通过（含基线 2 预存在失败说明）
  - ✅ agent-task-runner 2 commit、project_management 1 commit，改动文件集与各自 task 声明一致
- **潜在风险**：ATR daemon 加载旧 bridge → 见 Deferred D1。
- **预留歧义标注**：[x] 无歧义

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier（无人挡即刻开工） | 依赖已完成 |
|------|------------|--------------------------|------------|
| W1 | T1.1, T3.1 | T1.1, T3.1 | — |
| W2 | T1.2, T3.2 | T1.2, T3.2 | W1 |
| W3 | T1.3, T2.1 | T1.3, T2.1 | W2 |
| W4 | T4.1 | T4.1 | W3 |

注：T1.1/T1.2/T1.3 同文件（_core.py/tests）故串行；T3 与 T1 分属两仓库可并行，但 T3 的 partial_success 消费 P4 证据不依赖 T1 落地（bridge 侧独立判定）。

## Post-Execution Verification

### Automated Verification（Task Executor 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | loop_kit 全量测试（agent-task-runner） | `uv run --group dev pytest -m "not e2e" -q` | 615 passed；仅 2 预存在失败（test_shows_context_file_stats、test_task_card_in_resettable_files）；0 新增失败 |
| V2 | lint | `uv run ruff check src/loop_kit tests` | exit 0，0 errors |
| V3 | 编译检查 | `uv run python -m py_compile src/loop_kit/_core.py src/loop_kit/orchestrator.py` | exit 0 |
| V4 | 定向 noop 测试 | `uv run --group dev pytest tests/test_orchestrator.py -q -k "no_change or noop or evidence"` | 全绿 |
| V5 | bridge 测试（project_management） | `python -m pytest tests/test_bridge_partial_success.py -q` | 全绿 |
| V6 | bridge 编译 | `python -m py_compile src/auto_task/bridge.py` | exit 0 |

### Deferred (needs restart / deployment)
- [ ] D1: ATR daemon 重启后 bridge.py 新逻辑生效（Task Executor 不执行重启；给出发现命令：`systemctl list-units | grep -i atr` 或 `ps aux | grep -i auto_task`）。预期：重启后 ATR 日志不再出现旧窗口漏检，`loop_archive` 字段出现在 partial_success 通知中。

### Probe (best-effort, run if available)
- [ ] P1: `ps aux | grep -i "auto_task" | grep -v grep` — 记录 ATR 进程存在性（用于 D1 对照）。

### Manual（真正需要人工判断）
- [ ] M1: 人工抽查一次真实 ATR no-change+证据场景的 `summary.json`，确认 `round_details[].no_change_evidence` 字段内容与预期证据源一致。
- [ ] M2: 人工复核 README 新小节渲染与 flag 描述准确。

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（阶段/任务/验收/边界齐全） | 1（round_detail 排除规则初始未覆盖跨 run 同轮） | 1 | 0 |
| R1.5 | 外部引用事实核查（19 个锚点全部实测核实） | 1（snapshot 记录 #2622 未提交改动已过期，实际工作区干净） | 1 | 0 |
| R2 | 可执行性（命令实测：py_compile/ruff/pytest 基线 615+2） | 0 | 0 | 0 |
| R2.8 | LLM 可执行性（逐字段消歧：证据规则表、flag 名称、排除规则、异常跳过语义） | 2（P2 判定初始含 pre-round state 快照误判风险；bridge created_at 解析格式未定） | 2 | 0 |
| R3 | 风险与边缘（默认行为变化回滚、归档覆盖竞态、测试基线归因） | 1（kill-switch 缺失） | 1 | 0 |
| **终止** | **[T1] — 全部 issue 清零，计划可交付** | | | **0** |

## 风险与回滚

| 风险 | 概率 | 影响 | 缓解/回滚 |
|------|------|------|-----------|
| 默认路径行为变化（有证据即成功）影响现存使用方 | 中 | 中 | kill-switch 仅对直接 loop_kit run 生效；ATR 任务回滚 = git revert（bridge cmd 固定硬编码，operator 无法经 ATR 注入 flag）；C1 独立 commit 可 `git revert` |
| 归档工件被同轮新 run 覆盖导致跨 run 证据丢失（`_archive_bus_file` 覆盖语义） | 低 | 中 | 排除规则基于 run_id；若覆盖发生，P2/P3 仍可兜底；已知局限记录 README |
| bridge 窗口基期变早引入无关历史 commit → 误判 partial_success | 低 | 低 | partial_success 是"失败兜底救援"路径（#2742），非 done 白名单，影响面受限 |
| 证据判定误把当前轮工件当历史证据 | 低 | 高 | 排除规则 + T1.3 专门单测（test_single_round_no_change_ignores_current_run_artifacts） |
| 测试基线 2 预存在失败被误归因于本计划 | 低 | 低 | V1 验收口径明确：只比较"新增失败"集合，2 预存在失败为已知项 |


## CT 审阅合入（2026-08-20，critical-thinking 裁定）

### 🔴 必改（执行前）——证据限定跨 run
同 run 前轮证据与"任务已完成"反相关：round-1 worker 改文件 → reviewer changes_required → round-2 worker noop → 若采信同 run 前轮归档 → 直接 done，reviewer 驳回从未被满足（偷懒 dodge 通道）。
**改法**：P1/P2/P3 archive/state/round_details 证据一律要求 `run_id != 当前 run_id`（跨 run 才采信）；同 run 前轮证据不采信。保留全部 T-2902 正向目标（ATR 重试跨 run 场景不受影响）。补 2 个负向单测：同 run prior-round 证据不触发 gating。

### 🟡 修正
1. **证据读取捕获集放宽**：声明捕获 (ValidationError, ConfigError, JSONDecodeError, OSError) 有漏洞——损坏文件抛 UnicodeDecodeError（ValueError 子类）、JSON 为 list 时 payload.get 抛 AttributeError，均逃出导致崩溃而非 validation_failure。改为捕获 Exception（best-effort 语义），补 malformed-UTF8 归档测试。
2. **P1 notes=MEDIUM 跨 run 自认证链**：run-1 noop 报告（notes "already done"）在 run-2 被归档为证据 → 零改动任务二次 noop 即 done。改法：notes 证据需与 P4（输出文件/commit）佐证共同命中才计，或文档化接受。
3. **kill-switch 操作性表述修正**：bridge dispatch_atr 的 cmd 固定硬编码（bridge.py:706-731），operator 无法经 ATR 注入 flag；即时降级=git revert C1。README/计划中不得写"flag/env 即时降级"。

### 可选（不阻塞）
- D5 长排队任务窗口放大：有效窗口上限（window_base=max(created_at, started_at-24h)）或证据排序优先 task-scoped loop_archive——ACCEPTED with justification 即可。
- 锚点行号以执行时实读为准（个别漂移，如 _archive_rounds_for_task 实际 :9588）。

## Execution Log

### Post-Execution Verification Log (2026-08-20, Task Executor)

| ID | Command | Result | Actual Output |
|----|---------|--------|---------------|
| V1 | `uv run --group dev pytest -m "not e2e" -q` | ✅ PASS（偏差见下） | 628 passed, 1 skipped, 3 deselected, 0 failed。计划基线为 615 passed + 2 预存在失败（test_shows_context_file_stats、test_task_card_in_resettable_files）；本环境两测试当前均通过（执行时单独验证 2 passed）——环境漂移导致，非回归，0 新增失败 |
| V2 | `uv run ruff check src/loop_kit tests` | ✅ PASS | All checks passed (0 errors) |
| V3 | `uv run python -m py_compile src/loop_kit/_core.py src/loop_kit/orchestrator.py` | ✅ PASS | exit 0 |
| V4 | `uv run --group dev pytest tests/test_orchestrator.py -q -k "no_change or noop or evidence"` | ✅ PASS | 34 passed（21 既有 + 13 新增） |
| V5 | `.venv/bin/pytest tests/test_bridge_partial_success.py -q` | ✅ PASS | 26 passed（21 既有 + 5 新增） |
| V6 | `.venv/bin/python -m py_compile src/auto_task/bridge.py` | ✅ PASS | exit 0 |

- D1（Deferred）：⏸ PENDING RESTART — 发现命令 `ps aux | grep -i auto_task`；执行时 ATR daemon 未运行（P1 probe 无输出），重启后 bridge 新逻辑生效。
- P1（Probe）：✅ 执行 — ATR 进程当前不存在（无匹配行）。
- M1/M2（Manual）：⚠️ PENDING MANUAL — 需人工抽查真实 ATR no-change 场景的 summary.json `round_details[].no_change_evidence`，及 README 渲染。

### 执行偏差清单
1. **CT 合入**（计划内 CT 审阅合入节，均已落实）：🔴 证据限定跨 run（`run_id != 当前 run_id`，P1/P2/P3 一致）；新增 2 个同 run prior-round 负向单测。🟡1 证据读取 `except Exception` + malformed-UTF8 单测。🟡2 notes 不自认证（强命中优先返回，notes-only 归 None）+ 负向单测；计划原 notes=MEDIUM 成功路径测试改为负向。🟡3 README kill-switch 表述修正（ATR 固定 cmd 不可注入 flag，即时回滚=git revert）。
2. **P3 跨 run 判定依赖 round_details 携带 run_id**：noop handler 与 reviewer round_detail 各新增一行 `"run_id": run_id`（reviewer 处为 CT 🔴 落实所必需的最小扩展，超出计划 Task 1.1 原始修改清单，属于 CT 合入衍生改动）。
3. **V1 基线漂移**：计划基线 615 passed + 2 预存在失败 → 实际 628 passed + 0 失败（2 个预存在失败测试在当前环境通过，单独运行验证 2 passed）。
4. **编辑工具格式器污染**：edit 工具 LSP 集成对 `_core.py` 触发 ruff format 全文件重排（本仓库 HEAD 本身非 ruff-format clean），已 `git checkout` 回退并改用脚本重放补丁，最终 diff 16 hunks 全部落在声明修改点（C1 范围内无杂散 hunk）。

### 提交记录
| Commit | 仓库 | 文件 |
|--------|------|------|
| 4dfc67a | agent-task-runner | src/loop_kit/_core.py, tests/test_orchestrator.py |
| 5eebc85 | agent-task-runner | README.md |
| 99d7d0c | project_management | src/auto_task/bridge.py, tests/test_bridge_partial_success.py |
