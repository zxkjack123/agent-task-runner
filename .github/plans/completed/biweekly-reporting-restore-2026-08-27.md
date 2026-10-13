---
title: "pB-Fuel-Cycle 双周汇报自动化恢复 + 通用定期汇报模式（T-A/T-C/T-D）"
date: 2026-08-27
mode: plan
scope_mode: HOLD
revision: 1
context:
  git_commit: "执行时重测（计划生成时 HEAD=a3fb323，ATR 仓库工作区干净）"
  pm_repo: /home/gw/opt/project_management
  atr_repo: /home/gw/opt/agent-task-runner
  next_meeting: 2026-09-02 (Wed) 14:00 Asia/Shanghai
  exec_window: 2026-08-31 / 2026-09-01
---

# 计划：pB-Fuel-Cycle 双周汇报自动化恢复

## 1. 背景与目标

ATR 已迁移至 P8（user-ThinkStation-P8）。原 #2002 双周汇报自动化任务（首次 due 2026-08-04）从未正式执行：队列 #161（07-22 首跑）空转完成，仅生成了模板目录，无实质产物。现恢复该自动化，并将"定期汇报"沉淀为可推广模式。

**目标**：
1. 放开 ATR in_scope 限制（T-A）：当前用户可写的绝对路径一律允许，去除 repo-root 白名单。
2. 实现 biweekly_report 定时调度器（T-C）：每两周会议前 2 天自动建卡入队 → ATR 执行 → NAS 产出摘要 + Beamer。
3. 观察 2026-09-02 会议前的首次真实执行（T-D）。

**非目标（HOLD 模式，不扩展）**：
- 不实现 N 个项目的批量推广（仅参数化预留）
- 不改 ATR 调度层架构（不新增"到点执行"通用调度器；复用既有 pm-cron 设施）
- 不修改 #2002 任务卡的内容模板（4 步流程保持原样）

## 2. 已核实事实基线（2026-08-27 实测）

| # | 事实 | 锚点/证据 | 状态 |
|---|------|----------|------|
| F1 | `_is_safe_scope_pattern` 拒绝所有绝对路径 | `src/loop_kit/_core.py:5454-5458` | 核实 ✓ |
| F2 | `_build_task_packet` 双重限制（`ROOT.glob` + `_is_path_under_root`） | `_core.py:5468-5531`（glob 在 :5483，fallback 在 :5518-5531） | 核实 ✓ |
| F3 | `ROOT = Path.cwd()`（import 时求值，非仓库路径常量） | `_core.py:337` | 核实 ✓ |
| F4 | enqueue_task 实现位于 bridge 而非 server.py | `src/auto_task/bridge.py:1954`；`build_task_card` @ :265；`server.py:3983/4303` 仅调用点 | 修正用户锚点（原述 server.py:3695） |
| F5 | PM 建卡(含 auto 标签)→ 立即 enqueue 入队 | `mcp_server/server.py` create/update 路径均调 `build_task_card`+`enqueue_task` | 核实 ✓ |
| F6 | dispatcher `_resolve_project_dir` 优先级：notes `workspace:` 指令 > project_locations 中 git repo > ATR 回退 | `scripts/auto_task_dispatcher.py:265-318` | 核实 ✓ |
| F7 | **T-B 已完成**：proj=128 已登记 `/home/gw/opt/pBurn`（kind=source） | `project_locations` id=321 | 核实 ✓（本计划仅记录，不重做） |
| F8 | 日程 1476707 存在：`FREQ=WEEKLY;INTERVAL=2;BYDAY=WE;UNTIL=20270331T060000Z`，下次 09-02 14:00 | `data/pm.sqlite` events 表 | 核实 ✓ |
| F9 | **PM `schedule_list` MCP 不展开 rrule 事件**（09-01~09-30 查询无 1476707）→ 动态读会议日必须 SQL 直读 events 表 + rrule 解析 | 实测 | 关键设计约束 |
| F10 | cron_runner 注册机制 = argparse `choices` 列表（39 个 job）+ `_job_spec()` if 分支 | `scripts/cron_runner.py:916-962`（choices）、`:279` 起（分支） | 核实 ✓（用户述 ~30 个，实际 39） |
| F11 | pm-cron@.service 为 generic runner：`cron_runner.py run --job %i`，WorkingDirectory=PM 仓库 | `~/.config/systemd/user/pm-cron@.service` | 核实 ✓ |
| F12 | timer 模板格式 | `~/.config/systemd/user/pm-cron-zombie-scan.timer` | 核实 ✓ |
| F13 | PM venv 有 dateutil 2.9.0（rrule 解析可用） | `.venv/bin/python -c "import dateutil"` | 核实 ✓ |
| F14 | feishu 通知可用：`send_feishu_text` | `src/feishu_push.py:101` | 核实 ✓ |
| F15 | #2002 模板完整（4 步流程+验收+输出路径）| PM 任务 2002 notes | 核实 ✓ |
| F16 | 现有测试 `test_ignores_unsafe_in_scope_patterns` 断言 `/etc/passwd` 被忽略 | `tests/test_orchestrator.py:11144-11162` | 核实 ✓（新语义下 /etc/passwd 对 gw 不可写 → 结果不变，但测试需改造以脱离运行用户依赖） |
| F17 | 现有测试 `test_ignores_symlinked_match_outside_repo_root` / `test_literal_symlink_path_does_not_fallback_to_resolved_target` 针对相对 glob 语义 | `tests/test_orchestrator.py:11190-11228` | 核实 ✓（相对路径语义不变 → 无需改动，回归验证即可） |
| F18 | tasks 表 INSERT 列结构 | `mcp_server/server.py:3911-3936` | 核实 ✓ |
| F19 | ATR 测试基线：`uv run --group dev pytest`（e2e 默认排除） | repo `AGENTS.md` | 核实 ✓ |

## 3. 关键设计决策（Trade-off 可见）

### D1 — T-A 绝对路径判据 = 用户可写性（os.access W_OK）
```
DECISION: 绝对路径 pattern 允许 ⇔ os.access(file, W_OK)；文件不存在时对最近已存在父目录判 W_OK
ALTERNATIVES: (a) 完全无检查放开 — 危险，否决；(b) 白名单特定根 — 用户明确拒绝白名单
RATIONALE: 直接实现用户要求"当前用户（gw）有写权限的路径都允许"
RISK: root 环境下测试中 /etc/passwd 可写 → F16 测试必须改造为不依赖运行用户的构造（见 T1.3）
```

### D2 — T-A 绝对路径在 target_files 中保持绝对路径字符串
```
DECISION: 绝对路径命中后 target_files 存 as_posix() 绝对路径；相对路径逻辑（glob+fallback+symlink 检查）原样保留
ALTERNATIVES: 转为相对路径 — ROOT 外路径无法相对化，否决
RATIONALE: pathlib 语义 `ROOT / <absolute>` == `<absolute>`，`_function_index`（:5578）无需改动
RISK: 下游 target_files 消费者若假设相对路径会出错 → T1.4 强制 grep 核实全部消费者
```

### D3 — T-C 建卡 = 脚本直连 SQLite + 确定性 card 构造（不依赖 LLM）
```
DECISION: biweekly_report.py 直接 INSERT tasks + 内嵌确定性 card 构造器 + bridge.enqueue_task
ALTERNATIVES: (a) 调 PM MCP task_create — 跨进程、env 依赖复杂；(b) bridge.build_task_card LLM 路径 — cron 不应依赖 LLM 可用性
RATIONALE: 与 server.py create 路径同源 API（ensure_auto_task_table/build_task_card/enqueue_task），确定性、可测试
RISK: tasks 表 schema 变更破坏脚本 → 验收含 schema 断言（S1.2）
```

### D4 — T-C 触发 = timer 每天 08:30 + job 内判执行日
```
DECISION: OnCalendar=*-*-* 08:30:00 每日触发；job 内读 events 表 rrule 算下次会议日，today == 会议日-2 才建卡
ALTERNATIVES: OnCalendar=Mon 08:30 + 周奇偶硬编码 — 会议改期/取消即失配
RATIONALE: 执行日随会议日程动态漂移，满足"避免硬编码日期"要求
RISK: rrule 解析错误 → 漏触发；验收含 --print-next 模式人工核对（S1.4）
```

### D5 — T-C 通知 = 尽力而为 feishu 文本（失败不阻断）
```
DECISION: 建卡后调 src/feishu_push.send_feishu_text，异常捕获 → 记录日志 → 仍 exit 0
ALTERNATIVES: pm_notify MCP（跨进程）
RATIONALE: 同进程、零新增依赖；通知失败不应导致 cron job 判负
RISK: env 缺失静默降级 → 日志必须打印 notif 失败原因
```

## 4. 执行计划

### Phase 0 — 状态记录（无需执行）
T-B（`pm_project_add_location(proj=128, /home/gw/opt/pBurn, kind=source)`）已于计划生成前由 PM Coordinator 完成（F7）。执行者无需操作。

### Phase 1 — T-A：放开 ATR in_scope 限制（ATR 仓库 /home/gw/opt/agent-task-runner）

- **基线漂移重检**（必做）：`git rev-parse HEAD` + `git status --porcelain`；核对 `_core.py` 三个锚点行号（5454/5461/5468）是否漂移，漂移则先更新锚点再动手。
- **执行者**：Worker AI（ATR auto 任务 T-A 卡片本身经 ATR 执行）
- **修改文件数**：2（`src/loop_kit/_core.py` + `tests/test_orchestrator.py`）

#### Task 1.1: 修改 `_is_safe_scope_pattern`
- **目标**：绝对路径判据从"一律拒绝"改为"用户可写则允许"；相对路径语义不变。
- **文件**：`src/loop_kit/_core.py`（当前 :5454-5458）
- **MODIFY_SPEC**：
  - 新逻辑（伪代码级）：
    ```python
    def _is_safe_scope_pattern(pattern: str) -> bool:
        candidate = Path(pattern)
        if candidate.is_absolute():
            # 判据：文件本身可写；不存在则对最近已存在父目录判可写
            probe = candidate if candidate.exists() else _nearest_existing_parent(candidate)
            return probe is not None and os.access(probe, os.W_OK)
        return all(part != ".." for part in candidate.parts)
    ```
  - 新增私有 helper `_nearest_existing_parent(p: Path) -> Path | None`：沿 `p.parent` 上溯，返回第一个 `exists()` 的父目录；到根仍不存在返回 None。放在 `_is_safe_scope_pattern` 上方。
  - 确认 `os` 已在 `_core.py` 顶部 import（若无则补）。
- **修改边界**：不得触碰 `_is_path_under_root`（:5461，保留给相对路径分支用）；不得修改任何其他函数。
- **验收**：
  - ✅ `python -c "from loop_kit._core import _is_safe_scope_pattern; print(_is_safe_scope_pattern('/tmp'), _is_safe_scope_pattern('/root/x'), _is_safe_scope_pattern('../x'))"` → `True False False`（/tmp 对 gw 可写，/root 不可写）

#### Task 1.2: 修改 `_build_task_packet` 循环体
- **目标**：绝对路径 pattern 走直接路径解析分支；相对路径逻辑原样保留。
- **文件**：`src/loop_kit/_core.py`（当前 :5468-5531 的 for 循环内）
- **MODIFY_SPEC**：在 `if not _is_safe_scope_pattern(pattern): ... continue`（:5479-5481）之后、`try: glob_matched = ...`（:5482-5483）之前，插入：
  ```python
  # Absolute path patterns: direct resolution (writability already checked).
  if Path(pattern).is_absolute():
      try:
          p = Path(pattern)
          if p.is_file():
              resolved = p.resolve()
              matched_path = resolved.as_posix()  # keep absolute in target_files
              if matched_path not in seen_target_files:
                  target_files.append(matched_path)
                  seen_target_files.add(matched_path)
      except (OSError, RuntimeError):
          _log(f"Ignoring unreadable absolute in_scope path: {item!r}")
      continue
  ```
- **语义约定**：
  - 绝对路径 glob（如 `/home/gw/opt/pBurn/**/*.py`）→ `p.is_file()` 为 False → 整项忽略。**v1 不支持绝对 glob**，只支持精确文件路径（在计划中显式声明，不留给执行者猜测）。
  - 相对路径（含 glob、symlink 检查、`_is_path_under_root`）分支一字不改。
- **修改边界**：不得改动 :5533 起的 `target_symbols`/`constraints`/`commands_to_run` 逻辑；不得删除 F17 依赖的 symlink 逻辑。
- **验收**：
  - ✅ 精确绝对路径命中：in_scope=[tmp 下某可写文件绝对路径] → `_build_task_packet(...)["target_files"]` 含该绝对路径字符串
  - ✅ 不可写绝对路径忽略：in_scope=[/root/x] → 不含
  - ✅ 相对路径行为回归：现有 8 个 `_build_task_packet` 测试（:11130-11310）全绿

#### Task 1.3: 补测试
- **文件**：`tests/test_orchestrator.py`（在 `test_ignores_unsafe_in_scope_patterns` 类附近，:11144 起）
- **MODIFY_SPEC**：
  1. **改造** `test_ignores_unsafe_in_scope_patterns`：将 `/etc/passwd` 替换为运行用户无关的不可写构造——`tmp_path` 下建子目录 `locked/`，`chmod 0o555`，in_scope 用 `locked/secret.txt` 的绝对路径（父目录不可写）→ 断言被忽略。测试结尾 `chmod 0o755` 恢复（避免 tmp_path 清理失败）。`../secret.txt` 用例保留（相对路径 `..` 拒绝语义）。
  2. **新增** `test_absolute_in_scope_writable_file_included`：tmp_path 建文件（可写），in_scope=[str(abs_path)] → 断言 `packet["target_files"] == [abs_path]`。
  3. **新增** `test_absolute_in_scope_unwritable_ignored`：用 `monkeypatch.setattr(orchestrator.os, "access", lambda p, m: False)` 强制不可写 → 断言被忽略（替代方案：指向 `/proc/1/xxx` 等天然不可写路径，二选一，执行者按稳定性自选并在注释说明）。
  4. **新增** `test_absolute_glob_ignored`：in_scope=[f"{tmp_path}/**/*.py"] → 断言 target_files 不含（固化 v1 不支持绝对 glob 的语义）。
- **验收**：`uv run --group dev pytest tests/test_orchestrator.py -k "in_scope"` 全绿。

#### Task 1.4: 下游消费者核实 + 全量验证 + 提交
- **目标**：确认 target_files 的绝对路径形式不破坏下游。
- **MODIFY_SPEC**：
  1. `grep -n "target_files" src/loop_kit/*.py | grep -v "def _build_task_packet"` 列出全部消费者，逐个确认：`_function_index`（:5534，`ROOT / filepath`，绝对路径安全）；prompt 渲染（`_render_task_card_section` 渲染的是原始 in_scope，不消费 target_files）；若有 `git diff -- <file>` 类调用需确认绝对路径参数可行。发现假设相对路径的消费者 → 立即上报并暂停（不得静默绕过）。
  2. 验证命令（repo AGENTS.md 约定）：
     - `uv run ruff check src/loop_kit tests` → exit 0，0 error
     - `uv run python -m py_compile src/loop_kit/orchestrator.py` → exit 0
     - `uv run --group dev pytest` → 全绿（基线 615 passed / 0 failed，本任务新增 4 测试后应为 619）
  3. 提交：单一 commit，`git diff --stat` 只含 2 个声明文件；message 遵循 commit 规范（如 `feat(loop): allow absolute in_scope paths when user-writable (#XXXX)`，含 `#` 引用 PM 任务号以触发自动同步）。
- **验收**：✅ 验证三命令全绿；✅ commit 干净。

**Phase 1 风险与回滚**：
- 风险：F16 改造中 chmod 影响共享 tmp_path 其他用例 → 用例内 try/finally 恢复权限。
- 回滚：`git revert <commit>`；测试与源码同 commit，无中间态。

---


### Phase 2 — T-C：biweekly_report 调度器（PM 仓库 /home/gw/opt/project_management）

- **依赖**：Phase 1 完成（任务卡 in_scope 将含 NAS 绝对产出路径，T-A 放开后才不会被 `_build_task_packet` 过滤）。
- **基线漂移重检**（必做）：`git -C /home/gw/opt/project_management rev-parse HEAD` + `git status --porcelain`；核对 cron_runner.py 的 `main()` choices 列表与 `_job_spec()` 起始行号（916-962 / 279）。
- **执行者**：Worker AI（经 ATR 或以普通任务执行）
- **修改文件数**：3（`scripts/cron_runner.py`、新建 `scripts/biweekly_report.py`、新建 `~/.config/systemd/user/pm-cron-biweekly_report.timer`）

#### Task 2.1: 新建 scripts/biweekly_report.py（核心脚本）
- **目标**：读配置 → 算执行日 → 建带日期 auto 任务卡入队 → feishu 通知。
- **MODIFY_SPEC**（结构，不写成品代码）：
  - **配置（D3 参数化预留）**：模块级 `CONFIG` dict，v1 单项目，字段：
    ```python
    CONFIG = {
        "project_id": 128,
        "project_code": "PB-FUEL-CYCLE",
        "meeting_event_id": 1476707,           # events 表主键；动态读 rrule
        "lead_days": 2,                         # 执行日 = 会议日 - 2
        "output_dir": "/mnt/nas/ComputeData/pB-Fuel-Cycle/docs/project/biweekly",
        "workspace": "/home/gw/opt/pBurn",      # dispatcher 优先级1 双保险
        "task_tags": ["auto", "biweekly", "reporting", "PB-FUEL-CYCLE"],
        "notify": True,
        "title_prefix": "[Biweekly] pB-Fuel-Cycle 项目进展摘要 + Beamer Slide 生成",
    }
    ```
    （推广到其他项目 = 复制此 dict 或改为按 project_code 多配置表，本期不实现）
  - **执行日判定（F9 约束）**：
    1. `sqlite3.connect(ROOT/"data"/"pm.sqlite")`，`SELECT rrule, event_timezone FROM events WHERE id=?`（1476707）
    2. `dateutil.rrule.rrulestr(rrule)` 展开，用 `datetime.now(tz=ZoneInfo(event_timezone or "Asia/Shanghai"))` 取下一次 occurrence（> now）
    3. `exec_date = next_occurrence.date() - timedelta(days=lead_days)`
    4. `today != exec_date` → 打印 `SKIP: next meeting=..., exec_date=...` 并 **exit 0**（幂等，F10 cron 每日触发）
  - **建卡（D3）**：
    1. 幂等检查：`SELECT COUNT(*) FROM tasks WHERE title LIKE ? AND due_local = ? AND status IN ('todo','doing')`（前缀+exec_date）→ 已存在则打印 SKIP 并 exit 0
    2. `INSERT INTO tasks`（列结构 F18：title, status='todo', priority=2, due_local=exec_date.isoformat(), tags=','.join(CONFIG["task_tags"]), notes, project_id, created_at/updated_at=now），`last_insert_rowid()` 取 task_id
    3. **内嵌确定性 card 构造器**（不调 bridge.build_task_card 的 LLM 路径）：
       - `in_scope`：**只放路径**——`[CONFIG["output_dir"], CONFIG["workspace"]]`（绝对路径；bridge.py:371 教训：in_scope 严禁叙事字符串，防 ENAMETOOLONG）。产出目录可能不存在 → 仍是合法绝对路径（T-A 的 `_nearest_existing_parent` 判据覆盖）
       - `goal`：固定文案，引用"生成 pB-Fuel-Cycle 双周进展摘要 + Beamer slide"
       - `constraints`：含 `截止: <exec_date>`、`产出目录: <output_dir>`、`workspace: <workspace>`、`只读约束: 不得修改 pBurn 仓库代码，git log 仅用于读取摘要`
       - `acceptance_criteria`：复用 #2002 验收条件（F15）：`docs/project/biweekly/` 下存在 `biweekly_summary_<date>.md` 与 `biweekly_slides_<date>.tex`（含编译 PDF）、覆盖近 2 周 PM 任务状态变化、Beamer 可编译
    4. `from src.auto_task.bridge import enqueue_task, ensure_auto_task_table`（F4）：`ensure_auto_task_table(conn)` → `qid = enqueue_task(conn, task_id, card)`；qid 为 None（重复）→ 幂等 SKIP
    5. 提交 conn；打印 `ENQUEUED task_id=..., qid=...`
  - **CLI**：`--dry-run`（只打印执行日判定+卡片预览，不写库；cron degraded 模式用）；`--print-next`（打印下次会议日+执行日，供 S1.4 人工核对）；默认无参=真实执行。
  - **通知（D5）**：enqueue 成功后 `from src.feishu_push import send_feishu_text` 发送"已建卡 T-<id>，exec_date=..."；异常捕获 → `print("NOTIFY-FAILED:", e)`，不影响 exit 0。PM venv 运行时 `src` 可导入（WorkingDirectory=PM 仓库，F11）。
  - **修改边界**：不得修改 `src/auto_task/bridge.py`（只 import 既有公开函数）；不得写任何 ATR 仓库文件。
- **验收**：
  - ✅ `cd /home/gw/opt/project_management && .venv/bin/python scripts/biweekly_report.py --print-next` → 打印 meeting=2026-09-02, exec=2026-08-31
  - ✅ 同上 `--dry-run` → 打印完整卡片预览且 `tasks`/`auto_task_queue` 表无新行

#### Task 2.2: 注册 cron job
- **文件**：`/home/gw/opt/project_management/scripts/cron_runner.py`
- **MODIFY_SPEC**（两处）：
  1. `main()` 的 `--job` choices 列表（当前 :928-962 尾部）追加 `"biweekly_report",`（保持字母序插入在 `backup_rotate` 之后或列表尾，执行者按现状排版自选并保持一致）。
  2. `_job_spec()`（:279 起）在任一 `if name == ...` 分支后追加：
     ```python
     if name == "biweekly_report":
         argv = [str(PY), str(ROOT / "scripts" / "biweekly_report.py")]
         if degraded:  # 连续失败≥3 次降级为 dry-run（D5 同级防护）
             argv.append("--dry-run")
         out_files = []
         return JobSpec(name, argv, out_files, apply_effect=False, env=env)
     ```
- **修改边界**：不得改动 `_job_spec` 其它分支与 `JobSpec` 定义。
- **验收**：
  - ✅ `.venv/bin/python scripts/cron_runner.py run --job biweekly_report` 能被 argparse 接受（不报 invalid choice）；当日非执行日 → exit 0 + SKIP 日志
  - ✅ 临时改本机日期环境变量不可行时，用 `--dry-run` 经 `run_job` 全链路验证 argv 渲染（日志出现 dry-run 输出）

#### Task 2.3: 新增 systemd user timer
- **文件**：`~/.config/systemd/user/pm-cron-biweekly_report.timer`（新建；F12 模板）
- **MODIFY_SPEC**（全文照此写入）：
  ```ini
  [Unit]
  Description=Biweekly project report card creation at 08:30

  [Timer]
  OnCalendar=*-*-* 08:30:00
  Persistent=true
  Unit=pm-cron@biweekly_report.service

  [Install]
  WantedBy=timers.target
  ```
  （D4：每日触发，执行日判定在 job 内）
- **激活命令**（顺序执行）：
  ```bash
  systemctl --user daemon-reload
  systemctl --user enable --now pm-cron-biweekly_report.timer
  systemctl --user list-timers pm-cron-biweekly_report.timer
  ```
- **验收**：
  - ✅ `list-timers` 显示 NEXT 为下一个 08:30，UNIT=pm-cron@biweekly_report.service
  - ✅ `systemctl --user is-enabled pm-cron-biweekly_report.timer` → enabled

#### Task 2.4: 真实入队 dry-run 验证 + 提交
- **MODIFY_SPEC**：
  1. 选一个非执行日（或临时 `--print-next` 确认 08-31 前任意日），执行 `.venv/bin/python scripts/biweekly_report.py --dry-run` → 确认 preview 正确 → 再执行真实模式前**必须**人工确认：`sqlite3 data/pm.sqlite "SELECT COUNT(*) FROM auto_task_queue"` 前后差值 +1，且新增行 task_card_json 含 `in_scope` 两绝对路径、tags 含 auto。确认后**立即清理**：`DELETE FROM auto_task_queue WHERE task_id=<id>` + `DELETE FROM tasks WHERE id=<id>`（防 09-02 会前误触发重复执行；若恰好是执行日则保留作为真实首跑，改记为 T-D 观察对象）。
  2. PM 仓库提交：commit 仅含 `scripts/cron_runner.py` + `scripts/biweekly_report.py`；message 遵循 PM 仓库 commit 规范（含 `#` PM 任务号）。timer 文件在 `~/.config/systemd/user/`（非 git 仓库），无需提交，但在输出中报告完整路径（repo 约定：文件路径完整报告）。
- **验收**：✅ 入队→清理闭环完成且日志留痕；✅ commit 干净。

**Phase 2 风险与回滚**：
- 风险：tasks 表 schema 变更 → S1.2 验收已含断言，失败即停。
- 风险：rrule 时区（UNTIL 为 UTC 06:00）→ 统一转 Asia/Shanghai 比较，`--print-next` 人工核对一次。
- 回滚：`systemctl --user disable --now pm-cron-biweekly_report.timer` + 删除 timer 文件 + `git revert`；已入队条目 `DELETE FROM auto_task_queue WHERE task_id=...`。

---


### Phase 3 — T-D：观察首次真实执行（2026-08-31 ~ 09-01 窗口）

- **依赖**：Phase 1 + Phase 2 完成，且 2026-08-31 08:30 到来。
- **性质**：观察任务，非代码修改。执行者是用户本人（或 Plan Architect 回访），不在 ATR 中派发。

#### Task 3.1: 观察链
- **预期链路**：`08-31 08:30 timer` → `cron_runner.py run --job biweekly_report` → 判定 exec_date=08-31 命中 → INSERT tasks + enqueue → `auto_task_dispatcher`（每 5 分钟）扫描 → `dispatch_atr` 解析 project_dir（F6 优先级 2 命中 pBurn；notes workspace 指令双保险）→ `loop_kit run` worker+reviewer 执行 → NAS 产物。
- **观察点**（用户手动）：
  1. `journalctl --user -u pm-cron@biweekly_report.service --since "2026-08-31 08:28"` → 见 `ENQUEUED task_id=...`
  2. `sqlite3 /home/gw/opt/project_management/data/pm.sqlite "SELECT task_id, task_uuid, iteration FROM auto_task_queue ORDER BY id DESC LIMIT 3"`
  3. ATR 日志（`.loop/runs/T-<id>-*/` 或 ATR 仓库 logs）→ work_report/review_report 非空（对比 #2002 的 #161 空转教训）
  4. NAS：`ls -la /mnt/nas/ComputeData/pB-Fuel-Cycle/docs/project/biweekly/` → `biweekly_summary_2026-08-31.md`（或 09-01）与 `biweekly_slides_*.tex` + PDF
  5. 飞书：收到建卡通知；ATR 完成通知是否触发（观察既有链路，作为后续改进输入）
- **验收**：✅ 上述 5 点逐条记录；任何一步失败 → 立即 `cd /home/gw/opt/project_management && .venv/bin/python scripts/biweekly_report.py` 手动重跑建卡，或按 Phase 2 回滚清理后重建；确保 09-02 14:00 会议前拿到产物。

## 5. Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|-----------|
| W1 | T-A（Phase 1 全部 1.1-1.4 顺序执行） | T-A | —（T-B 已在 Phase 0 记录为已完成） |
| W2 | T-C（Phase 2 全部 2.1-2.4 顺序执行） | T-C | W1（T-A 完成：任务卡 in_scope 绝对路径才生效） |
| W3 | T-D（观察，无代码） | — | W2 + 日历窗口 08-31 |

- **顺序理由**：T-C 生成的任务卡 `in_scope` 含绝对路径（NAS 产出目录）。若 T-C 先于 T-A 完成，卡被 `_build_task_packet` 过滤 → worker 拿不到产出路径 → 空转（复现 #161 教训）。因此 T-A 严格先行。
- **可并行性**：T-A 仅改 ATR 仓库、T-C 仅改 PM 仓库，技术上可并行。但 T-C 的卡在 T-A 部署前入队有真实风险，故**不并行**——这是有意的顺序化决策（R3 审查确认）。
- **失败策略**：T-A 失败 → revert 后重做（无下游依赖风险）；T-C 失败 → timer disable + revert，不影响 ATR；T-D 失败 → 手动兜底（3.1 末）。

## 6. Post-Execution Verification

### Automated Verification（执行者自动执行）
| ID | 描述 | 命令 | 期望 |
|----|------|------|------|
| V1 | ATR lint+compile+pytest | `uv run ruff check src/loop_kit tests && uv run python -m py_compile src/loop_kit/orchestrator.py && uv run --group dev pytest`（workdir=ATR 仓库） | exit 0，pytest 全绿（≥619） |
| V2 | cron job 注册有效 | `.venv/bin/python scripts/cron_runner.py run --job biweekly_report --timeout 120`（workdir=PM 仓库；非执行日） | exit 0，输出含 SKIP 或 dry-run 预览 |
| V3 | timer 状态 | `systemctl --user is-enabled pm-cron-biweekly_report.timer && systemctl --user list-timers pm-cron-biweekly_report.timer` | enabled；NEXT 为下一 08:30 |
| V4 | T-A 语义自检 | `python -c "from loop_kit._core import _is_safe_scope_pattern as f; assert f('/tmp'); assert not f('/root/x'); assert not f('../x')"`（workdir=ATR 仓库） | exit 0 |

### Deferred (needs restart / deployment)
- [ ] D1: `systemctl --user daemon-reload` 已在 T2.3 执行；无其它服务重启需求。

### Probe (best-effort, run if available)
- [ ] P1: `ls /mnt/nas/ComputeData/pB-Fuel-Cycle/docs/project/biweekly/` → NAS 挂载可达（T-D 前置探针，08-31 前建议先探一次）

### Manual（真正需要人工判断）
- [ ] M1: `--print-next` 输出人工核对（会议 09-02 → exec 08-31）
- [ ] M2: T-D 五观察点逐条确认（Phase 3 Task 3.1）

## 7. 风险与回滚汇总

| 风险 | 影响 | 缓解 / 回滚 |
|------|------|------------|
| R1 in_scope 放开安全面扩大（worker 可写任意 gw 可写路径） | 中 | 任务卡仍是受控入口（PM 建卡流程）；W_OK 判据 + 相对路径语义不变；D1 已记录 trade-off。回滚：`git revert` |
| R2 target_files 绝对路径下游假设 | 中 | T1.4 强制 grep 核实全部消费者；发现即停 |
| R3 测试运行用户为 root（/etc/passwd 可写） | 低 | F16 改造脱离运行用户（T1.3） |
| R4 rrule 解析/时区错误 → 漏触发 | 高 | `--print-next` 人工核对（M1）；events 表直读（F9 已确认 MCP 不可用）；漏触发则手动跑脚本兜底 |
| R5 tasks 表 schema 变更 | 中 | 脚本启动时 `PRAGMA table_info(tasks)` 断言关键列存在（S1.2 语义） |
| R6 NAS 未挂载 → worker 产出失败 | 高 | 任务卡 acceptance 含 NAS 可达性前置（PRECONDITION-FAILED 哨兵语义）；P1 提前探针 |
| R7 09-02 会议前窗口错失 | 高 | T-D 明确手动兜底路径；T2.4 清理残留防重复 |
| 回滚总则 | — | T-A: `git revert <commit>`（单 commit 含源码+测试）；T-C: `systemctl --user disable --now pm-cron-biweekly_report.timer` + 删 timer 文件 + `git revert` + `DELETE FROM auto_task_queue WHERE task_id=<残留>` |

## 8. 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（4 任务/依赖/验收二元化/每任务≤3 文件） | 1（原方案 T-C 建卡依赖 LLM 路径，重构为确定性 card） | 1 | 0 |
| R1.5 | 外部引用事实核查（18 项锚点逐一实测：F1-F19） | 3（enqueue 锚点 3695→bridge.py:1954；job 数 30→39；schedule_list 不展开 rrule） | 3 | 0 |
| R2 | 可执行性（验证命令干跑、测试改造方案、cron 链路） | 1（test 改造需脱离运行用户，chmod/monkeypatch 方案落地） | 1 | 0 |
| R2.8 | LLM 可执行性（逐字段消除下游猜测：绝对 glob 语义显式声明、timer 全文、card 字段约束） | 2（绝对 glob v1 语义未声明；in_scope 叙事字符串风险未引用 bridge.py:371 教训） | 2 | 0 |
| R3 | 风险与边缘（跨任务一致性、回滚、时区、窗口期） | 0 | 0 | 0 |
| **终止** | **[T1] — 全部审查轮次 issue 清零** | | | **0** |

## 9. 修订记录
- rev 1 (2026-08-27): 初始计划。Scope Mode=HOLD。T-B 已完成为 Phase 0 状态记录，T-A/T-C/T-D 全量 MODIFY_SPEC。

---

## 10. 执行进度（2026-08-27 追加）

以下为 2026-08-27 对计划生成的 ATR 闭环任务的实际执行状态快照（由文档维护环节记录，不含计划执行期的实时日志）。

### 10.1 已完成并验收

| 任务 | 对应计划节点 | 内容 | Commit(s) | 验收状态 |
|------|-------------|------|-----------|----------|
| **T-A**（= PM #3080） | Phase 1（Task 1.1-1.4） | loop_kit 放开已存在的绝对 in_scope 路径：`_is_safe_scope_pattern` 由"一律拒绝绝对路径"改为"用户可写则允许"，`_build_task_packet` 增加绝对路径直接解析分支，测试改造/新增（T1.3）。 | `972f4a6`（ATR 仓库） | ✅ 已验收 |
| **T-3085**（后续补充） | Phase 1 语义扩展 | T-A 后补齐"文件本身不存在"场景：当绝对 in_scope 命中的文件不存在时，对其**最近已存在祖先目录**判可写，写权限满足即允许（与 D1/Task 1.1 中 `_nearest_existing_parent` 设计一致）。 | `27b4929` + `39dcca3`（ATR 仓库） | ✅ 已验收（`uv run --group dev pytest` = **637 passed**） |
| **T-3086**（后续补充） | —（Phase 2/3 之外的 dispatcher 修复） | dispatcher 陈旧 `summary.json` 竞态修复（`scripts/auto_task_dispatcher.py`）。 | `e8db4f4` + `92f3162`（project_management 仓库） | ✅ 已验收（23 passed） |
| **T-B**（= pBurn 登记） | Phase 0（状态记录） | proj=128 已登记 `/home/gw/opt/pBurn`（kind=source，`project_locations` id=321）。 | —（登记类，无 commit） | ✅ 已完成 |

> 注：T-3085 / T-3086 为 T-A 验收后由人工/PM 追加的闭环收尾任务，原计划的 Wave 表未将其单列；此处补记以确保进度一致。

### 10.2 语义修正说明

原计划基线（F1）表述为"`_is_safe_scope_pattern` **拒绝所有绝对路径**"——这是 T-A 执行前的事实基线。T-A 之后绝对路径语义已扩展为：

> **相对路径**：仓库内（`ROOT.glob` + `_is_path_under_root` 语义不变）。
> **绝对路径**：用户可写的已存在文件；**或文件不存在时其最近已存在祖先目录可写** 的新文件（`_nearest_existing_parent` 判据）。

`/etc/passwd` 等不可写路径仍被忽略（F16 语义在新判据下成立）。绝对 glob（如 `/home/gw/opt/pBurn/**/*.py`）v1 不支持、整项忽略（D2 / Task 1.2 语义约定不变）。

### 10.3 已完成并验收（本轮追加）

| 任务 | 对应计划节点 | 内容 | Commit(s) | 验收状态 |
|------|-------------|------|-----------|----------|
| **T-C**（= PM #3081） | Phase 2（Task 2.1-2.4） | `biweekly_report.py` 调度器（配置读入 → rrule 执行日判定 → 确定性建卡入队 → feishu 通知）+ cron job 注册 + systemd timer。交付：cron_runner 注册、`src/ops/biweekly_report.py`、`config/biweekly_report.json`、模板、systemd `pm-cron-biweekly_report.timer` 仓库副本 + `~/.config/systemd/user` 实装、测试（10 passed）。dry-run 验证会议解析（09-02 → 08-31）。timer 已启用，NEXT=08-31 08:30。 | `f2ff035` | ✅ 已完成并验收（2026-08-27） |

### 10.4 待观察（计划内剩余）

| 任务 | 对应计划节点 | 内容 | 状态 |
|------|-------------|------|------|
| **T-D**（= PM #3082） | Phase 3（Task 3.1） | 09-01 窗口观察首次真实执行（依赖 T-C 完成 + 日历窗口） | ✅ 已就绪：timer 将于 08-31 08:30 首次触发，观察窗口 08-31 / 09-01 |

### 10.5 实战经验补充：preflight workspace 指令机制

#3081 首轮被 dispatcher 拦截 → 追加 `workspace:` 指令后重派发成功。这实战验证了 F6 的 `_resolve_project_dir` 优先级：notes 中 `workspace:` 指令 > project_locations 中 git repo > ATR 回退。**结论**：任务卡 notes 中应始终携带 `workspace:` 指令作为 dispatcher 解析 project_dir 的确定性双保险（与 T2.1 的 D3 card 构造器设计一致）。

> **未归档原因**：T-D（首次真实执行观察）尚未触发完成，本计划文件保留在 `.github/plans/`，不归档至 `plans/completed/`。

---

> **归档说明（2026-10-13）**：T-D（PM #3082）已 done（T-A=#3080、T-C=#3081 亦 done，DB 实测），原"未归档原因"失效。本计划随台账卫生批次（#T-4397）移入 `.github/plans/completed/`；D1/P1/M1/M2 复选框保留历史原状，不再回填。
