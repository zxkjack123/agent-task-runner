# Plan: PM #3346 — dispatch-retries 耗尽后的最终放弃路径（_wait_for_role_result / 子进程等待修复）

- **计划文件**: `.github/plans/pm3346-dispatch-retries-final-abandonment-2026-09-05.md`
- **生成者**: Plan Architect（Rigid 模式）
- **生成日期**: 2026-09-05
- **context 快照**（生成时，执行时必须重测，禁止沿用）：`git rev-parse HEAD` = `02e3528b2f5c9b310d0cd4110848f3dd730dfc48`；测试基线 = 733 passed / 1 skipped / 3 deselected（task-fit 实测，70.9s）
- **Scope Mode**: HOLD（Bug 修复——严格保持范围不扩不缩；parent-death 检测属任务原文列明的范围内可选增强，纳入不视为扩范围）
- **Review Mode**: 无（初次制定）
- **修改文件白名单**: `src/loop_kit/_core.py` + `tests/test_orchestrator.py`（仅此两文件；详见各 task 修改边界）

---

## 背景与目标

- **问题/需求描述**：PM #3346。2026-09-04 清理了两个存活 18.6h 的孤儿进程（PID 3587569/3587579，为 #3263 会话中断遗留的 single-round 子进程，配置 `--dispatch-retries 2 --artifact-timeout 90 --timeout 0`）。理论上 retries 耗尽后应在分钟级放弃，实际长时间存活。
- **任务原文验收**：
  1. 重试耗尽后有明确终止路径（非无限等待），有测试证明
  2. 全量测试不回归（733 passed 基线）
  3. 若实现 parent-death 检测：父进程死亡后子进程在限定时间内退出
- **硬约束**：只改 agent-task-runner 仓；保持 #3155 repo 锁/dirty-tree fail-fast 与 #3263 watchdog/plan patch 行为不变；不回退测试基线。
- **非目标（不做什么）**：
  - 不改 `--dispatch-timeout 0=unlimited` 的文档化语义（有既有测试 `test_run_auto_dispatch_zero_timeout_is_unlimited` 锁定）
  - 不改 `dispatch.py` backend 注册、`file_bus.py` 锁、`session.py` 会话恢复、`exceptions.py` 异常层次
  - 不动 #3301（copilot-agents 仓，跨仓，与 #3300 跨目录规则冲突）

---

## CoT Stage 1：需求分解

```
REQUIREMENT: dispatch 重试耗尽后子进程必须最终放弃（不得无限等待）；可选 parent-death 检测。
CONSTRAINTS:
  - [硬] 只改 agent-task-runner 仓
  - [硬] #3155 dirty-tree fail-fast、#3263 session_deadline 检查点行为不变（C3）
  - [硬] 733 passed 测试基线不回退
  - [task-fit C1] 定位必须并列考察 _run_auto_dispatch 子进程等待（一号嫌疑）与 _wait_for_role_result（二号）
  - [task-fit C2] 24h _WAIT_SAFETY_CAP_SEC 的去留必须显式决策
  - [task-fit C4] stash@{0} 存在 → 执行期间禁 git stash pop/apply；plans/ 与 data/ 为 untracked 不得卷入提交
BOUNDARY (IN scope):
  - src/loop_kit/_core.py 内等待/重试函数：_wait_for_file / _wait_for_role_result / _run_auto_dispatch /
    _dispatch_with_artifact_fallback / _collect_streamed_process_output（后者的有界化是本次修复核心，属 _run_auto_dispatch 等待路径的一部分）
  - tests/test_orchestrator.py 对应测试
BOUNDARY (OUT of scope):
  - dispatch.py / file_bus.py / session.py / exceptions.py / orchestrator.py 门面
  - CLI 参数新增（24h cap 不参数化，见 D1）
  - copilot-agents 仓（#3301 互补不重叠）
ACCEPTANCE（二元）:
  - A1: 新增真实子进程测试证明「grandchild 持有管道时 _collect_streamed_process_output 在 wall-clock 界限内返回」
  - A2: 新增测试证明「retries 耗尽（含 rc!=0 + 管道被持有）→ RuntimeError/PermanentDispatchError 抛出，非挂起」
  - A3: parent-death 真实子进程测试证明「父进程死亡（getppid==1）后子进程在 ≤30s 内以 EXIT_PARENT_DEAD 退出」
  - A4: `uv run --group dev pytest -q` 全绿且 passed ≥ 733
  - A5: `uv run ruff check src/loop_kit tests` 0 error
```

---

## 定位结论（阶段一调研产物 — 消化 C1–C4）

基于 HEAD=02e3528 的实测（行号为执行时锚点，允许漂移，计划中函数名与常量名为准）：

1. **C1 消化（根因校正）**：`_wait_for_role_result`（`_core.py:11585`）仅是 `_wait_for_file` 的薄包装，其调用点（`_core.py:12659`）仅在 `config.auto_dispatch=False` 的手动模式可达——任务标题假设的「retries 耗尽后进入 _wait_for_role_result 无限等待」在 auto-dispatch 模式下不成立。
   **真实无界点**是 `_collect_streamed_process_output`（`_core.py:3044`）：
   - `deadline = None if timeout_sec <= 0 else ...`（:3113）→ `while proc.poll() is None` 在 `--dispatch-timeout 0`（默认 `DEFAULT_DISPATCH_TIMEOUT_SEC=0`，`_core.py:353`）下无超时；
   - 更关键：`returncode = proc.wait()` 后的 `stdout_thread.join()` / `stderr_thread.join()`（:3124-3125）**无界**——daemon 读线程在 `for raw_line in pipe`（`_read_pipe`，:3069）阻塞，若直接子进程退出但其 **grandchild 继承管道写端**（`opencode` CLI 派生的 agent 进程），EOF 永不到达 → 主线程永久阻塞于 join。这与孤儿进程 anon_pipe_read 阻塞症状吻合，且解释「重试框架根本来不及参与」。
   - 附带确认：rc!=0 时重试耗尽路径**已存在**并正确抛异常（:3755/:3765/:3775，已有测试 `test_run_auto_dispatch_retry_exhaustion_raises_final_failure`）——但只有子进程正常退出才可达。
2. **C2 消化**：`_wait_for_file`（:9747）`if timeout_sec and elapsed >= timeout_sec`（:9818）→ timeout_sec=0 时跳过逐次检查，唯一兜底为 `_WAIT_SAFETY_CAP_SEC=86400`（:449/:9832）。18.6h 存活与该 24h 上限一致。
3. **C3 保护区确认**：#3263 检查点位于 `_run_auto_dispatch` 内 :3375-3397（session_deadline 前置 fail-fast），本计划所有修改不得触碰该区块；#3155 dirty-tree 在 `git_helpers.py:_dirty_tracked_paths`（本计划零接触）。
4. **C4 确认**：`git stash list` 存在 `stash@{0}: On loop/E2E-1PLUS1/r1/lane_main`；`.github/plans/*.md` 与 `data/` 为 untracked。
5. **测试基础设施事实**：`_FakeProc`（tests/test_orchestrator.py:108）用内存 `_FakePipe` 模拟管道，**无法**复现 grandchild 持管场景 → 必须用真实 `subprocess.Popen([sys.executable, "-c", SCRIPT])`；既有 mock 模式为 `monkeypatch.setattr(orchestrator.time, "monotonic"/"sleep", ...)` + `orchestrator.subprocess.Popen` 替换。退出码现状：`EXIT_OK=0/GENERAL=1/TIMEOUT=2/VALIDATION=3/DIRTY_WORKTREE=4/LOCK_FAILURE=5/PLAN_PATCH_VIOLATION=6/INTERRUPTED=130`（:457-467），无 parent-dead 码。

---

## 关键设计决策（CoT Stage 3：Trade-off 可见）

### D1 — 24h cap（C2）：**保留，不参数化**

```
DECISION: _WAIT_SAFETY_CAP_SEC=86400 保留原值，不加 CLI/配置参数。
ALTERNATIVES: (a) 移除 cap —— 拒绝：手动模式（show_manual_hint=True，人工介入可合法数小时）
  会退化为真正无限等待； (b) 参数化为 --wait-safety-cap —— 拒绝：新增配置面 + 状态漂移风险，无实测需求。
RATIONALE: 本次修复让 retries 耗尽路径在秒级终止，cap 从「唯一兜底」回归「罕见安全网」；
  保留 24h 对人工模式是正确语义。
RISK: 有人误以为 24h 是本次 bug 的修复手段 → 缓解：T2.4 补 cap 回归测试锁定语义 + 计划文档明示。
```

### D2 — parent-death 检测（任务原文「可选增强」）：**纳入（推荐），轻量实现**

```
DECISION: 纳入。实现为懒启动 daemon 监视线程 + 新退出码 EXIT_PARENT_DEAD，钩入两个长等待入口。
ALTERNATIVES: 推迟到独立任务 —— 拒绝：孤儿进程正是「父死子活」类事故的直接复发防护，
  且任务原文验收条件 3 已预留；与 #3301 无重叠（#3301 在 copilot-agents 仓修其自身子进程，
  本仓只监视本进程的 getppid）。
RATIONALE: 范围小（1 helper + 1 常量 + 2 行钩子）、可测、直接消灭 18.6h 孤儿复发路径。
RISK: os._exit 绕过状态写入/锁释放 → 接受（父已死，进程被遗弃，干净退出优于带伤收尾）；Windows 语义差异 → os.name != "nt" 守卫。
```

### D3 — 修复机制选型：**有界读线程回收**（`_collect_streamed_process_output`）

```
DECISION: proc.wait() 后对 stdout/stderr 读线程 join 施加 _PIPE_READER_JOIN_TIMEOUT_SEC（2.0s）上限；
  超时未回收 → _log 警告 + _close_pipe(proc.stdout/stderr) + 1.0s 复 join；_read_pipe 读循环包
  except (OSError, ValueError) 视为 EOF。保持 timeout_sec=0 的 deadline=None 语义不变。
ALTERNATIVES: (a) 改 0=unlimited 语义（给 poll 循环加硬上限）—— 拒绝：破坏文档化契约与既有测试；
  (b) 用 selectors/非阻塞读重写管道读取 —— 拒绝：改动面大、收益低（读线程本就是 daemon）。
RATIONALE: 有界 join 使「grandchild 持管」不再阻塞主线程 → _run_auto_dispatch 可达 rc!=0 重试/耗尽
  逻辑（已有 RuntimeError 抛出与 _fail_single_round(exit_code=EXIT_VALIDATION_ERROR) 分类），
  即「重试耗尽 → 最终放弃」链路闭合，无需新增异常类型（exceptions.py 不在修改白名单）。
RISK: 放弃读线程时可能截断尾部输出 → 仅发生在放弃场景；已写部分保留在 chunks 且 _log 警告；
  正常场景（无 grandchild）join 立即返回零损失。测试断言正常路径 chunks 完整。
```

---

## 假设清单（CoT Stage 2）

1. `[假设: 孤儿根因确为 grandchild 持管导致的读线程 join 阻塞]` — 由 T1.2 真实子进程红测试实证；若红测试显示不同阻塞点（如 poll 循环本身），T2.1 在 HOLD 姿态内调整修复点并记录。影响：高 → 已内置定位任务。
2. `[假设: --timeout 0 与 --dispatch-timeout 0 的「无限」语义是用户可接受的文档化契约]` — 已由 CLI help 文本（`_core.py:14437` "0=unlimited"）与既有测试锁定；修复不改契约，改「孤儿不可发生」（D2/D3 兜底）。
3. `[假设: 733 passed 基线在计划执行时仍成立]` — T1.1 实测；若漂移且漂移非本计划引起，暂停并上报。
4. `[假设: monkeypatch.setattr(orchestrator.os, "getppid", ...) 对 os 模块可行]` — os 是普通 Python 模块，属性可被 monkeypatch；若实测不可行，退化为 patch `_parent_process_died` 谓词（T2.3 已列双路径）。影响：低。
5. `[假设: 执行环境为 Linux（POSIX），ppid==1 判据有效]` — Windows 由 `os.name != "nt"` 守卫跳过监视线程，测试仅断言守卫行为。
6. `[假设: EXIT_PARENT_DEAD=7 与现有退出码无冲突]` — 现有 0-6/130；T2.3 第一步 grep 验证，冲突则取下一个空闲值（验收标准写明验证命令）。

---

## 执行计划

### Phase 1: 定位与基线

- **基线漂移重检**（Phase 首步，强制）：`git rev-parse HEAD` + `git status --porcelain` + `git stash list` 实测；若 HEAD 移动或 `src/loop_kit/_core.py` 被改 → 先 `git log --oneline -3` 确认改动来源，更新本计划锚点（函数名/常量名不变则无需改计划）。**全程禁止 `git stash pop/apply`（C4）**。

#### Task 1.1: 基线实测与锚点重测（无代码变更）
- **目标**：固化执行基线（HEAD、pytest 计数、ruff、锚点行号），确认工作树状态与 C4 约束一致。
- **依赖**：无
- **frontier**：是
- **执行者**：Dev Orchestrator
- **修改内容**：无（只读任务）
- **修改边界**：不得修改/提交任何文件；不得执行 stash 操作。
- **质量检查方式**：
  - 记录 `git rev-parse HEAD`、`git status --porcelain` 全文、`git stash list` 全文
  - 记录 pytest 汇总行（passed/skipped/deselected）
- **验收标准**：
  - ✅ `uv run --group dev pytest -q` 汇总行 passed ≥ 733 且 0 failed（把实测值写入下方 Execution Log）
  - ✅ `uv run ruff check src/loop_kit tests` exit 0
  - ✅ 锚点重测 `grep -n "def _collect_streamed_process_output\|def _run_auto_dispatch\|def _dispatch_with_artifact_fallback\|def _wait_for_file\|def _wait_for_role_result\|_WAIT_SAFETY_CAP_SEC\|DEFAULT_DISPATCH_TIMEOUT_SEC" src/loop_kit/_core.py` 输出 7 个命中（函数名/常量名存在即可，行号允许漂移）
  - ✅ `git status --porcelain` 与 C4 描述一致（plans/*.md、data/ untracked；无 `src/` 或 `tests/` 未预期改动）
- **潜在风险**：基线漂移（他人并发修改）→ 发现即暂停上报。
- **预留歧义标注**：
  - [x] 无歧义：所有字段可直接执行，无需额外推断

#### Task 1.2: 真实子进程复现测试（红测试，定位证据）
- **目标**：用真实 `subprocess.Popen` 复现 C1 一号嫌疑（grandchild 持有 stdout 管道写端 → `_collect_streamed_process_output` / `_run_auto_dispatch` 挂起），产出红测试作为定位证据。**本任务不 commit**（红测试不入历史；变更由 T2.1 commit 吸收）。
- **依赖**：T1.1
- **frontier**：否
- **执行者**：Dev Orchestrator
- **修改内容**：
  - 文件 `tests/test_orchestrator.py`：在 `_FakeProc`/`_BlockingStdin` 定义之后（约 :160 后）新增 2 个测试函数：
    - `test_collect_streamed_process_output_returns_when_grandchild_holds_pipe`：构造 SCRIPT = `import sys,subprocess,time; subprocess.Popen([sys.executable,"-c","import time;time.sleep(15)"], stdout=sys.stdout, stderr=sys.stderr, close_fds=False, start_new_session=True); open(sys.argv[1],"w").write(str(...))`（写入 grandchild PID 供 teardown kill；grandchild 经 `close_fds=False` 继承管道写端）；主测试 `subprocess.Popen([sys.executable, "-c", SCRIPT, pidfile], stdout=PIPE, stderr=PIPE, text=True)` 后调用 `orchestrator._collect_streamed_process_output(proc, role="worker", backend="codex", parse_event_fn=orchestrator._require_registered_parse_event("codex"), stdin_text=None, timeout_sec=0, verbose=False)`；断言 wall-clock 耗时 < 10s 且返回 4 元组；teardown 读 pidfile `os.kill(pid, signal.SIGKILL)`（`contextlib.suppress(ProcessLookupError)` 包裹）。
    - `test_run_auto_dispatch_retry_exhaustion_terminates_despite_pipe_hold`：同样 SCRIPT 但直接子进程 `sys.exit(3)`；monkeypatch `orchestrator._agent_command` → `([sys.executable, "-c", SCRIPT, pidfile], None, "STDIN_PAYLOAD")`、`_log`→None、`_write_dispatch_log`→None、`_feed_event`→收集器（模式同既有测试 :1011）；真实 subprocess 走 `_run_auto_dispatch("worker", "codex", "ignored", 0, dispatch_retries=1, dispatch_retry_base_sec=1)`；断言 wall-clock < 20s 且 `pytest.raises(RuntimeError, match="after 2 attempts")`；teardown kill grandchild。
  - ⛔ 完整路径：`/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`
- **修改边界**：不修改 `src/loop_kit/_core.py`；不新增测试依赖；不触碰既有测试函数。
- **质量检查方式**：
  - 红测试运行须有 shell 级硬超时守卫（修复前会挂起）：
    `timeout 180 uv run --group dev pytest -q tests/test_orchestrator.py -k "grandchild_holds_pipe or retry_exhaustion_terminates"` → 预期 **超时被 shell timeout 杀死或测试 FAIL**（两种都算红证据；输出留存为定位证据）
- **验收标准**：
  - ✅ 两个测试函数存在于 `tests/test_orchestrator.py`，且实测为红（挂起或失败），**不得**出现「意外通过」
  - ✅ 红证据输出明确指向管道读线程阻塞（无 `RuntimeError "after 2 attempts"` 输出）
  - ✅ `git status` 无 commit；测试文件处于修改态（等待 T2.1 吸收）
- **潜在风险**：SCRIPT 里 `close_fds=False` 拼写/行为不符导致复现失败 → 参考 `subprocess.Popen` 文档核对该参数；grandchild 泄漏 → pidfile + teardown kill 兜底。
- **预留歧义标注**：
  - [x] 无歧义：SCRIPT 内容、断言界限、teardown 均已给出

### Phase 2: 修复

- **基线漂移重检**：同上（HEAD、`git status`）；确认 T1.2 的测试修改仍在工作树。

#### Task 2.1: 主修复 — `_collect_streamed_process_output` 有界读线程回收
- **目标**：消灭 grandchild 持管导致的无限 join 阻塞，使 `_run_auto_dispatch` 的重试/耗尽逻辑可达；不改变 `timeout_sec=0` 的 deadline=None 契约。
- **依赖**：T1.2
- **frontier**：否
- **执行者**：Dev Orchestrator
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    1. 常量区（`DISPATCH_STREAM_POLL_SEC = 0.1` 附近，:448 邻域）新增：`_PIPE_READER_JOIN_TIMEOUT_SEC = 2.0  # bounded reclaim for pipe-reader threads (grandchild holding pipe)`
    2. `_read_pipe`（:3069 邻域）：将 `for raw_line in pipe:` 循环包入 `try: ... except (OSError, ValueError): pass`（主线程关管后读线程异常 → 视为 EOF 安静退出；`finally: _close_pipe(pipe)` 保持不变）
    3. `_collect_streamed_process_output`（:3113-3128 邻域）：`returncode = proc.wait()` 之后，`stdout_thread.join()` → `stdout_thread.join(timeout=_PIPE_READER_JOIN_TIMEOUT_SEC)`；若 `stdout_thread.is_alive()`：`_log("abandoning blocked stdout reader after ...s; grandchild may hold pipe")` + `_close_pipe(proc.stdout)` + `stdout_thread.join(timeout=1.0)`；`stderr_thread` 同。`stdin_thread.join(timeout=5.0)` 保持不动。**不修改** `deadline = None if timeout_sec <= 0 else ...` 与 `while proc.poll() is None` 的超时逻辑。
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：T1.2 两个测试保持原样（随本任务转绿，一并 commit）。
- **修改边界**：⛔ 不得修改 `_run_auto_dispatch` 的 session_deadline 检查点（:3375-3397 区块，C3）、重试计数/延迟逻辑（:3368-3398 与 :3722-3796 的 retry 语义）、`_dispatch_with_artifact_fallback` 与 `_wait_for_file` 本体；⛔ 不得触碰 `dispatch.py` / `file_bus.py` / `session.py` / `exceptions.py`。
- **质量检查方式**：
  - 修复后复跑 T1.2 两条测试（无需 shell timeout 兜底也应 <180s 完成）：
    `uv run --group dev pytest -q tests/test_orchestrator.py -k "grandchild_holds_pipe or retry_exhaustion_terminates"`
  - 契约锁定回归：
    `uv run --group dev pytest -q tests/test_orchestrator.py -k "zero_timeout_is_unlimited or timeout_kills_and_waits or stdin_write_blocks or collect_streamed_text_output"`
- **验收标准**：
  - ✅ T1.2 两条测试转绿（返回 4 元组 / raise RuntimeError "after 2 attempts"，均不挂起）
  - ✅ `test_run_auto_dispatch_zero_timeout_is_unlimited` 保持绿（`terminate_called is False` 断言不变——证明 0=unlimited 契约未被破坏）
  - ✅ `test_run_auto_dispatch_timeout_kills_and_waits_process`、`..._stdin_write_blocks`、`test_collect_streamed_text_output_waits_with_timeout_on_stream_exception` 保持绿
  - ✅ `uv run ruff check src/loop_kit tests` exit 0
  - ✅ commit：`git add src/loop_kit/_core.py tests/test_orchestrator.py`（**仅此两文件**，commit 前 `git status --porcelain` 确认无意外 hunk）→ message：`[Plan: pm3346-dispatch-retries-final-abandonment] T2.1 bounded pipe-reader reclamation in _collect_streamed_process_output (#3346)`
- **潜在风险**：bounded join 截断正常路径输出 → 仅放弃场景截断且有 `_log` 警告；无 grandchild 场景 join 立即返回（现有测试全部走 `_FakePipe` 有限迭代，可证明）。放弃场景读线程抛 ValueError 打印 threading 异常 → 已被 `_read_pipe` 的 except 吞掉。
- **预留歧义标注**：
  - [x] 无歧义：常量名/值、join 顺序、异常类型、commit message 均已给定

#### Task 2.2: 重试耗尽终止路径回归测试（含 retries=0 边界）
- **目标**：锁定「重试耗尽 → 明确异常（分类与退出码）」链路的纯 `_FakeProc` 回归覆盖，含 retries=0（max_attempts=1）边界。
- **依赖**：T2.1
- **frontier**：否
- **执行者**：Dev Orchestrator
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `test_run_auto_dispatch_retry_exhaustion_zero_retries_raises`：模式同既有 :1011 测试；`_FakeProc(stdout_lines=[], stderr_lines=["fail\n"], returncode=3)`；调用 `_run_auto_dispatch("worker", "codex", "ignored", 30, dispatch_retries=0, dispatch_retry_base_sec=5)`；断言 `pytest.raises(RuntimeError, match="after 1 attempts")`、`len(popen_calls) == 1`、`sleep_calls == []`、`FEED_DISPATCH_FAIL` 事件恰好 1 个。
  - `src/loop_kit/_core.py`：**预期零修改**（:3775 分支已覆盖 retries=0 场景；仅当新测试暴露 message 缺陷时才允许微调错误消息字符串，且不得改控制流）。
- **修改边界**：不得改 `_core.py` 控制流/异常类型；不得新增异常类。
- **质量检查方式**：`uv run --group dev pytest -q tests/test_orchestrator.py -k "retry_exhaustion"`
- **验收标准**：
  - ✅ 新测试绿；既有 `test_run_auto_dispatch_retry_exhaustion_raises_final_failure` 保持绿
  - ✅ `uv run ruff check tests` exit 0
  - ✅ commit（仅 `tests/test_orchestrator.py`）：`[Plan: pm3346-dispatch-retries-final-abandonment] T2.2 retry-exhaustion zero-retries regression test (#3346)`
- **潜在风险**：低（纯测试）。
- **预留歧义标注**：
  - [x] 无歧义

#### Task 2.3: parent-death 检测（D2 决策落地）+ EXIT_PARENT_DEAD
- **目标**：父进程死亡（`os.getppid()==1`）后子进程在限定时间（约 5s 轮询 + 余量）内自行退出，退出码 `EXIT_PARENT_DEAD=7`；POSIX 守卫。
- **依赖**：T2.1（共享 `_core.py`，避免编辑冲突）
- **frontier**：否
- **执行者**：Dev Orchestrator
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：
    1. 常量区新增：`PARENT_DEATH_POLL_SEC = 5.0`；退出码区（:457-467 邻域）新增 `EXIT_PARENT_DEAD = 7`。**先行验证**：`grep -n "= 7\b" src/loop_kit/_core.py` 确认 7 未被占用（现有 0-6/130）；若冲突取下一个空闲整数并在 commit message 注明。
    2. 新增 helper（`_wait_for_file` 定义前邻域）：
       - `def _parent_process_died() -> bool:` → `return os.getppid() == 1`（含 3 行注释说明 POSIX 语义）
       - `def _ensure_parent_death_monitor() -> None:` → `os.name == "nt"` 直接 return；模块级 `_parent_death_monitor_started: bool = False` + `threading.Lock()` 双检懒启动 daemon 线程，线程体：`while True: time.sleep(PARENT_DEATH_POLL_SEC); if _parent_process_died(): _log("parent process died; exiting with EXIT_PARENT_DEAD"); os._exit(EXIT_PARENT_DEAD)`
    3. 钩入两处（函数体第一行，`_log` 之后）：`_wait_for_file`（:9747 邻域）与 `_collect_streamed_process_output`（:3044 邻域）各加一行 `_ensure_parent_death_monitor()`。
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：
    1. 单测 `test_parent_process_died_detects_reparented_ppid`：`monkeypatch.setattr(orchestrator, "_parent_process_died", lambda: True)` 后断言为 True；再用 `monkeypatch.setattr(orchestrator.os, "getppid", lambda: 1)`（若 os 模块 setattr 无效则跳过此变体——见假设 4）直接断言 `_parent_process_died() is True`、恢复后为 False。
    2. 真实子进程测试 `test_parent_death_monitor_exits_real_child`：`subprocess.Popen([sys.executable, "-c", SCRIPT])`，SCRIPT = `import sys, unittest.mock; sys.path.insert(0, "<repo>/src"); from loop_kit import _core; with unittest.mock.patch("os.getppid", return_value=1): _core._wait_for_file(<不存在路径>, "t", timeout_sec=0)`；主测试断言 `proc.wait(timeout=30) == 7`（30s 上限即「限定时间」验收）。
- **修改边界**：⛔ 不修改 `_run_auto_dispatch` session_deadline 区块与重试逻辑；⛔ 不新增 CLI 参数；⛔ 不改 `exceptions.py`；监视线程只做 `_log` + `os._exit`，不做任何状态写入（设计决策见 D2 RISK）。
- **质量检查方式**：
  - `uv run --group dev pytest -q tests/test_orchestrator.py -k "parent_death or parent_process_died"`
  - `uv run --group dev pytest -q tests/test_orchestrator.py -k "wait_for_file"`（确认 `_wait_for_file` 既有测试不受钩子影响）
- **验收标准**：
  - ✅ 单测绿；真实子进程测试绿（子进程 exit code == 7 且 `wait(timeout=30)` 未超时）
  - ✅ `uv run ruff check src/loop_kit tests` exit 0
  - ✅ `grep -n "EXIT_PARENT_DEAD" src/loop_kit/_core.py` 出现 ≥2 处（定义 + `os._exit` 调用）
  - ✅ commit（两文件）：`[Plan: pm3346-dispatch-retries-final-abandonment] T2.3 parent-death monitor + EXIT_PARENT_DEAD (#3346)`
- **潜在风险**：`os._exit` 在非预期时机触发（测试进程）→ 懒启动 + 真实 getppid 在正常测试中恒非 1，仅真实子进程测试被 mock；Windows CI 跑测试 → `_ensure_parent_death_monitor` 的 nt 守卫使监控不启动，真实子进程测试加 `@pytest.mark.skipif(os.name == "nt", ...)`。
- **预留歧义标注**：
  - [x] 无歧义：实现形态、钩子位置、测试 SCRIPT、退出码均已给定；唯一运行时决策点（7 被占用时换值）已写验证命令

#### Task 2.4: 24h cap 保留（C2/D1 决策落地）回归测试
- **目标**：锁定 `_wait_for_file(timeout_sec=0)` 的唯一兜底 `_WAIT_SAFETY_CAP_SEC` 语义（保留决策 D1），防止后续改动误删 cap。
- **依赖**：T2.3（共享 tests 文件，串行）
- **frontier**：否
- **执行者**：Dev Orchestrator
- **修改内容**：
  - 文件 `/home/gw/opt/agent-task-runner/tests/test_orchestrator.py`：新增 `test_wait_for_file_safety_cap_returns_none`：`monotonic_values = iter([0.0, 86401.0])`；`monkeypatch.setattr(orchestrator.time, "monotonic", lambda: next(...))`、`monkeypatch.setattr(orchestrator.time, "sleep", lambda _: None)`；`_wait_for_file(tmp_path/"missing.json", "t", timeout_sec=0)` 断言返回 None。
  - 文件 `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`：可选——在 `_WAIT_SAFETY_CAP_SEC = 86400` 注释追加一句：`# retained by decision (PM #3346 plan D1): absolute fallback for manual-mode waits`。
- **修改边界**：不得改 cap 数值、不得参数化、不得改 `_wait_for_file` 循环结构。
- **质量检查方式**：`uv run --group dev pytest -q tests/test_orchestrator.py -k "safety_cap or wait_for_file"`
- **验收标准**：
  - ✅ 新测试绿；既有 `test_wait_for_file_ignores_stale_run_id_until_matching_artifact` 等保持绿
  - ✅ `uv run ruff check src/loop_kit tests` exit 0
  - ✅ commit（测试文件 + 可选注释）：`[Plan: pm3346-dispatch-retries-final-abandonment] T2.4 safety-cap retention regression test (#3346)`
- **潜在风险**：低。
- **预留歧义标注**：
  - [x] 无歧义

### Phase 3: 回归与收尾

- **基线漂移重检**：`git rev-parse HEAD` + `git status --porcelain`；确认 4 个 T2.x commit 已落，工作树干净（除 untracked plans/data）。

#### Task 3.1: 全量回归 + 提交纪律终检
- **目标**：全量测试、静态检查、提交范围终检；发现任何回归就地修复（修复仅限白名单两文件，并走增量 commit）。
- **依赖**：T2.4
- **frontier**：否
- **执行者**：Dev Orchestrator
- **修改内容**：预期无；仅当回归暴露问题才修改（并逐条追加 commit，message 同前缀格式）。
- **修改边界**：同全计划白名单；禁止 stash 操作。
- **质量检查方式**：见下方 Post-Execution Verification 全表。
- **验收标准**：
  - ✅ V1–V6 全绿（见下表）；P1 输出 `2.0 5.0 7`
  - ✅ `git log --oneline -6` 显示 4 个 T2.x commit 且均含 `#3346`
  - ✅ `git status --porcelain` 无 `src/`、`tests/` 遗留修改；untracked 仅既有 `data/` 与 `.github/plans/*.md`（本计划文件本身）
- **潜在风险**：全量回归暴露既有 flaky（非本计划引起）→ 记录在 Execution Log 并标注 `[FLAKY?]`，不掩盖。
- **预留歧义标注**：
  - [x] 无歧义

---

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier（无人挡即刻开工） | 依赖已完成 |
|------|------------|--------------------------|------------|
| W1 | T1.1 | T1.1 | — |
| W2 | T1.2 | T1.2 | W1 |
| W3 | T2.1 | T2.1 | W2 |
| W4 | T2.2 | T2.2 | W3 |
| W5 | T2.3 | T2.3 | W4 |
| W6 | T2.4 | T2.4 | W5 |
| W7 | T3.1 | T3.1 | W6 |

**CoT Stage 4（顺序理由）**：T1.1→T1.2 是「基线→证据」因果链；T2.1 必须吸收 T1.2 红测试转绿（红测试不入历史，提交纪律要求 commit 恒绿）；T2.2/T2.3/T2.4 均编辑 `tests/test_orchestrator.py`（T2.3 另加 `_core.py`），共享文件并发编辑易冲突，故串行——每任务仍是完整纵向切片（修复+其测试+其 commit），符合 tracer-bullet 原则。**失败回滚策略**：每任务单 commit 粒度，失败即 `git revert` 该任务 commit 或 `git checkout -- <file>` 丢弃未提交变更；T2.1 失败不影响 T1.2 证据（测试文件仍在工作树）。

---

## Post-Execution Verification

Dev Orchestrator 在所有 plan task 执行完毕后**必须**运行本节命令。

### Automated Verification（Dev Orchestrator 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量回归 | `uv run --group dev pytest -q` | exit 0；passed ≥ 733（+7 新增），0 failed |
| V2 | ruff | `uv run ruff check src/loop_kit tests` | exit 0，0 error |
| V3 | 编译 | `uv run python -m py_compile src/loop_kit/_core.py` | exit 0 |
| V4 | 导入烟测 | `uv run python -c "from loop_kit.orchestrator import *"` | exit 0 |
| V5 | 提交范围 | `git log --oneline -6` + `git status --porcelain` | 4 个 T2.x commit 含 `#3346`；无 `src/`/`tests/` 遗留改动；无 stash 操作痕迹 |
| V6 | cap 保留 | `grep -n "_WAIT_SAFETY_CAP_SEC" src/loop_kit/_core.py` | 定义仍为 `86400`（D1 决策锁定） |
| V1b | de-ai-fier 术语门 | `de-ai-fier/deai_review_file(path=".github/plans/pm3346-dispatch-retries-final-abandonment-2026-09-05.md", doc_type="plan", strict=false, include_ai_flavor_assessment=true)` | 术语 finding 记录摘要（suggestion/info 级不阻塞）；MCP 不可用标注 `[⚠️ skipped]` |

### Probe (best-effort, run if available)

- [ ] P1: `uv run python -c "from loop_kit import _core as c; print(c._PIPE_READER_JOIN_TIMEOUT_SEC, c.PARENT_DEATH_POLL_SEC, c.EXIT_PARENT_DEAD)"` → 输出 `2.0 5.0 7`

### Manual（真正需要人工判断）

- [ ] M1: 人工复核 T1.2 红测试证据与 T2.1 转绿 diff，确认修复针对真实阻塞点（读线程 join）而非掩盖（如删断言/放宽界限）

---

## 风险表（C1–C4 对应）

| # | 风险 | 影响 | 缓解措施 | 对应 |
|---|------|------|----------|------|
| R1 | 根因误判（实际阻塞点非读线程 join，如 poll 循环他因） | 修复无效，孤儿复发 | T1.2 真实子进程红测试先行实证；若证据不符，Phase 2 在 HOLD 姿态内调整修复点并记录 | C1 |
| R2 | 24h cap 被误删/参数化，manual 模式退化为真无限等待 | 严重 | D1 决策保留；T2.4 回归测试锁定；V6 终检 | C2 |
| R3 | 误改 #3263 session_deadline 检查点 / #3155 dirty-tree fail-fast | 破坏既有修复 | 修改仅限白名单函数；C3 区块列为 ⛔ 边界；每 commit 前 `git diff --stat` 负向验证 | C3 |
| R4 | `git stash pop/apply` 破坏 loop/E2E-1PLUS1 worktree；untracked 卷入提交 | 数据/环境破坏 | 全程禁 stash；commit 白名单 `git add` 显式路径；V5 终检 | C4 |
| R5 | bounded join 截断正常输出 | 丢失尾部日志 | 仅放弃场景截断；正常场景 join 立即返回；`_log` 警告；测试断言正常路径完整 | — |
| R6 | `os._exit` 在测试进程误触发 | 测试异常终止 | 懒启动 + 真实 getppid 测试环境恒非 1；真实子进程测试隔离于独立进程 | — |
| R7 | Windows 语义差异（ppid==1 判据） | CI 平台不兼容 | `os.name != "nt"` 守卫 + 测试 skipif | — |
| R8 | 与 #3301（copilot-agents 仓）重叠 | 重复/冲突修复 | 本计划零跨仓改动（#3300 规则）；parent-death 仅监视本进程 getppid | — |
| R9 | 基线漂移（并发修改导致 733 基线变化） | 验收误判 | T1.1 实测基线；漂移且非本计划引起 → 暂停上报，不以旧基线为准 | — |

---

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（Phase/Task/Wave/验证表齐备；≤8 任务；每任务 ≤3 文件） | 1（T1.2 红测试 commit 策略未显式化） | 1（改为「不 commit，T2.1 吸收」并写入任务体） | 0 |
| R1.5 | 外部引用事实核查（函数名/常量/行号/测试模式/退出码/CLI 语义全部在 HEAD=02e3528 实测） | 0 | — | 0 |
| R2 | 可执行性（命令可复制、红测试有 shell timeout 守卫、mock 模式与既有测试一致） | 1（真实子进程测试缺 grandchild 清理） | 1（pidfile + teardown SIGKILL） | 0 |
| R2.8 | LLM 可执行性（逐字段消除歧义：SCRIPT 内容、断言界限、join 顺序、commit message、exit code 验证命令均给定） | 0 | — | 0 |
| R3 | 风险与边缘（C1-C4 映射、跨轮一致性：D1-D3 决策与 task 体一致、边界与白名单一致、执行者/依赖/Wave 无环） | 0 | — | 0 |
| **终止** | **T1 — HOLD 姿态范围无漂移** | | | **0** |

---

## Execution Log

### [2026-09-05] 执行完成（Dev Orchestrator，7/7 任务 ✅）

- **T1.1 ✅**：基线实测 HEAD=02e3528，pytest 733 passed/1 skipped/3 deselected，ruff 全绿；锚点 7 命中（行号与计划一致）。
- **T1.2 ✅**：2 条真实子进程红测试实测为红——collector 阻塞 15.0s（grandchild 持管），retry 链 31.1s（2×15s+1s retry delay）。红证据精确指向 `_collect_streamed_process_output` 读线程 join 无界阻塞（C1 校正成立）。红测试不 commit，由 T2.1 吸收。
- **T2.1 ✅**（commit a3d3c28）：`_PIPE_READER_JOIN_TIMEOUT_SEC=2.0` + `_join_reader` 有界 join 放弃 daemon 读线程；`_read_pipe` 吞 OSError/ValueError。**计划偏差 D1**：计划原写「join 超时后 close pipe + 1.0s 复 join」，实测发现 CPython io 对象在被阻塞 readline 时持有内部锁，主线程 close() 会自身阻塞至 grandchild 退出（实测 close() 阻塞 13s）——改为「有界 join + 日志警告 + 放弃（不 close）」，行为/影响范围与计划一致（主线程秒级返回，重试耗尽路径可达）。两条红测试转绿（13.4s），契约锁定回归 4 项全绿（zero_timeout_is_unlimited 等）。
- **T2.2 ✅**（commit bba09f5）：retries=0 边界回归测试，`after 1 attempts` + 单次 popen + 零 sleep + 1 个 fail 事件。
- **T2.3 ✅**（commit 56c9dcf）：`EXIT_PARENT_DEAD=7`（7 未占用已验证）+ `PARENT_DEATH_POLL_SEC=5.0` + `_parent_process_died`/`_ensure_parent_death_monitor`（POSIX 守卫，daemon 懒启动）钩入 `_wait_for_file` 与 `_collect_streamed_process_output`。真实子进程测试：mock getppid=1 → 子进程 5.9s 内以退出码 7 退出。**计划偏差 D1**：测试 SCRIPT 需在子进程内 `from pathlib import Path`（_wait_for_file 接收 Path 而非 str），已在计划范围内微调。
- **T2.4 ✅**（commit 9648fbe）：24h cap 保留回归测试（timeout_sec=0 下 monotonic 86401s → 返回 None）+ cap 常量 D1 决策注释。
- **T3.1 ✅**：V1 全量 739 passed/1 skipped/3 deselected（基线 733 + 6 新增）；V2 ruff 0 error；V3 py_compile OK；V4 import smoke OK；V5 4 个 T2.x commit 含 #3346、无 src/tests 遗留、无 stash 操作；V6 cap=86400 保留；P1 probe 输出 `2.0 5.0 7`。

**偏差汇总**（均 D1，行为/范围一致）：
1. T2.1 close-pipe 步骤移除（CPython io 锁阻塞实证），改为纯有界 join 放弃
2. T2.3 测试脚本补 Path 导入
3. 测试文件一处预存在超长 lambda 行被环境格式化器反复合并，每次 edit 后需复原换行（无实质内容变化）


