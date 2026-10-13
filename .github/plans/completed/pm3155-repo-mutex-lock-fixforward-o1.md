---
plan_id: "pm3155-repo-mutex-lock-fixforward-o1"
mode: "fix-forward"
scope_mode: "HOLD"
title: "PM #3155 CT O1 孤儿孙进程泄漏 —— 测试侧最小 fix-forward"
status: "ready"
parent_plan: "pm3155-repo-mutex-lock"
driven_by: "CT 复核报告 /home/gw/opt/ct-review-pm3155-acceptance.md（2026-09-03，PM #3155 唯一阻塞项 O1 🔴）"
tasks:
  - id: "F1.0"
    phase: 1
    title: "现存孤儿清理（可审计，免误杀）"
    goal: "kill 现存 6 个 --single-round 测试孤儿（PPID=systemd --user），过滤条件三重核对，禁止全局 pkill"
    dependencies: []
    modifications: []
    modify_specs: []
    boundaries: ["禁止 pkill/pkillall 全局匹配", "只 kill 同时满足三重过滤条件的显式 PID 清单", "不动任何源码文件"]
    test_commands: ["pgrep -af '[l]oop_kit run --single-round'"]
    test_expected: ["输出为空（计数 0）"]
    suggested_executor: "Task Executor"
    input_contracts: []
    output_contracts:
      - {type: "state_change", identifier: "system:orphans_cleaned", verification_hint: {type: "grep", pattern: "loop_kit run --single-round", file: "PROC_TABLE", expected_count: "0"}}
    acceptance_criteria:
      - {claim: "孤儿计数归零", verify: "pgrep -af '[l]oop_kit run --single-round'", expected: "空输出"}
  - id: "F1.1"
    phase: 2
    title: "用例 3 进程组修复 + 无孤儿断言"
    goal: "用例 3 改用 Popen(start_new_session=True)+communicate(timeout=60)，超时 killpg+wait，保留超时证据语义，新增 scoped /proc 无孤儿断言"
    dependencies: ["F1.0"]
    modifications: ["tests/test_orchestrator.py"]
    modify_specs:
      - {action: "insert_after", file: "tests/test_orchestrator.py", target: "_loop_run_cmd 函数定义之后（当前 L15195-15205，锚点 `class TestDirtyTreeFailFastNoRetry:` 之前）", description: "插入模块级只读辅助函数 _single_round_orphan_pids(repo)，扫描 /proc/*/cmdline 匹配本测试 .loop/task_card.json 路径，绝不 kill"}
      - {action: "replace", file: "tests/test_orchestrator.py", target: "test_replay_clean_tree_after_release_acquires_normally 函数体（当前 L15327-15355，EOF 前最后一个函数）", description: "替换为 Popen+start_new_session+communicate(timeout=60) 版本，TimeoutExpired 路径 killpg(SIGKILL)+wait+无孤儿断言，完整新旧代码见计划正文 F1.1"}
    boundaries:
      - "只改 tests/test_orchestrator.py 的 T2.3 追加块（L15175 及之后区域）；禁改 src/**；禁改用例 1/2；禁改 _init_tmp_repo/_write_minimal_card/_loop_run_cmd 三个既有 helper 的既有行为"
      - "保留 REFINE-2 超时证据语义（elapsed >= 59.0 断言、PASS 注释）原文不动"
    test_commands: ["uv run --group dev pytest tests/test_orchestrator.py -k 'HistoricalReplay' -v --durations=10"]
    test_expected: ["exit 0（用例 3 走超时证据 PASS 路径）", "pgrep -af '[l]oop_kit run --single-round' 计数 0"]
    suggested_executor: "Task Executor"
    input_contracts:
      - {type: "function", identifier: "_loop_run_cmd", contract_signature: "def _loop_run_cmd(repo: Path, card: Path) -> list[str]"}
    output_contracts:
      - {type: "file", identifier: "tests/test_orchestrator.py", contract_signature: "case 3 不再泄漏孙进程；exports _single_round_orphan_pids"}
    acceptance_criteria:
      - {claim: "用例 3 超时证据语义不变且无孤儿", verify: "pytest -k 'HistoricalReplay' -v 连跑两遍 + pgrep 计数", expected: "两遍均 exit 0 且每遍后孤儿计数 0"}
      - {claim: "用例 1/2 语义不变", verify: "pytest -k 'HistoricalReplay' -v 输出", expected: "returncode 4/5 断言与 elapsed<10 断言仍在且通过"}
  - id: "F1.2"
    phase: 2
    title: "父计划 O2/O3 文本勘误"
    goal: "父计划 pm3155-repo-mutex-lock.md 六处文本勘误（O2 三处+一处同类、O3 两处），纯文本编辑，不进 commit"
    dependencies: []
    modifications: [".github/plans/pm3155-repo-mutex-lock.md"]
    modify_specs:
      - {action: "replace", file: ".github/plans/pm3155-repo-mutex-lock.md", target: "L189 frontmatter acceptance", description: "expected 字段「各回放用例 <10s」→「用例 1/2 <10s，用例 3 走 REFINE-2 超时证据语义（60s 上限）」"}
      - {action: "replace", file: ".github/plans/pm3155-repo-mutex-lock.md", target: "L273 验收汇总", description: "「历史回放三用例 <10s，用例 3 TimeoutExpired=超时证据 PASS」→「历史回放用例 1/2 <10s，用例 3 60s TimeoutExpired=超时证据 PASS（REFINE-2 口径）」"}
      - {action: "replace", file: ".github/plans/pm3155-repo-mutex-lock.md", target: "L604 T2.3 测试要求", description: "「exit 0 且各回放 <10s」→「exit 0 且用例 1/2 <10s，用例 3 60s 超时证据 PASS」"}
      - {action: "replace", file: ".github/plans/pm3155-repo-mutex-lock.md", target: "L607 T2.3 验收标准（同类矛盾，CT 未点名但同口径）", description: "「历史回放三用例通过且 <10s」→「历史回放用例 1/2 通过且 <10s，用例 3 60s 超时证据 PASS」"}
      - {action: "replace", file: ".github/plans/pm3155-repo-mutex-lock.md", target: "L277 回滚步骤 1", description: "「每个 task 一个 commit，共 7 个」→「每个 task 一个 commit，T1.2 因 fix-forward 拆为 2 个，共 8 个；本 fix-forward 计划追加 1 个 commit 后共 9 个，回滚先 revert 该 fix-forward commit」"}
      - {action: "replace", file: ".github/plans/pm3155-repo-mutex-lock.md", target: "L278 回滚步骤 2 逆序清单", description: "「→ T1.3 → T1.2 → T1.1 → T1.0」→「→ T1.3 → T1.2-fix-forward(037a6d1) → T1.2(3e9f9fb) → T1.1 → T1.0」"}
    boundaries:
      - "仅上述 6 处文本；不改父计划 context 快照字段；不触碰另两个 pre-existing untracked；严禁 git add 该文件"
    test_commands: ["grep -n '共 8 个\\|037a6d1\\|用例 1/2 <10s' .github/plans/pm3155-repo-mutex-lock.md"]
    test_expected: ["命中 L189/L273/L277/L278/L604/L607 六处新文本"]
    suggested_executor: "Task Executor"
    input_contracts: []
    output_contracts:
      - {type: "file", identifier: ".github/plans/pm3155-repo-mutex-lock.md", contract_signature: "O2/O3 口径勘误完成，文件保持 untracked"}
    acceptance_criteria:
      - {claim: "六处勘误落地且文件保持 untracked", verify: "grep 六处 + git status --porcelain", expected: "命中且 ?? .github/plans/pm3155-repo-mutex-lock.md 不变"}
  - id: "F1.3"
    phase: 3
    title: "定向+全量验证、无孤儿复核、提交"
    goal: "两遍定向回归 + pgrep 无孤儿复核 + 全量 pytest + ruff + 单文件 commit（仅 tests/test_orchestrator.py）"
    dependencies: ["F1.0", "F1.1"]
    modifications: []
    modify_specs: []
    boundaries:
      - "git add 仅 tests/test_orchestrator.py（禁止 git add -A/.）；3 个 pre-existing untracked 与本计划文件自身绝不进 commit"
      - "不直接写 PM（PM 状态更新经 pm-coordinator 委派，见 F1.4 建议项）"
    test_commands:
      - "uv run --group dev pytest tests/test_orchestrator.py -k 'HistoricalReplay' -v（连跑两遍，每遍后跑 pgrep 计数）"
      - "uv run --group dev pytest -q"
      - "uv run ruff check src/loop_kit tests"
    test_expected: ["两遍 exit 0 且两遍后 pgrep 计数 0", "exit 0，0 failed", "exit 0，0 errors"]
    suggested_executor: "Task Executor"
    input_contracts: []
    output_contracts:
      - {type: "state_change", identifier: "git:committed", verification_hint: {type: "grep", pattern: "fix-forward: reap single-round grandchild", file: "REPO", expected_count: "1"}}
    acceptance_criteria:
      - {claim: "定向两遍零孤儿", verify: "见 test_commands", expected: "true"}
      - {claim: "全量零回归", verify: "uv run --group dev pytest -q", expected: "exit 0"}
      - {claim: "生产代码零改动", verify: "git diff HEAD --stat -- src/", expected: "空输出"}
      - {claim: "提交范围仅 1 文件", verify: "git show --stat --oneline HEAD", expected: "仅 tests/test_orchestrator.py"}
      - {claim: "untracked 保护", verify: "git status --porcelain", expected: "4 个 untracked（3 原有 + 本计划文件），biweekly 计划 sha256 与基线一致"}
  - id: "F1.4"
    phase: 4
    title: "PM 闭环与生产侧 follow-up（建议项，非阻塞）"
    goal: "经 pm-coordinator 更新 PM #3155（notes 记录 O1 fix-forward commit + O2/O3 口径）；建议新建生产侧 parent-death 传播缺口 follow-up 任务（引用 5dcb859）"
    dependencies: ["F1.3"]
    modifications: []
    modify_specs: []
    boundaries: ["仅建议动作，须经 pm-coordinator 委派，PA 不直接调用 PM 写工具；用户未确认则跳过"]
    test_commands: []
    test_expected: []
    suggested_executor: "pm-coordinator（委派）"
    input_contracts: []
    output_contracts: []
    acceptance_criteria: []
context:
  repo_path: "/home/gw/opt/agent-task-runner"
  repo_path_source: "[推断] PM #3155 tasks.workspace=null；2026-09-03 实测核对：git HEAD=eb5e6e6、父计划 8 commits 全在库、生产树零 diff"
  untracked_items: [".github/plans/biweekly-reporting-restore-2026-08-27.md", ".github/plans/pm3155-repo-mutex-lock.md（父计划，F1.2 勘误对象）", "data/"]
  git_commit: "eb5e6e6c0b6559a119fffeb8df10edfc0cc92a92（生成时快照，执行时重测）"
  generated_at: "2026-09-03T14:10:00Z"
  files:
    - {path: "tests/test_orchestrator.py", sha256: "77cbbb99db7d81c4e09bcc3b4ae5e84bcee4250cca611f59cb4ab66397be5a2b（生成时快照，执行时重测）"}
    - {path: ".github/plans/biweekly-reporting-restore-2026-08-27.md", sha256: "a728b78212a74b6944c1a966241e4024fd59b6b904ff3f86881cd6171e085946（保护基线，执行时重测）"}
---

# PM #3155 CT O1 孤儿孙进程泄漏 —— 测试侧最小 fix-forward（HOLD）

## 背景与目标

- **问题/需求描述**：CT 复核报告（`/home/gw/opt/ct-review-pm3155-acceptance.md`，2026-09-03）确认 PM #3155 唯一阻塞项 O1 🔴：`tests/test_orchestrator.py` 用例 3（`test_replay_clean_tree_after_release_acquires_normally`，当前 L15327-15355）用 `subprocess.run(timeout=60)` 启动 `loop run` 多轮父进程，父进程在 `_core.py:12530` 用无 `start_new_session` 的 `Popen` 派生 `--single-round` 孙进程；60s 超时后 `subprocess.run` 只 SIGKILL 直接子进程，孙进程被 reparent 到 `systemd --user`（pid=2875）无界存活。**本机实测现存 6 个孤儿**（PID 1103167/1139997/1205676/1460274/1545127/1603532，etime 17min–30min，每跑一次套件泄漏一个）。
- **根因分析**：测试侧 = 超时只杀直接子进程、无进程组语义（`subprocess.run(timeout=)` 不保证孙进程回收）。生产侧 = multi-round→single-round 子进程无 parent-death 传播（blame `5dcb859`，T-722 引入）——**既有架构缺口，本计划禁止触碰**（另开 follow-up，见 F1.4）。
- **目标**：
  1. 用例 3 改用 `Popen(start_new_session=True)` + `communicate(timeout=60)`；超时路径 `killpg(SIGKILL)` + `wait()`，捕获 `ProcessLookupError`；孙进程随进程组一并回收
  2. 新增 scoped 无孤儿断言（只读 `/proc` 扫描，按本测试唯一 tmp card 路径匹配，绝不误伤/误报）
  3. 父计划 O2/O3 文本勘误（六处）
  4. 现存 6 个孤儿按可审计流程清理
- **非目标（不做什么）**：
  - ❌ 不改任何生产源码（`src/**` 零 diff 是验收条件）
  - ❌ 不修生产侧 parent-death 缺口（PDEATHSIG/父 pid 轮询），属 follow-up 任务
  - ❌ 不改用例 1/2（`test_replay_t3151_dirty_tree_fails_once_fast`、`test_replay_repo_lock_conflict_exits_5_fast`）任何一行
  - ❌ 不触碰 3 个 pre-existing untracked（`.github/plans/biweekly-reporting-restore-2026-08-27.md`、`.github/plans/pm3155-repo-mutex-lock.md` 除 F1.2 六处勘误外、`data/`）
  - ❌ 不直接写 PM（状态更新经 pm-coordinator，F1.4 建议项）

## 修改方案

### 方案概述

单文件测试侧修复 + 父计划文档勘误 + 系统态孤儿清理，三件套。核心是把用例 3 的子进程放入**独立进程组**（`start_new_session=True`），使超时回收从"杀直接子进程"升级为"杀整组"（子+孙），并用一个**路径锚定**的 `/proc` 只读扫描把卫生保证变成可回归断言。

### 关键设计决策

| # | 决策 | 理由 | 备选（已否决） |
|---|------|------|----------------|
| F-D1 | `start_new_session=True` + 超时 `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` + `proc.wait()` | 子进程成为组长（pgid=子 pid），孙进程继承该组；killpg 只作用于本测试组，无旁杀风险（组内仅本测试派生的进程）。CT 报告明确指定此形态 | ①生产侧加 PDEATHSIG → 触碰生产代码，越界；②`subprocess.run` 继续用 → 泄漏不变；③kill 后不 wait → 僵尸进程 |
| F-D2 | 无孤儿断言用**只读** `/proc/*/cmdline` 扫描，匹配 `str(repo/".loop"/"task_card.json")`（孙进程实际 --task 参数，经 CT 证据校准，**不是** 测试侧传入的 `repo/card.json`） | 锚定唯一 pytest tmp 路径 → 历史上累积的旧孤儿（指向已删 tmp 目录）不误报、并行场景无假阳性；只读扫描绝不 kill，满足"不得误杀无关进程" | 用 `pgrep -f` 全局匹配 → 匹配到无关真实 loop run 或自身 shell 包装器；在测试内 kill 扫描结果 → 越权误杀风险 |
| F-D3 | `ProcessLookupError` 用 `contextlib.suppress` 包裹（文件已 import contextlib，L5） | 子进程恰在 60s 边界自退时 `getpgid` 抛 ESRCH；且规避 ruff SIM105（select 含 SIM，`try/except: pass` 会挂 lint） | 裸 `try/except ProcessLookupError: pass` → SIM105 lint 失败 |
| F-D4 | 超时证据语义（REFINE-2）**逐字保留**：`elapsed >= 59.0` 断言 + PASS 注释 + 非超时路径 `returncode not in (4,5)` | O1 修复只补回收，不改验收语义；用例 3 的 PASS 判定仍由超时证据承载 | 超时改为 FAIL → 破坏父计划 REFINE-2 设计 |
| F-D5 | 现存孤儿清理：三重过滤（cmdline 含 `loop_kit run --single-round` ∧ `pytest-of-` ∧ `test_replay_clean_tree_after_r`；PPID == systemd --user 执行时实测值）+ 显式 PID 清单 `kill -TERM`→2s→存活才 `-9` | 可审计、免误杀；若 PPID 不符或 cmdline 不匹配任何一条 → 记录并跳过，人工确认 | `pkill -f 'loop_kit'` 全局 → 可能误杀真实 loop run，禁止 |
| F-D6 | F1.2 勘误共**六处**（CT 点名 L189/L273/L604 + 同类 L607 + O3 L277/L278）；L277 追加 fix-forward commit 交叉引用 | CT 点名三处之外 L607 存在同一矛盾口径，一并修正；追加交叉引用使父计划回滚规程在本计划提交后仍自洽 | 只改 CT 点名三处 → L607 残留矛盾；不加交叉引用 → 父计划"共 8 个"在 9 commits 后再次失准 |

### 假设标注

1. `[假设: 孙进程不自行 setsid]` — CT 机制链实测 `_core.py:12530` 的 Popen 无 `start_new_session`，孙进程继承子进程组。若未来生产代码给该 Popen 加了 setsid，killpg 仍安全（只少回收一个孙，无孤儿断言会 FAIL 暴露），测试不会静默通过。影响：中。
2. `[假设: 测试串行执行]` — pyproject 无 xdist/addopts 无 `-n`（已实测核对），`/proc` 扫描无跨 worker 干扰。影响：低。
3. `[假设: /proc 可见性]` — 环境为 Linux（/proc 存在）。helper 对 vanish 进程用 OSError 吞掉。影响：低。
4. `[假设: systemd --user 是孤儿唯一 reparent 目标]` — 实测 6 个孤儿 PPID 全为 2875。F1.0 执行时重测，不符则跳过该 pid。影响：低。

## 授权归因（硬规则三要素）

| 要素 | 证据 |
|------|------|
| ①授权主体 | 用户（本会话发起者） |
| ②授权时点与载体 | 本会话消息（2026-09-03）：明确要求"为 PM #3155 唯一阻塞 O1 制定最小 fix-forward 方案"，并逐条指定 killpg/清理孤儿/无孤儿断言/勘误/保护 untracked |
| ③授权范围 | 仅测试侧单文件修复、按三重过滤条件清理现存测试孤儿、父计划六处文本勘误、建议（非执行）PM 状态更新。**不含**生产代码改动、不含 D2 门控类声明（本计划无门控涉及） |

## 执行计划

每个 Phase 第一步为**基线漂移重检**（动态基线：HEAD、孤儿计数、文件 sha256、行号锚点一律执行时重测，不沿用快照值）。

### Phase 1: 现存孤儿清理（F1.0）

**基线漂移重检**：`git rev-parse HEAD`（应=eb5e6e6）；`pgrep -af '[l]oop_kit run --single-round'` 重新枚举（2026-09-03 快照 6 个，数量可能已变）；`pgrep -u "$USER" -x systemd` 重测 reparent 目标 pid（快照 2875）。

#### Task F1.0: 现存孤儿清理（可审计，免误杀）

- **目标**：kill 现存 `--single-round` 测试孤儿，全程可审计、绝不误杀无关进程
- **依赖**：无
- **frontier**：是
- **执行者**：Task Executor
- **修改内容**：无文件修改（纯系统态操作）。**精确步骤**：
  1. 枚举：`pgrep -af '[l]oop_kit run --single-round'`（方括号模式防 pgrep 自匹配）
  2. 过滤（**三重条件全部满足**才入 kill 清单）：cmdline 含 `loop_kit run --single-round` ∧ 含 `pytest-of-` ∧ 含 `test_replay_clean_tree_after_r`；且 `ps -o ppid= -p <pid>` 等于第 0 步重测的 systemd --user pid。任一不满足 → 不入清单，记录后跳过并人工确认
  3. 复核清单：逐条打印 `ps -o pid=,ppid=,etime=,cmd= -p <pid>` 作为审计痕迹留存到任务回执
  4. 清理：`kill -TERM <pid1> <pid2> ...`（显式 PID 清单，**禁止 pkill/pkillall**）→ `sleep 2` → 对 `kill -0` 仍存活者 `kill -9 <pid>`
  5. 验证：`pgrep -af '[l]oop_kit run --single-round'` 输出为空
- **修改边界**：⛔ 禁止 `pkill`/`pkillall` 全局匹配；⛔ 禁止 kill 任何不满足三重过滤的 pid；⛔ 不动任何文件
- **质量检查方式**：kill 清单与过滤依据逐条记录；清理前后计数对比
- **验收标准**：
  - ✅ `pgrep -af '[l]oop_kit run --single-round'` 计数 == 0
  - ✅ 审计记录含每个被 kill pid 的三重过滤证据
- **潜在风险**：若存在不满足过滤条件的 `--single-round` 进程（真实 loop run），跳过不 kill 并上报；孤儿为测试残留、无锁无状态，TERM/KILL 无副作用
- **预留歧义标注**：
  - [x] 无歧义：命令逐字给出

### Phase 2: 测试侧修复 + 计划勘误（F1.1 / F1.2，可并行）

**基线漂移重检**：`git status --porcelain`（应仅 3 个 untracked）；`git diff HEAD --stat -- src/` 为空（生产零改动）；`sha256sum tests/test_orchestrator.py` 应=77cbbb99…（若漂移，先 diff 定位漂移源再动手）；父计划六处锚点行号 grep 复核。

#### Task F1.1: 用例 3 进程组修复 + 无孤儿断言

- **目标**：用例 3 超时路径回收整进程组 + scoped 无孤儿断言，超时证据语义逐字保留
- **依赖**：F1.0（干净基线，否则 pgrep 验收被历史孤儿污染）
- **frontier**：否（依赖 F1.0）
- **执行者**：Task Executor
- **修改内容**（仅 `tests/test_orchestrator.py`，T2.3 追加块内，两处编辑）：

  **编辑 1 — insert_after `_loop_run_cmd`（锚点：其定义结束于 `    ]`，下一行为空行+`class TestDirtyTreeFailFastNoRetry:`）**，插入：

```python
def _single_round_orphan_pids(repo: Path) -> list[int]:
    """Read-only /proc scan for --single-round loop runs referencing this test's
    task card (CT O1 regression guard). Scoped to the unique pytest tmp card
    path, so unrelated processes can never match -- and this helper never kills
    anything. Linux-only, matching the CI/dev environment."""
    marker = str(repo / ".loop" / "task_card.json")
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue  # process vanished between readdir and read
        cmdline = raw.replace(b"\x00", b" ").decode("utf-8", "replace")
        if "--single-round" in cmdline and marker in cmdline:
            found.append(int(entry.name))
    return found
```

  **编辑 2 — replace `test_replay_clean_tree_after_release_acquires_normally` 函数体（旧：L15327-15355）**。旧文（逐字）：

```python
    def test_replay_clean_tree_after_release_acquires_normally(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo3"
        _init_tmp_repo(repo)
        card = _write_minimal_card(repo, "T-3152B")

        start = time.monotonic()
        try:
            result = subprocess.run(
                _loop_run_cmd(repo, card),
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            # Timeout-evidence semantics (REFINE-2): not exiting within 60s means
            # the subprocess passed the repo lock (no exit 5) and the dirty-tree
            # check (no exit 4) and entered later loop stages that wait on PM
            # dependencies unavailable in this environment. That is a PASS for
            # this case's goal: after release the lock is free and a clean tree
            # proceeds past the fail-fast gates.
            elapsed = time.monotonic() - start
            assert elapsed >= 59.0, f"timeout fired unexpectedly early: {elapsed:.1f}s"
            return
        elapsed = time.monotonic() - start
        assert result.returncode not in (4, 5), (
            f"clean tree must pass the dirty check (not 4) and the repo lock (not 5); "
            f"got {result.returncode}. stderr: {result.stderr[-500:]}"
        )
```

  新文（逐字，行宽 ≤120，ruff E/F/W/I/UP/B/SIM/RUF 全绿）：

```python
    def test_replay_clean_tree_after_release_acquires_normally(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo3"
        _init_tmp_repo(repo)
        card = _write_minimal_card(repo, "T-3152B")

        # CT O1 fix-forward: run in a dedicated process group. The multi-round
        # parent spawns a --single-round grandchild (subprocess.Popen in _core.py
        # has no start_new_session), which subprocess.run(timeout=60) left behind
        # as an orphan reparented to systemd --user. start_new_session=True makes
        # the child a group leader, so the timeout path can killpg the whole
        # group -- child and grandchild -- with no risk to unrelated processes.
        start = time.monotonic()
        proc = subprocess.Popen(
            _loop_run_cmd(repo, card),
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            _stdout, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            # Timeout-evidence semantics (REFINE-2): not exiting within 60s means
            # the subprocess passed the repo lock (no exit 5) and the dirty-tree
            # check (no exit 4) and entered later loop stages that wait on PM
            # dependencies unavailable in this environment. That is a PASS for
            # this case's goal: after release the lock is free and a clean tree
            # proceeds past the fail-fast gates. Before declaring PASS, reap the
            # whole process group so no grandchild leaks (O1); ProcessLookupError
            # covers the child exiting exactly at the 60s boundary.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()  # reap the direct child (group already killed)
            elapsed = time.monotonic() - start
            assert elapsed >= 59.0, f"timeout fired unexpectedly early: {elapsed:.1f}s"
            orphans = _single_round_orphan_pids(repo)
            assert not orphans, f"single-round grandchild leaked after group kill: {orphans}"
            return
        elapsed = time.monotonic() - start
        assert proc.returncode not in (4, 5), (
            f"clean tree must pass the dirty check (not 4) and the repo lock (not 5); "
            f"got {proc.returncode}. stderr: {stderr[-500:]}"
        )
```

- **修改边界**：⛔ 禁改 `src/**`；⛔ 禁改用例 1/2 与三个既有 helper（`_init_tmp_repo`/`_write_minimal_card`/`_loop_run_cmd`）；⛔ 禁改 REFINE-2 注释语义句；⛔ 不在测试内 kill 扫描到的任何进程
- **质量检查方式**：
  - 检查项 1：`grep -n "start_new_session\|killpg\|_single_round_orphan_pids" tests/test_orchestrator.py` 三处命中
  - 检查项 2：`uv run ruff check tests` exit 0（SIM105 已用 suppress 规避；`_stdout` 走 dummy-variable-rgx 豁免）
  - 检查项 3：`git diff --stat` 仅 tests/test_orchestrator.py 一个文件
- **验收标准**：
  - ✅ `uv run --group dev pytest tests/test_orchestrator.py -k 'HistoricalReplay' -v --durations=10` exit 0（用例 3 走超时证据 PASS 路径）
  - ✅ 测试结束后 `pgrep -af '[l]oop_kit run --single-round'` 计数 == 0
  - ✅ 用例 1/2 的 `returncode 4/5`、`elapsed < 10` 断言仍在且通过（`pytest -k 'HistoricalReplay' -v` 输出可查）
- **潜在风险**：`communicate(timeout=)` 内部先 SIGKILL 子进程再抛 TimeoutExpired（Python 3.11 行为），此时孙进程仍在；我们随后 killpg 补杀整组——顺序正确。若孙进程未来自行 setsid，killpg 少杀一个，无孤儿断言会 FAIL 显性暴露（fail-loud，不静默）
- **预留歧义标注**：
  - [x] 无歧义：新旧代码逐字给出，锚点唯一

#### Task F1.2: 父计划 O2/O3 文本勘误

- **目标**：父计划 `.github/plans/pm3155-repo-mutex-lock.md` 六处文本勘误（O2 口径 + O3 计数/回滚顺序）
- **依赖**：无
- **frontier**：是（与 F1.1 文件不相交，可并行）
- **执行者**：Task Executor
- **修改内容**：仅父计划文件六处 replace（**old → new 逐字**，每处 old 串全文唯一）：
  1. L189：`expected: "exit 0，各回放用例 <10s"` → `expected: "exit 0，用例 1/2 <10s，用例 3 走 REFINE-2 超时证据语义（60s 上限）"`
  2. L273：`T2.3（脏树单次失败 + 历史回放三用例 <10s，用例 3 TimeoutExpired=超时证据 PASS）` → `T2.3（脏树单次失败 + 历史回放用例 1/2 <10s，用例 3 60s TimeoutExpired=超时证据 PASS，REFINE-2 口径）`
  3. L604：`→ exit 0 且各回放 <10s。` → `→ exit 0 且用例 1/2 <10s，用例 3 60s 超时证据 PASS。`
  4. L607：`  - claim: 历史回放三用例通过且 <10s → verify: pytest -k 'HistoricalReplay' -v --durations=10 → expected: exit 0` → `  - claim: 历史回放用例 1/2 通过且 <10s，用例 3 60s 超时证据 PASS → verify: pytest -k 'HistoricalReplay' -v --durations=10 → expected: exit 0`
  5. L277：`（每个 task 一个 commit，共 7 个）` → `（每个 task 一个 commit，T1.2 因 fix-forward 拆为 2 个，共 8 个；fix-forward 计划 pm3155-repo-mutex-lock-fixforward-o1 追加 1 个 commit 后共 9 个，回滚先 revert 该 fix-forward commit）`
  6. L278：`→ T2.3 → T2.2 → T2.1 → T1.3 → T1.2 → T1.1 → T1.0` → `→ T2.3 → T2.2 → T2.1 → T1.3 → T1.2-fix-forward(037a6d1) → T1.2(3e9f9fb) → T1.1 → T1.0`
- **修改边界**：⛔ 仅上述六处；⛔ 不改父计划 context 快照字段；⛔ 不触碰另两个 untracked；⛔ 严禁 `git add` 该文件
- **质量检查方式**：`grep -n '共 8 个\|037a6d1\|用例 1/2 <10s' .github/plans/pm3155-repo-mutex-lock.md` 六处命中；改前 `cp .github/plans/pm3155-repo-mutex-lock.md /tmp/pm3155-repo-mutex-lock.md.fixforward-bak`（备份落 /tmp，避免污染 git status）
- **验收标准**：
  - ✅ 六处新文本 grep 命中，旧口径（`各回放用例 <10s`、`共 7 个`）零残留
  - ✅ `git status --porcelain` 中该文件仍为 `??`（untracked 不变）
- **潜在风险**：父计划是 untracked 纯文本，改错可从 /tmp 备份秒级还原
- **预留歧义标注**：
  - [x] 无歧义：old/new 逐字给出

### Phase 3: 验证与提交（F1.3）

**基线漂移重检**：`git rev-parse HEAD`（应=eb5e6e6）；`git status --porcelain`（应=3 untracked + tests 修改 + 本计划文件 `??`）；`pgrep -af '[l]oop_kit run --single-round'` 应=0（F1.0 已清）。

#### Task F1.3: 定向+全量验证、无孤儿复核、提交

- **目标**：两遍定向回归 + 每遍后无孤儿复核 + 全量 pytest + ruff + 单文件 commit
- **依赖**：F1.0、F1.1
- **frontier**：否
- **执行者**：Task Executor
- **修改内容**：无文件内容修改。**精确步骤**：
  1. `uv run --group dev pytest tests/test_orchestrator.py -k 'HistoricalReplay' -v` → exit 0 → `pgrep -af '[l]oop_kit run --single-round' | wc -l` 记数（应 0）
  2. 重复第 1 步一遍（连跑两遍语义，防单次侥幸）→ 两遍后计数均 0
  3. `uv run --group dev pytest -q` → exit 0
  4. `uv run ruff check src/loop_kit tests` → exit 0
  5. `git diff HEAD --stat -- src/` → 空（生产零改动证据）
  6. `git add tests/test_orchestrator.py`（**仅此一文件，禁止 `git add -A`/`.`**）
  7. `git diff --cached --stat` 负向验证：仅 tests/test_orchestrator.py
  8. commit：`[Plan: pm3155-repo-mutex-lock] T2.3 fix-forward: reap single-round grandchild via process group (CT O1)`
  9. commit 后复核：`git status --porcelain` == 4 个 untracked（3 原有 + 本计划文件自身）；`sha256sum .github/plans/biweekly-reporting-restore-2026-08-27.md` 与基线 a728b782…一致
- **修改边界**：⛔ 提交范围仅 tests/test_orchestrator.py；⛔ 不直接调 PM 写工具
- **质量检查方式**：步骤 5/7/9 为负向验证三道闸
- **验收标准**：
  - ✅ 两遍定向均 exit 0 且两遍后孤儿计数 0
  - ✅ 全量 pytest exit 0、ruff exit 0
  - ✅ `git show --stat --oneline HEAD` 仅 tests/test_orchestrator.py
  - ✅ `git diff HEAD --stat -- src/` 空
  - ✅ 3 个 pre-existing untracked 原样（biweekly 计划 sha256 一致）
- **潜在风险**：全量 615+ 用例耗时较长（TE 设 timeout ≥ 15min）；用例 3 每次定向跑 ~60s（两遍 + 全量内一遍共 ~3 分钟），属预期开销
- **预留歧义标注**：
  - [x] 无歧义：命令逐字给出

### Phase 4: PM 闭环（F1.4，建议项）

#### Task F1.4: PM 闭环与生产侧 follow-up（建议项，非阻塞）

- **目标**：经 pm-coordinator 委派：①更新 PM #3155 notes（记录 O1 fix-forward commit sha、O2/O3 口径「用例 1/2 <10s、用例 3 60s 超时证据、共 8+1 commits」）并可置 done；②建议新建 agent-task-runner 生产侧 follow-up 任务（parent-death 传播缺口，引用 `5dcb859`）
- **依赖**：F1.3
- **frontier**：否
- **执行者**：pm-coordinator（委派）
- **修改内容**：无文件修改（PM 系统写操作，须委派）
- **修改边界**：⛔ 仅建议动作；用户未确认则跳过；PA/TE 不得直接调用 `project-management/*` 工具
- **验收标准**：（可选）PM #3155 done + follow-up 任务已建，notes 含口径记录
- **潜在风险**：无（可跳过不影响 O1 修复完整性）

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|------------|
| W1 | F1.0 + F1.2 | F1.0, F1.2 | — |
| W2 | F1.1 | —（需干净孤儿基线） | W1: F1.0 |
| W3 | F1.3 | — | W2: F1.1 |
| W4 | F1.4（建议） | — | W3: F1.3 |

**排序理由（CoT Stage 4）**：F1.0 先于 F1.1 因为 F1.1 的 pgrep 验收需干净基线（历史孤儿会污染计数）；F1.2 与 F1.1 文件不相交（untracked 计划 vs tracked 测试）故可并行；F1.3 聚合验证依赖 F1.1 完成；F1.4 纯建议项尾置。**无跨项目阻塞依赖**（PM #3155 状态更新为建议动作；生产侧缺口另开任务不阻塞）。

## Post-Execution Verification

### Automated Verification（Task Executor 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量单元测试（排除 e2e） | `uv run --group dev pytest -q` | exit 0，0 failed |
| V2 | lint 全仓 | `uv run ruff check src/loop_kit tests` | exit 0，0 errors |
| V3 | 定向回归 ×2 + 无孤儿 | `uv run --group dev pytest tests/test_orchestrator.py -k 'HistoricalReplay' -v` ×2，每遍后 `pgrep -af '[l]oop_kit run --single-round' | wc -l` | 两遍 exit 0 且计数均 0 |
| V4 | 生产零改动 | `git diff HEAD --stat -- src/` | 空输出 |

### Probe (best-effort, run if available)

- [ ] P1: `pgrep -af '[l]oop_kit run --single-round'` — 期望空；非空则列清单人工裁决（若命中真实 loop run 而非 pytest 路径 → 非本计划泄漏，上报）

### Manual（真正需要人工判断）

- [ ] M1: 人工复核 commit message 与 `git show --stat HEAD` 范围声明一致（1 文件 1 语义）

## 回滚操作手册

1. **F1.3 commit 回滚**：`git revert <F1.3-commit-sha>`（单文件单块，与父计划其余 commit 无文本重叠，可独立 revert）
2. **与父计划回滚链组合时**：先 revert 本 fix-forward commit，再按父计划 L278（已勘误）逆序：`T2.3 → T2.2 → T2.1 → T1.3 → T1.2-fix-forward(037a6d1) → T1.2(3e9f9fb) → T1.1 → T1.0`。**顺序不可乱**：037a6d1 与 3e9f9fb 重写同一段 try/finally，逆序 revert 3e9f9fb 会冲突
3. **F1.2 勘误回滚**：父计划为 untracked，从 `/tmp/pm3155-repo-mutex-lock.md.fixforward-bak` 还原
4. **F1.0 无回滚**：kill 不可逆，但孤儿为无锁无状态测试残留，无数据损失
5. **禁止**：`git reset` 任何 commit；触碰 3 个 pre-existing untracked；`git add -A`

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（背景/目标/非目标/方案/影响范围） | 0 | 0 | 0 |
| R1.5 | 外部引用事实核查 | 2 | 2 | 0 |
| R2 | 可执行性（命令逐字、锚点唯一性、ruff 门禁干跑推演） | 2 | 2 | 0 |
| R2.8 | LLM 可执行性（字段歧义、边界漏项、contract 可执行性） | 1 | 1 | 0 |
| R3 | 风险与边缘（含跨轮一致性、回滚顺序、误杀面） | 0 | 0 | 0 |
| **终止** | **[T1] — R3 零新增且前置轮 issue 全部闭环** | | | **0** |

**R1.5 明细**：①孤儿扫描标记路径——孙进程 cmdline 实测为 `repo3/.loop/task_card.json`（CT 证据），非测试侧传入的 `repo3/card.json`；helper 已按 `.loop/task_card.json` 校准（F-D2）。②`contextlib` 已 import（L5）、`os`/`signal` 已 import（L8-9）、pyproject 无 xdist、systemd --user=2875 实测，全部与方案假设一致。

**R2 明细**：①`try/except ProcessLookupError: pass` 会触发 ruff SIM105（select 含 SIM）→ 改 `contextlib.suppress`（F-D3）。②`stdout` 未用变量触发 F841 → 改名 `_stdout` 走 dummy-variable-rgx 豁免。

**R2.8 明细**：F1.0 的 pgrep 自匹配风险（shell 包装器 cmdline 含模式串）→ 全部验证命令改用 `[l]oop_kit` 方括号模式；该细节已逐字写入计划，消除下游猜测。

**[Red-Team 记录]**：本计划 4 Task ≥3，默认开启。前置 CT 复核报告（`/home/gw/opt/ct-review-pm3155-acceptance.md`）已覆盖方案级对抗复核；另自行执行 3-lens：Prompt Injection（无用户输入进入命令/代码路径，孤儿清理只用 pgrep 输出做三重过滤→无注入面）；Silent Failure（killpg 边界竞态→suppress+wait 兜底；/proc 扫描竞态→OSError 吞；pgrep 自匹配→方括号模式）；Cross-Task Drift（F1.0 干净基线→F1.1/F1.3 计数验收；F1.2 勘误→父计划回滚规程与 F1.3 后 9-commit 状态自洽）。0 个 Medium+ finding。

## 交叉项目依赖检查

本计划无跨项目阻塞依赖：PM #3155 状态更新为建议动作（F1.4，经 pm-coordinator）；生产侧 parent-death 缺口另开 follow-up 任务（不阻塞）；全部文件落点在本仓 `/home/gw/opt/agent-task-runner`。
