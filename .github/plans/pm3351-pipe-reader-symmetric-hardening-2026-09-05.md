# Plan: PM #3351 — pipe-reader 对称加固（文本版有界 join + parent-death monitor 初始 PPID 防御）

- **任务**: PM #3351 [ATR] pipe-reader 对称加固（workspace: /home/gw/opt/agent-task-runner，priority=low）
- **Scope Mode**: HOLD（防御加固，严格不扩不缩）
- **基线（执行时实测，勿沿用本值）**: `git rev-parse HEAD` + `uv run --group dev pytest` 实测基线（预期 739 passed / 1 skipped / 3 deselected）；`uv run ruff check src/loop_kit tests` 0 error；工作树干净，6 个 untracked 文件**不得卷入任何 commit**
- **硬约束**: 只改 `src/loop_kit/_core.py` + `tests/test_orchestrator.py`；不改 `_collect_streamed_process_output` 与 `_wait_for_file` 结构；不引入 CLI 参数；每任务独立 commit（message 含 `#3351`）
- **task-fit verdict=valid 消化要点**: 调整 1 — 文本版 stdout 在主线程消费（_core.py:3190-3204），grandchild 双管持有时主线程先阻塞于 stdout for-loop，仅 stderr join 加 timeout 不够，必须 stdout 也迁入 daemon reader 线程；调整 2 — 新 monitor 语义破坏 tests:286 与 tests:273，本计划含其改造

## 背景与目标

- **缺口①**: `_collect_streamed_text_output`（src/loop_kit/_core.py:3170-3208）的 `stderr_thread.join()`（L3207）无界：grandchild 持管（opencode CLI 派生 agent 后代）→ reader 永不 EOF → 主线程永久阻塞。对称应用 #3346 有界 join 模式（`_PIPE_READER_JOIN_TIMEOUT_SEC=2.0`，_core.py:454 + L3155-3161：放弃 daemon 读线程 + `_log` 警告；**禁止主线程 close pipe** —— CPython io 锁反阻塞已实证，注释见 L3149-3154）。
- **缺口②**: parent-death monitor 对「出生即 PPID=1」进程误判：`_parent_process_died()`（L9794-9796）裸判断 `os.getppid()==1`，直接子 init 的进程（部分 supervisor 场景）会误自杀。防御：`_ensure_parent_death_monitor()`（L9799-9817）记录初始 PPID；谓词仅当「初始 PPID != 1 且当前 == 1」返回 True；monitor 未启动（无基线）返回 False。
- **非目标**: 不改 `_collect_streamed_process_output`（L3055-3167）与 `_wait_for_file`（L9820+）结构；不改 `_PIPE_READER_JOIN_TIMEOUT_SEC` 取值；不新增 CLI 面；不触及 6 个 untracked 文件。

## 关键设计决策

1. **stdout 线程化方案**：stdout 消费迁入 daemon reader 线程（镜像 process 版 `_read_pipe` L3082-3098 的线程结构），但**异常处理不照抄**——process 版吞 `(OSError, ValueError)`，文本版必须 `except Exception → stash 进 stream_error 列表`，主线程有界 join 后按旧 finally 顺序先 `proc.wait(timeout=1)` 再 `raise stream_error[0]`。原因：tests:837 `test_collect_streamed_text_output_waits_with_timeout_on_stream_exception` 锁定「回调异常传播 + wait_timeouts==[1]」契约，reader 线程内吞掉会静默打破该测试（task-fit 只列了 273/286，未计入 837——本计划用 stash-重抛方案保住它，避免第三处测试改造）。
2. **initial-ppid 记录位置**：新增模块级 `_parent_death_initial_ppid: int | None = None`（紧邻 L9790 两个既有全局）；在 `_ensure_parent_death_monitor()` 内、`_parent_death_monitor_lock` 临界区内、`_parent_death_monitor_started=True` 之前赋值 `os.getppid()`。`_parent_process_died()` 改为：`initial is None or initial == 1 → False`，否则 `os.getppid() == 1`。单条件同时覆盖「未启动」与「出生即 1」两情形，谓词无需再查 started 标志。
3. **两测试改造方案**：tests:273 → 纯单元测试，直接 monkeypatch `orchestrator._parent_death_initial_ppid` 全局 + 模拟 getppid，覆盖 4 情形（未启动/初始=1/初始非1仍存活/初始非1→1）；**不启动真实 monitor 线程**（避免测试进程内 os._exit 风险与全局状态污染）。tests:286 → 真实子进程「初始非 1 → 中途变 1」转移场景：子进程内以计数式 getppid mock（第 1 次调用返回真实 ppid——恰为 monitor 启动时的基线记录，之后返回 1），首次 poll（PARENT_DEATH_POLL_SEC=5.0）即触发 EXIT_PARENT_DEAD。

## 执行计划

### Phase 1: 缺口① 文本版收集器加固

- **基线漂移重检**（本 Phase 首步，强制）：`git rev-parse HEAD` + `git status --porcelain`；若 L3170-3208 或 L454/L3155 锚点漂移（目标区被改、行号移动）→ 先重读再动手；确认 untracked 集合仍为原 6 项。

#### Task 1.1: `_collect_streamed_text_output` 对称加固（_core.py）
- **依赖**: 无
- **frontier**: 是
- **执行者**: Task Executor
- **修改文件**: `src/loop_kit/_core.py`（仅函数 L3170-3208，其余文件不动）
- **实施要点**:
  1. 删除主线程 stdout for-loop（现 L3190-3204，含 stream_error/finally 块），主线程不再直接读任何 pipe。
  2. 新增函数内 `stream_error: list[BaseException] = []`；新增本地 `_read_pipe(pipe, sink, line_callback=None)`：`if pipe is None: return`；`try: for raw_line in pipe: sink.append(raw_line); callback 非空则调用`；`except Exception as exc: stream_error.append(exc)`（**宽捕获，不得缩窄为 (OSError, ValueError)**——回调 RuntimeError 必须进 stash）；`finally: _close_pipe(pipe)`。
  3. stdout/stderr 各起 daemon reader 线程（stdout 传 `stdout_line_callback`，stderr 不传回调），立即 start；stdout_line_callback 在 reader 线程内调用（单 reader 保证行序确定性，capsys 断言不受影响）。
  4. 本地复制 #3346 `_join_reader` 模式（参照 L3155-3161）：`thread.join(timeout=_PIPE_READER_JOIN_TIMEOUT_SEC)`，`is_alive()` 则 `_log(f"abandoning blocked {name} reader after {_PIPE_READER_JOIN_TIMEOUT_SEC:.1f}s; grandchild may hold the pipe")`。join 顺序 stdout → stderr。**主线程不得 close 任一 pipe**。
  5. 若 `stream_error` 非空：`with contextlib.suppress(subprocess.TimeoutExpired, OSError): proc.wait(timeout=1)` 后 `raise stream_error[0]`（复刻旧 finally 顺序，保 tests:837 契约）。
  6. 正常路径 `returncode = proc.wait()`；返回 3 元组 `(stdout, stderr, returncode)` 签名不变。
- **修改边界**: 不改 `_collect_streamed_process_output`（L3055-3167）、`_wait_for_file`、`_PIPE_READER_JOIN_TIMEOUT_SEC` 值；不在本任务改 tests 文件。
- **质量检查方式**:
  - `uv run --group dev pytest -k "collect_streamed_text_output or run_auto_dispatch"` → 全绿（重点：tests:837/853/880/8613）
  - `uv run python -m py_compile src/loop_kit/_core.py` → exit 0
  - `uv run ruff check src/loop_kit/_core.py` → 0 error
- **验收标准**:
  - ✅ `test_collect_streamed_text_output_waits_with_timeout_on_stream_exception` 通过且 `proc.wait_timeouts == [1]`（异常传播契约未破坏）
  - ✅ 上述三条命令全部 exit 0
- **潜在风险**: 若误将异常捕获缩窄为 (OSError, ValueError)，tests:837 静默失败——按要点 2 的宽捕获执行即可规避。
- **commit**: `[PM #3351] pipe-reader 对称加固：文本版收集器 stdout/stderr 双 reader 线程 + 有界 join`（仅 `git add src/loop_kit/_core.py`，禁止 `git add -A`）

#### Task 1.2: 缺口① 回归测试（grandchild 持管限时返回）
- **依赖**: T1.1
- **frontier**: 否（需 T1.1 修复在场）
- **执行者**: Task Executor
- **修改文件**: `tests/test_orchestrator.py`（在 tests:203 `test_collect_streamed_process_output_returns_when_grandchild_holds_pipe` 之后新增 1 个测试）
- **实施要点**: 镜像 tests:203-236 结构，新增 `test_collect_streamed_text_output_returns_when_grandchild_holds_pipe(tmp_path)`：
  1. `pidfile = tmp_path / "grandchild.pid"`；`subprocess.Popen([sys.executable, "-c", _grandchild_pipe_holder_script(0), str(pidfile)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")`（复用 tests:177 `_grandchild_pipe_holder_script`，grandchild 双管持有 ~15s，子进程立即 exit 0）。
  2. `start = time.monotonic()`；调用 `orchestrator._collect_streamed_text_output(proc)`（不传回调）。
  3. 断言：`elapsed < 10.0`（修复后预期 ~4s：两次 2.0s 有界 join + 快速 wait；未修复时 stdout 主线程阻塞 ~15s 直接失败）；`stdout`/`stderr` 均为 `str`；`returncode == 0`。
  4. finally 清理同 tests:231-236：`proc.kill()` → `proc.wait(timeout=5)` → `_kill_pidfile_process(pidfile)`。
- **修改边界**: 不改 `_grandchild_pipe_holder_script` 与 `_kill_pidfile_process` 本体；不改 tests:203 现有 process 版测试。
- **质量检查方式**:
  - `uv run --group dev pytest tests/test_orchestrator.py -k "collect_streamed_text_output"` → 全绿
  - `uv run ruff check tests/test_orchestrator.py` → 0 error
- **验收标准**:
  - ✅ 新测试通过且 elapsed < 10.0（grandchild 持管下主线程限时返回的测试证明）
  - ✅ `pytest -k collect_streamed_text_output` 全绿（新旧文本版测试共存）
- **潜在风险**: 子进程遗留 zombie——finally 清理已覆盖；grandchild 由 `_kill_pidfile_process` SIGKILL 兜底。
- **commit**: `[PM #3351] 测试：文本版收集器 grandchild 持管限时返回回归用例`（仅 `git add tests/test_orchestrator.py`）

### Phase 2: 缺口② parent-death monitor 初始 PPID 防御

- **基线漂移重检**（本 Phase 首步，强制）：`git rev-parse HEAD` + `git status --porcelain`；确认 L9790-9817 monitor 组锚点未漂移；确认 T1 的 2 个 commit 已落。

#### Task 2.1: monitor 初始 PPID 防御（_core.py）
- **依赖**: 无（与 T1.2 文件不相交，可并行）
- **frontier**: 是（仅改 _core.py，与 T1.2 改 tests 文件无冲突）
- **执行者**: Task Executor
- **修改文件**: `src/loop_kit/_core.py`（仅 monitor 组 L9790-9817）
- **实施要点**:
  1. 在 L9791 `_parent_death_monitor_lock` 之后新增 `_parent_death_initial_ppid: int | None = None`。
  2. 重写 `_parent_process_died()`（L9794-9796）为：`if _parent_death_initial_ppid is None or _parent_death_initial_ppid == 1: return False`；`return os.getppid() == 1`（注释：monitor 未启动无基线不可判；出生即 PPID=1 的进程不可判为孤儿——仅真实 reparenting 转移触发）。
  3. `_ensure_parent_death_monitor()`（L9799+）：`global _parent_death_monitor_started, _parent_death_initial_ppid`；在 `_parent_death_monitor_lock` 临界区内、`_parent_death_monitor_started = True` 之前执行 `_parent_death_initial_ppid = os.getppid()`。
- **修改边界**: 不改 `_monitor_loop` 主体、`PARENT_DEATH_POLL_SEC`、`EXIT_PARENT_DEAD`；不改 tests 文件。
- **质量检查方式**:
  - `uv run python -m py_compile src/loop_kit/_core.py`
  - `uv run ruff check src/loop_kit/_core.py`
  - `uv run --group dev pytest -k "parent"`（旧 273/286 预期**暂时失败**——属已知过渡态，T2.2 完成后转绿；不得在本任务修测试）
- **验收标准**:
  - ✅ py_compile 与 ruff 全绿
  - ✅ 谓词三条件可读性复核：`None → False`、`initial==1 → False`、`initial!=1 且当前==1 → True`
- **潜在风险**: 若把记录放在锁外或 started=True 之后，存在竞态窗口——严格按要点 3 顺序。
- **commit**: `[PM #3351] parent-death monitor 记录初始 PPID：出生即 1 不误判，仅真实 reparenting 触发`（仅 `git add src/loop_kit/_core.py`）

#### Task 2.2: 缺口② 两测试改造（tests:273 + tests:286）
- **依赖**: T2.1
- **frontier**: 否（新语义测试依赖 T2.1 在场）
- **执行者**: Task Executor
- **修改文件**: `tests/test_orchestrator.py`（仅 tests:273 与 tests:286 两个函数）
- **实施要点**:
  1. **重写 tests:273**（现 `test_parent_process_died_detects_reparented_ppid` → `test_parent_process_died_initial_ppid_semantics`），纯单元、**不启动真实 monitor 线程**，按序 4 组断言：
     - 未启动（`monkeypatch.setattr(orchestrator, "_parent_death_initial_ppid", None)` + getppid→1）→ `False`
     - 初始=1（`_parent_death_initial_ppid` 置 1 + getppid→1）→ `False`（出生即 1 恒 False）
     - 初始非 1 仍存活（置 4242 + getppid→4242）→ `False`
     - 初始非 1 变 1（置 4242 + getppid→1）→ `True`
     - 结尾 `monkeypatch.setattr(orchestrator.os, "getppid", real_getppid)` 还原（复用原测试 275 行的 real_getppid 模式）。
  2. **重写 tests:286**（`test_parent_death_monitor_exits_real_child`）为转移场景：子进程脚本改为先 `real_ppid = os.getppid()`，再 `calls={'n':0}` 计数式 `fake_getppid()`（第 1 次调用返回 `real_ppid`——恰为 `_ensure_parent_death_monitor` 基线记录（`_wait_for_file` L9832 首行调用，此前无其他 getppid 调用），此后返回 1），`with unittest.mock.patch('os.getppid', side_effect=fake_getppid):` 内调 `_core._wait_for_file(Path(missing_artifact), 't', timeout_sec=0)`；父测试保留 `proc.wait(timeout=30)` + `assert rc == orchestrator.EXIT_PARENT_DEAD`（首次 poll ~5s 内触发）+ 原 finally 清理（tests:303-310）。原「出生即 mock getppid=1」脚本在新语义下永不触发→挂死，必须整体替换。
- **修改边界**: 不动 tests:273/286 之外的任何测试；不改 `_grandchild_pipe_holder_script`；不在子进程脚本中引入真实 reparenting（不可靠）。
- **质量检查方式**:
  - `uv run --group dev pytest tests/test_orchestrator.py -k "parent"` → 全绿
  - `uv run ruff check tests/test_orchestrator.py` → 0 error
- **验收标准**:
  - ✅ 「初始非 1 → 变 1 触发」有真实子进程测试证明（tests:286，rc == EXIT_PARENT_DEAD）
  - ✅ 「出生即 1 不误判 / 未启动 False / 初始非 1 恒等转移」有单元测试证明（tests:273 四断言）
- **潜在风险**: 计数式 mock 若被 `_wait_for_file` 入口外任何代码先调 getppid 会错位——已按 L9832 首行调用顺序核实；如 ruff/平台差异导致 `os.getppid` patch 失败，降级用可变 holder + timer 线程翻 1（备选，仅当计数方案实测失败）。
- **commit**: `[PM #3351] 测试：monitor 初始 PPID 语义改造（273 单元四断言 + 286 转移场景）`（仅 `git add tests/test_orchestrator.py`）

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier（无人挡即刻开工） | 依赖已完成 |
|------|------------|--------------------------|------------|
| W1 | T1.1 | T1.1 | — |
| W2 | T1.2, T2.1 | T1.2（需 T1.1）、T2.1 | T1.1 |
| W3 | T2.2 | T2.2 | T1.2, T2.1 |

并行依据：T1.2 改 tests 文件、T2.1 改 _core.py，文件不相交；T1.1/T2.1 都改 _core.py 故分波串行。失败回滚：每任务独立 commit → 单任务失败仅需 `git revert <该任务 commit>`；修复优先（fix-forward），仅当 _core.py 语义被证伪才回退 T1.1/T2.1。

## Post-Execution Verification

Dev Orchestrator 在全部 plan task 执行完毕后必须运行本节验证。

### Automated Verification（自动执行）

| ID | 描述 | 命令 | 预期 |
|----|------|------|------|
| V1 | 全量测试 | `uv run --group dev pytest` | ≥ 739 passed（预期 740，T1.2 净增 1）、1 skipped、0 failed |
| V2 | 静态检查 | `uv run ruff check src/loop_kit tests` | exit 0，0 error |
| V3 | 编译检查 | `uv run python -m py_compile src/loop_kit/_core.py` | exit 0 |
| V4 | commit 卫生 | `git log --oneline -5` + `git diff HEAD~4 --stat`（或按实际 commit 数） | 仅 2 文件被改；每 commit 含 #3351；无 untracked 文件卷入 |
| V5 | 工作树 | `git status --porcelain` | untracked 集合仍为原 6 项，无新增 tracked 改动 |
| V1b | 术语门（非阻塞） | `de-ai-fier_deai_review_file(path=".github/plans/pm3351-pipe-reader-symmetric-hardening-2026-09-05.md", doc_type="plan", strict=false)` | 术语 finding 记摘要不阻塞；MCP 不可用标注 [⚠️ skipped] |

### Manual（真正需要人工判断）

- [ ] M1: 人工确认 `git status --porcelain` 中 6 个 untracked 文件与任务开始前完全一致（名称逐一核对），未被任何 commit 卷入。

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（每任务 ≤3 文件、边界、验收二元化） | 1（T1.1 初稿漏 stdout 线程化，仅 stderr 加 timeout） | 1 | 0 |
| R1.5 | 外部引用事实核查（L3170-3208/L9790-9817/L454/L3155/测试 177/203/273/286/837 锚点逐一读源确认） | 0 | 0 | 0 |
| R2.8 | LLM 可执行性（命令、路径、断言逐字段可无歧义执行；宽捕获/stash-重抛顺序显式化） | 1（计数式 mock 首调前提未写明 → 补"L9832 首行调用"依据与备选方案） | 1 | 0 |
| R3 | 风险与边缘（并行冲突、os._exit 测试危害、异常契约、zombie 清理、commit 卫生） | 0 | 0 | 0 |
| **终止** | **[T1] — 0 issue 残留** | | | **0** |

## Execution Log

### [2026-09-05] 执行完成（Dev Orchestrator，4/4 任务 ✅）

- **T1.1 ✅**（commit 4236f59）：`_collect_streamed_text_output` 对称加固——stdout/stderr 双 daemon reader 线程 + 有界 join（复用 `_PIPE_READER_JOIN_TIMEOUT_SEC`）+ `stream_error` stash-重抛（保 tests:837 契约）。24 条定向测试全绿。
- **T1.2 ✅**（commit b661dad）：`test_collect_streamed_text_output_returns_when_grandchild_holds_pipe` 真实子进程回归（grandchild 双管持管 15s → collector ~5s 返回）。
- **T2.1 ✅**（commit 88964d3）：`_parent_death_initial_ppid` 模块级记录（锁内、started=True 前赋值）+ 谓词三条件。过渡态 2 条旧测试失败与计划预测完全一致。
- **T2.2 ✅**（commit b415b30）：273 重写为 `test_parent_process_died_initial_ppid_semantics`（4 组断言，无 monitor 线程）；286 重写为计数式 getppid 转移场景（真实子进程 5s 内 exit 7）。
- **Post-Execution Verification**：V1 全量 740 passed/1 skipped/3 deselected（基线 739 + 净增 1）；V2 ruff 0 error；V3 py_compile OK；V4 4 commit 均含 #3351、仅 2 文件；V5 工作树 untracked 仍 7 项（含本计划文件），无新增 tracked 改动。
