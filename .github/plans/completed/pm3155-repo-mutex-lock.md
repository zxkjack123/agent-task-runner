---
plan_schema_version: "1.1"
scope_mode: HOLD
pm_task: 3155
waves:
  - wave: 1
    tasks: [T1.0, T1.1]
  - wave: 2
    tasks: [T1.2, T1.3]
    depends_on: [wave: 1]
  - wave: 3
    tasks: [T2.1]
    depends_on: [wave: 2]
  - wave: 4
    tasks: [T2.2]
    depends_on: [wave: 3]
  - wave: 5
    tasks: [T2.3]
    depends_on: [wave: 4]
  - wave: 6
    tasks: [T3.1]
    depends_on: [wave: 5]
phases:
  - id: "Phase 1"
    title: "repo 级互斥锁实现（src/loop_kit/）"
    tasks:
      - id: "T1.0"
        phase: 1
        title: "_git_at porcelain 输出剥离修复（脏树检测正确性前置，REFINE-1 新增）"
        goal: "修复 _git_at 返回值的 .strip() 剥离 porcelain XY 前导空格导致 _dirty_tracked_paths 解析错位（1-2 字符路径被静默忽略、>=3 字符路径首字符被吞）的缺陷，使脏树 fail-fast 的『列出脏文件清单』语义在回放测试（T2.3/V6）下正确成立"
        dependencies: []
        modifications: ["src/loop_kit/_core.py"]
        modify_specs:
          - {action: "replace_line", file: "src/loop_kit/_core.py", target: "当前 L6882 `    return result.stdout.strip()`（函数 _git_at 唯一 return，锚文本唯一）", description: "改为 `    return result.stdout.rstrip()`。仅此一行，不改函数其余逻辑"}
        boundaries:
          - "仅允许修改 _git_at 的 return 行（L6882），不得修改 _LoopLock（L1254-1299）、_cleanup_stale_lock（L1310-1329）、_enforce_clean_worktree_or_exit（L8860-8904）及 _dirty_tracked_paths 本身"
          - "不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围，不得修改 tests/ 与其他模块"
        test_commands: ["uv run python -m py_compile src/loop_kit/_core.py", "bash -c 'tmp=$(mktemp -d) && git -C \"$tmp\" init -q && git -C \"$tmp\" config user.email t@t && git -C \"$tmp\" config user.name t && echo x > \"$tmp/f\" && git -C \"$tmp\" add -A && git -C \"$tmp\" commit -qm i && echo y >> \"$tmp/f\" && cd \"$tmp\" && uv run --project /home/gw/opt/agent-task-runner python -c \"import loop_kit._core as c; assert c._dirty_tracked_paths() == [\\\"f\\\"], c._dirty_tracked_paths()\"; rc=$?; rm -rf \"$tmp\"; exit $rc'"]
        test_expected: ["exit 0", "exit 0（1 字符脏路径被正确检出）"]
        suggested_executor: "Task Executor"
        input_contracts: []
        output_contracts:
          - {type: "function", identifier: "_git_at", contract_signature: "def _git_at(cwd: Path, *args: str, timeout: float | None = DEFAULT_GIT_TIMEOUT_SEC) -> str（仅返回值剥离方式改变：保留首行前导空格，去尾部空白）"}
        acceptance_criteria:
          - {claim: "单行修复落地", verify: "grep -n 'return result.stdout' src/loop_kit/_core.py", expected: "唯一命中为 `    return result.stdout.rstrip()`"}
          - {claim: "1 字符脏路径检出", verify: "上述 bash 复现命令", expected: "exit 0（_dirty_tracked_paths()==['f']）"}
          - {claim: "既有 porcelain 消费方不回归", verify: "uv run --group dev pytest tests/test_orchestrator.py -k 'dirty or worktree or merge or clean' -q", expected: "exit 0"}
      - id: "T1.1"
        phase: 1
        title: "_core.py 新增 repo 锁函数组（3 公开 + 内部诊断辅助）"
        goal: "在 src/loop_kit/_core.py 中新增公开函数 _repo_lock_root_for / _repo_lock_path / _acquire_repo_lock（及模块私有诊断辅助 _repo_lock_diagnostic / _pid_is_live），实现基于 repo 路径 sha256 的单机互斥锁（flock 权威、pid 重写、无 unlink）"
        dependencies: []
        modifications: ["src/loop_kit/_core.py"]
        modify_specs:
          - {action: "insert_after", file: "src/loop_kit/_core.py", target: "_cleanup_stale_lock 函数体末行（当前 L1329 `_log(f\"Cleaned up orphan lock file from PID {lock_pid}: {lock_path}\")`，插入位置在该函数结束后、`def _heartbeat_path`（当前 L1332，REFINE-1 实测修正）之前）", description: "新增函数组（完整实现见计划正文 T1.1 修改内容），不修改 _cleanup_stale_lock 与 _LoopLock 本身"}
        boundaries:
          - "不得修改 _LoopLock 类（L1254-1299）与 _cleanup_stale_lock（L1310-1329），旧 loop-dir 锁行为冻结"
          - "不得修改 _enforce_clean_worktree_or_exit（L8860-8904）及其 warn_only 分支"
          - "不得修改 src/loop_kit/ 之外的任何文件，不得触碰 repo 下 执行时动态核对的 pre-existing untracked 项"
        test_commands: ["uv run python -m py_compile src/loop_kit/_core.py", "uv run python -c \"from loop_kit.orchestrator import _repo_lock_path, _acquire_repo_lock, _repo_lock_root_for\""]
        test_expected: ["exit 0", "exit 0"]
        suggested_executor: "Task Executor"
        input_contracts: []
        output_contracts:
          - {type: "function", identifier: "_repo_lock_path", contract_signature: "def _repo_lock_path(root: Path | None = None) -> Path（返回 /tmp/loop-kit-repo-locks/<sha256hex>.lock）"}
          - {type: "function", identifier: "_repo_lock_root_for", contract_signature: "def _repo_lock_root_for(root: Path) -> Path（git toplevel 优先，失败回退 resolve()）"}
          - {type: "function", identifier: "_acquire_repo_lock", contract_signature: "def _acquire_repo_lock(paths: LoopPaths | None = None) -> _LoopLock（flock 冲突抛 RuntimeError，消息 another loop run is already using this working tree）"}
        acceptance_criteria:
          - {claim: "三符号可从 orchestrator 命名空间导入", verify: "uv run python -c \"from loop_kit.orchestrator import _repo_lock_path, _acquire_repo_lock\"", expected: "exit 0"}
          - {claim: "模块可编译", verify: "uv run python -m py_compile src/loop_kit/_core.py", expected: "exit 0"}
      - id: "T1.2"
        phase: 1
        title: "cmd_run 接入 repo 锁（先 repo 后 loop-dir）"
        goal: "在 cmd_run 中于 loop-dir 锁之前获取 repo 锁并按逆序释放，冲突转 StateError 退出码 5，single_round 跳过，部分获取失败仍释放已获锁"
        dependencies: ["T1.1"]
        modifications: ["src/loop_kit/_core.py"]
        modify_specs:
          - {action: "replace_section", file: "src/loop_kit/_core.py", target: "当前 L12620-12628 锁获取块（`lock: _LoopLock | None = None` 至第二个 `except RuntimeError` 块结束）", description: "替换为 repo_lock 先行的双锁获取块（nested try，具体代码见计划正文 T1.2）"}
          - {action: "replace_section", file: "src/loop_kit/_core.py", target: "当前 L12700-12702 finally 块（`finally:` → `if lock is not None:` → `lock.release()`，REFINE-1 实测修正）", description: "替换为先释放 loop-dir lock、再释放 repo_lock 的逆序释放块"}
        boundaries:
          - "不得移动 daemon idle 早退检查（L12630-12639）位置，不得修改 _enforce_clean_worktree_or_exit 调用参数"
          - "不得新增退出码，冲突必须复用 StateError → EXIT_LOCK_FAILURE(5) 路径"
          - "不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围，不得修改 tests/"
        test_commands: ["uv run python -m py_compile src/loop_kit/_core.py", "uv run --group dev pytest tests/test_orchestrator.py -k 'cmd_run' -q --no-header -x"]
        test_expected: ["exit 0", "exit 0（既有 cmd_run 相关测试不回归）"]
        suggested_executor: "Task Executor"
        input_contracts:
          - {type: "function", identifier: "_acquire_repo_lock", contract_signature: "def _acquire_repo_lock(paths: LoopPaths | None = None) -> _LoopLock"}
        output_contracts:
          - {type: "function", identifier: "cmd_run", contract_signature: "def cmd_run(config, single_round, round_num, resume=False, reset=False, paths=None, *, daemon_mode=False) -> None（非 single_round 时先 _acquire_repo_lock 再 _acquire_run_lock，finally 逆序释放）"}
        acceptance_criteria:
          - {claim: "repo 锁先于 loop-dir 锁获取", verify: "grep -n \"repo_lock = _acquire_repo_lock\" src/loop_kit/_core.py 行号小于 grep -n \"lock = _acquire_run_lock\" 行号", expected: "true（两处均 1 命中）"}
          - {claim: "finally 逆序释放", verify: "grep -A4 \"finally:\" src/loop_kit/_core.py 中 lock.release() 在 repo_lock.release() 之前", expected: "true"}
      - id: "T1.3"
        phase: 1
        title: "门面与所有权表同步（file_bus.py + orchestrator.py）"
        goal: "将 _acquire_repo_lock/_repo_lock_path 暴露到 file_bus.py 门面与 _SECTION_OWNERSHIP_MAP lock 段"
        dependencies: ["T1.1"]
        modifications: ["src/loop_kit/file_bus.py", "src/loop_kit/orchestrator.py"]
        modify_specs:
          - {action: "replace_import", file: "src/loop_kit/file_bus.py", target: "from loop_kit._core import ( 显式列表（REFINE-2 字母序位置修正：`_acquire_repo_lock,` 插在 L11 `_acquire_run_lock,` 之前；`_repo_lock_path,` 插在 `_prepare_bus_file,` 之后、`_unlock_file,` 之前，保持 `_parse` < `_prepare` < `_repo` < `_unlock` 字母序；执行时以符号/唯一文本为准）", description: "按字母序加入两个新符号（repo<run；prepare<repo<unlock），ruff I001 门禁"}
          - {action: "add_field", file: "src/loop_kit/file_bus.py", target: "__all__ 列表（`'_acquire_repo_lock',` 插在 L38 `'_acquire_run_lock',` 之前；`'_repo_lock_path',` 插在 L54 `'_prepare_bus_file',` 与 L55 `'_unlock_file',` 之间，与 import 同字母序位置）", description: "与 import 块同位置加入 '_acquire_repo_lock' 与 '_repo_lock_path'，ruff RUF022 门禁"}
          - {action: "replace_line", file: "src/loop_kit/orchestrator.py", target: "`    \"lock\": (\"_lock_file\", \"_unlock_file\", \"_LoopLock\", \"_acquire_run_lock\"),`", description: "元组末尾追加 \"_repo_lock_path\", \"_acquire_repo_lock\""}
        boundaries:
          - "不得新增/删除任何其他符号，不得改动 _SECTION_MODULE_PATHS"
          - "不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围，不得修改 tests/"
        test_commands: ["uv run python -c \"from loop_kit.file_bus import _acquire_repo_lock, _repo_lock_path; from loop_kit import orchestrator as o; assert hasattr(o, '_acquire_repo_lock')\"", "uv run python -m py_compile src/loop_kit/file_bus.py src/loop_kit/orchestrator.py", "uv run ruff check --preview --select I001,RUF022 src/loop_kit/file_bus.py"]
        test_expected: ["exit 0", "exit 0", "exit 0（REFINE-2 门禁：import 排序 I001 与 __all__ 排序 RUF022 双通过，证明插入位置字母序正确）"]
        suggested_executor: "Task Executor"
        input_contracts:
          - {type: "function", identifier: "_acquire_repo_lock", contract_signature: "def _acquire_repo_lock(paths: LoopPaths | None = None) -> _LoopLock"}
          - {type: "function", identifier: "_repo_lock_path", contract_signature: "def _repo_lock_path(root: Path | None = None) -> Path"}
        output_contracts:
          - {type: "file", identifier: "src/loop_kit/file_bus.py", contract_signature: "exports _acquire_repo_lock, _repo_lock_path"}
          - {type: "file", identifier: "src/loop_kit/orchestrator.py", contract_signature: "exports _acquire_repo_lock, _repo_lock_path via module alias"}
        acceptance_criteria:
          - {claim: "门面暴露新符号", verify: "uv run python -c \"from loop_kit.file_bus import _acquire_repo_lock, _repo_lock_path\"", expected: "exit 0"}
          - {claim: "所有权表含新符号", verify: "grep -c '_acquire_repo_lock' src/loop_kit/orchestrator.py", expected: ">=1"}
  - id: "Phase 2"
    title: "测试（仅 tests/test_orchestrator.py 文件末尾追加）"
    tasks:
      - id: "T2.1"
        phase: 2
        title: "repo 锁单元测试（路径哈希/获取/冲突/pid 记录）"
        goal: "追加 TestRepoLockPath / TestAcquireRepoLock / TestRepoLockPidRecord 三个测试类，验证确定性哈希、冲突报错、pid 记录重写、PID 复用不误判"
        dependencies: ["T1.1"]
        modifications: ["tests/test_orchestrator.py"]
        modify_specs:
          - {action: "insert_after", file: "tests/test_orchestrator.py", target: "文件末尾（执行时以当时 EOF 为锚点，追加三个新测试类）", description: "追加三个测试类（用例清单见计划正文 T2.1）"}
        boundaries:
          - "只追加不修改任何既有测试函数，不得改动 conftest.py 与其他测试文件"
          - "测试内不得对真实 repo 调用 _repo_lock_path()（无 root 参数），必须传 root=tmp_path 或 monkeypatch ROOT"
          - "不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围"
        test_commands: ["uv run --group dev pytest tests/test_orchestrator.py -k 'RepoLockPath or AcquireRepoLock or RepoLockPidRecord' -v"]
        test_expected: ["exit 0，全部用例通过"]
        suggested_executor: "Task Executor"
        input_contracts:
          - {type: "function", identifier: "_repo_lock_path", contract_signature: "def _repo_lock_path(root: Path | None = None) -> Path"}
          - {type: "function", identifier: "_acquire_repo_lock", contract_signature: "def _acquire_repo_lock(paths: LoopPaths | None = None) -> _LoopLock"}
        output_contracts:
          - {type: "file", identifier: "tests/test_orchestrator.py", contract_signature: "exports TestRepoLockPath, TestAcquireRepoLock, TestRepoLockPidRecord（追加区）"}
        acceptance_criteria:
          - {claim: "新测试类全绿", verify: "uv run --group dev pytest tests/test_orchestrator.py -k 'RepoLockPath or AcquireRepoLock or RepoLockPidRecord' -v", expected: "exit 0"}
          - {claim: "既有锁测试不回归", verify: "uv run --group dev pytest tests/test_orchestrator.py -k '_LoopLock or acquire_run_lock or cleanup_stale_lock' -q", expected: "exit 0"}
      - id: "T2.2"
        phase: 2
        title: "cmd_run 锁语义集成测试（顺序/跳过/冲突退出/daemon 不变）"
        goal: "追加 TestCmdRunRepoLock 测试类：获取顺序、single_round 跳过、冲突 exit 5、部分获取失败释放已获锁、daemon warn_only 语义不变"
        dependencies: ["T1.2", "T2.1"]
        modifications: ["tests/test_orchestrator.py"]
        modify_specs:
          - {action: "insert_after", file: "tests/test_orchestrator.py", target: "文件末尾（T2.1 追加区之后，以当时 EOF 为锚点）", description: "追加 TestCmdRunRepoLock 测试类（用例清单见计划正文 T2.2）"}
        boundaries:
          - "只追加，不得修改 T2.1 已追加的测试类，不得改动 conftest.py"
          - "daemon 用例必须经 _enforce_clean_worktree_or_exit 真实调用验证 warn_only 语义（不得重写其实现）"
          - "不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围"
        test_commands: ["uv run --group dev pytest tests/test_orchestrator.py -k 'CmdRunRepoLock or enforce_clean_worktree_warn_only' -v"]
        test_expected: ["exit 0"]
        suggested_executor: "Task Executor"
        input_contracts:
          - {type: "function", identifier: "cmd_run", contract_signature: "def cmd_run(config, single_round, round_num, resume=False, reset=False, paths=None, *, daemon_mode=False) -> None"}
        output_contracts:
          - {type: "file", identifier: "tests/test_orchestrator.py", contract_signature: "exports TestCmdRunRepoLock（追加区）"}
        acceptance_criteria:
          - {claim: "锁顺序/跳过/冲突退出测试全绿", verify: "uv run --group dev pytest tests/test_orchestrator.py -k 'CmdRunRepoLock' -v", expected: "exit 0"}
          - {claim: "warn_only 既有测试不回归", verify: "uv run --group dev pytest tests/test_orchestrator.py -k 'warn_only' -v", expected: "exit 0"}
      - id: "T2.3"
        phase: 2
        title: "脏树单次失败无重试 + T-3151/T-3152 历史回放测试"
        goal: "追加 TestDirtyTreeFailFastNoRetry 与 TestHistoricalReplayT3151T3152，显式验证脏树单次检查即 exit 4 且无重试，真实子进程回放历史故障（<10s 快速失败）与 repo 锁冲突（exit 5）"
        dependencies: ["T1.2", "T2.2"]
        modifications: ["tests/test_orchestrator.py"]
        modify_specs:
          - {action: "insert_after", file: "tests/test_orchestrator.py", target: "文件末尾（T2.2 追加区之后，以当时 EOF 为锚点）", description: "追加两个测试类（含 subprocess 真实回放，用例清单见计划正文 T2.3）"}
        boundaries:
          - "只追加，回放测试必须用 tmp_path 内 git init 的真实 git 仓（参考既有 L2172 模式：subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)），严禁在真实 repo 上运行回放"
          - "回放测试不得依赖外部网络/PM 服务，超时保护 timeout=60 并断言耗时上限"
          - "不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围"
        test_commands: ["uv run --group dev pytest tests/test_orchestrator.py -k 'DirtyTreeFailFastNoRetry or HistoricalReplay' -v"]
        test_expected: ["exit 0"]
        suggested_executor: "Task Executor"
        input_contracts:
          - {type: "function", identifier: "_repo_lock_path", contract_signature: "def _repo_lock_path(root: Path | None = None) -> Path"}
          - {type: "function", identifier: "cmd_run", contract_signature: "def cmd_run(config, single_round, round_num, resume=False, reset=False, paths=None, *, daemon_mode=False) -> None"}
        output_contracts:
          - {type: "file", identifier: "tests/test_orchestrator.py", contract_signature: "exports TestDirtyTreeFailFastNoRetry, TestHistoricalReplayT3151T3152（追加区）"}
        acceptance_criteria:
          - {claim: "脏树单次失败无重试用例通过", verify: "uv run --group dev pytest tests/test_orchestrator.py -k 'DirtyTreeFailFastNoRetry' -v", expected: "exit 0"}
          - {claim: "历史回放用例通过且耗时达标", verify: "uv run --group dev pytest tests/test_orchestrator.py -k 'HistoricalReplay' -v --durations=10", expected: "exit 0，用例 1/2 <10s，用例 3 走 REFINE-2 超时证据语义（60s 上限）"}
  - id: "Phase 3"
    title: "全量回归与收尾"
    tasks:
      - id: "T3.1"
        phase: 3
        title: "全量回归 + lint + 锁目录人工复核"
        goal: "跑全量测试与 lint，确认无回归，人工复核 /tmp/loop-kit-repo-locks 残留语义，按仓库 commit 约定提交并建议 PM 回写"
        dependencies: ["T1.3", "T2.3"]
        modifications: []
        modify_specs: []
        boundaries:
          - "本任务不修改任何源码/测试文件（纯验证 + 提交），提交范围仅限本计划 4 个文件"
          - "不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围（git add 须逐文件指定，禁止 git add -A/.)"
          - "不直接写 PM（如需更新 #3155 状态经 pm-coordinator 委派）"
        test_commands: ["uv run --group dev pytest -q", "uv run ruff check src/loop_kit tests", "uv run python -m py_compile src/loop_kit/_core.py src/loop_kit/file_bus.py src/loop_kit/orchestrator.py"]
        test_expected: ["exit 0 且 0 failed", "exit 0 且 0 errors（PM #2749 基线）", "exit 0"]
        suggested_executor: "Task Executor"
        input_contracts: []
        output_contracts:
          - {type: "state_change", identifier: "git:committed", verification_hint: {type: "grep", pattern: "\\[Plan: pm3155-repo-mutex-lock\\]", file: "REPO", expected_count: ">=4"}}
        acceptance_criteria:
          - {claim: "全量测试零失败", verify: "uv run --group dev pytest -q", expected: "exit 0"}
          - {claim: "lint 零错误", verify: "uv run ruff check src/loop_kit tests", expected: "exit 0"}
          - {claim: "提交不含计划外文件", verify: "git show --stat HEAD 仅含 4 个计划内文件路径", expected: "true"}
context:
  repo_path: "/home/gw/opt/agent-task-runner"
  repo_path_source: "[推断] PM #3155 tasks.workspace=null，按 project_id=171（project_name=agent-task-runner）推断仓路径；2026-09-03 实测核对：git HEAD=25d4ccf、分支 master、本计划文件本体位于该仓 .github/plans/、4 个计划文件 sha256 与快照一致"
  untracked_items: [".github/plans/biweekly-reporting-restore-2026-08-27.md", ".github/plans/pm3155-repo-mutex-lock.md（本计划文件自身）", "data/"]
  git_commit: "25d4ccf5c838ed6aae3f94f27822cf25f32b91e9"
  generated_at: "2026-09-03T00:44:25Z"
  refined_at: "2026-09-03T04:28:09Z"
  files:
    - {path: "src/loop_kit/_core.py", sha256: "6e5823b0b7c78a10828021e52d83af48c45f207055df8890209217b11c7b4659"}
    - {path: "src/loop_kit/file_bus.py", sha256: "06e4afe9964d8edbc18683e8eee451853f909c9a0480781d494e2321d4b5788a"}
    - {path: "src/loop_kit/orchestrator.py", sha256: "917f25597009c58dab9f7f6ccc43c42600ddb120b26ff0bb1191510c2ba5f126"}
    - {path: "tests/test_orchestrator.py", sha256: "45696cd2536f17ac74f09e4182c35c567e5c9f9c4fdba2dd54c0b411cc6048b7"}
---

# PM #3155 ATR repo 级互斥锁（单机）实施计划

## 背景与目标

- **问题/需求描述**：PM #3155 为 ATR 自身兜底，除调度器侧 workspace 互斥门控（RESEARCH-PM 主防线任务，out-of-scope）外，loop-kit 需在**非 PM dispatcher 路径**（手动 `loop run`、AOM pipeline-loop）提供 repo 级互斥锁，防止并发 `loop run` 污染同一工作树。脏工作树 fail-fast 预检**已存在**（`_enforce_clean_worktree_or_exit`，exit 4），本计划**禁止重写**，只补显式测试验证其「单次失败、无重试」语义。
- **根因分析**：2026-08-30 T-3151/T-3152 脏树各经 3 次重试浪费约 5 分钟，重试发生在调度器层（本仓外），loop-kit 内 `cmd_run` 本身单次执行即退出，但缺乏①repo 级互斥（现有 `.loop/lock` 只保护 loop 状态目录，且 `.loop/` 不存在时无锁可用）②「脏树=确定性故障不重试」的显式回归测试。
- **目标**：
  1. repo-path hash 单机互斥锁，`loop run` 全程持有，冲突明确报错「another loop run is already using this working tree」并 exit 5
  2. 与现有 loop-dir `.loop/lock` 统一获取顺序（repo → loop-dir），防 ABBA，stale pid 覆盖式清理 + PID 复用防护，single-round 子进程跳过避免自死锁
  3. daemon `warn_only` 语义零改动，脏树单次失败无重试显式测试，真实历史案例（T-3151/T-3152）回放，全量回归
- **非目标（不做什么）**：
  - 不重写脏树 fail-fast（只加测试）— 已验证存在且行为正确
  - 不引入跨机/分布式锁，PM #3155 out-of-scope 明确单机场景
  - 不改 project_management / copilot-agents / `.loop/`（运行态目录），不碰 执行时动态核对的 pre-existing untracked 项
  - 不修改调度器侧重试逻辑，属 RESEARCH-PM 主防线任务
- **已有代码/流程复用分析**：
  - `_LoopLock`（_core.py L1254）：**复用** flock 机制（同一 OS 原语），不复制不修改
  - `_cleanup_stale_lock`（L1311）：**不复用**其 unlink 模式（inode 竞态 + PID 复用误判），repo 锁采用「flock 唯一权威 + 覆盖式 pid」新范式，该旧函数冻结不改
  - `_acquire_run_lock`（L1302）：**复用其调用形态**（`paths=None` 签名、RuntimeError→StateError→exit 5 链）
  - 脏树检查、daemon 早退、single_round 跳过逻辑：**零改动复用**

## 产出1 Scope 澄清（REFINE-1 补充，以实测证据固化）

PM #3155 产出 1 为「worker 启动前脏工作树检测 fail-fast：错误信息列出脏文件清单；脏树错误类型直接失败，不进 retry 循环」。**澄清：产出 1 在 loop-kit 内的实现侧已存在且冻结，本计划的产出 1 工作量 = 仅补显式回归测试（T2.3）+ Post-Execution 独立复现（V6），不含任何实现改动。** 证据（2026-09-03 实测，HEAD=25d4ccf）：

| 产出 1 要求 | 现状证据（`src/loop_kit/_core.py`） | 本计划动作 |
|---|---|---|
| 脏文件清单逐条列出 | `_enforce_clean_worktree_or_exit` L8874-8876：`print("Warning: dirty git working tree detected:", ...)` + 逐路径 `  - {path}` 到 stderr | 冻结不改；T2.3 用例 2 断言 stderr 含清单 |
| 单次检查快速失败 | L8900 `raise DirtyWorktreeError("Dirty worktree")` → L8902 `sys.exit(EXIT_DIRTY_WORKTREE)`=4；`cmd_run` 内单次调用（L12658-12662），无内部 retry 循环 | 冻结不改；T2.3 `TestDirtyTreeFailFastNoRetry` 用计数包装器断言 `calls==1` 且 `<1s` |
| 不进 retry 循环（retries 仅用于瞬时故障） | retry 逻辑在调度器侧（本仓外，RESEARCH-PM 主防线任务），loop-kit `cmd_run` 单次执行即退出 | 不回退；T2.3 历史回放断言 `returncode==4` 且 stderr 无 `[Worker] Running`、耗时 <10s（历史基线约 300s） |

**REFINE-1 实测发现的缺陷与对策**：产出 1 的数据源 `_dirty_tracked_paths`（L7715-7731）依赖 `_git_at` 的 porcelain 输出，而 `_git_at` L6882 的 `.strip()` 剥离 XY 前导空格导致解析错位（1-2 字符路径静默跳过、≥3 字符路径首字符被吞）。该缺陷使「列出脏文件清单」语义在特定路径形态下失真，且直接导致本计划 V6/T2.3 回放测试按原样执行会失败（实测复现：脏 tmp 仓 `loop run` 挂起而非 exit 4）。对策：新增 **T1.0**（单行修复 `_git_at`，非冻结函数），修复后 V6/T2.3 的断言（完整脏文件名、快速 exit 4）方可成立。冻结名单（`_LoopLock`/`_cleanup_stale_lock`/`_enforce_clean_worktree_or_exit`）**未被触碰**——该缺陷位于冻结名单之外的 `_git_at`。

## 修改文件清单与验收/回滚汇总（REFINE-1 补充）

**修改文件（共 4 个源码文件 + 计划文件自身，无新增文件）**：

| 文件 | 修改点 | 任务 | 独立 commit |
|---|---|---|---|
| `src/loop_kit/_core.py` | T1.0：L6882 单行（`.strip()`→`.rstrip()`）；T1.1：在 `_cleanup_stale_lock` 结束后、`_heartbeat_path` 之前插入 repo 锁函数组（`_repo_lock_root_for`/`_repo_lock_path`/`_repo_lock_diagnostic`/`_pid_is_live`/`_acquire_repo_lock`，含 `import tempfile` 补充；REFINE-2：`_pid_is_live` 死代码简化，删除 `_pid_start_ticks_match`/`_pid_is_self_start_match` 两辅助函数）；T1.2：L12620-12628 双锁获取块 + L12700-12702 finally 逆序释放 | T1.0 / T1.1 / T1.2 | 每 task 1 个 |
| `src/loop_kit/file_bus.py` | 显式 import：`_acquire_repo_lock,` 插 L11 `_acquire_run_lock,` 前、`_repo_lock_path,` 插在 `_prepare_bus_file,` 之后、`_unlock_file,` 之前（REFINE-2 字母序修正；执行时以唯一符号文本为锚）；`__all__`（L34 起）同位置加入 `'_acquire_repo_lock',`（L38 前）与 `'_repo_lock_path',`（L54/L55 之间），ruff I001/RUF022 门禁 | T1.3 | 1 个 |
| `src/loop_kit/orchestrator.py` | L37 `_SECTION_OWNERSHIP_MAP["lock"]` 元组追加 `"_repo_lock_path", "_acquire_repo_lock"` | T1.3 | 与 file_bus.py 同 commit |
| `tests/test_orchestrator.py` | 文件末尾按 T2.1→T2.2→T2.3 顺序追加 7 个测试类（RepoLockPath/AcquireRepoLock/RepoLockPidRecord/CmdRunRepoLock/DirtyTreeFailFastNoRetry/HistoricalReplayT3151T3152） | T2.1 / T2.2 / T2.3 | 每 task 1 个 |
| `.github/plans/pm3155-repo-mutex-lock.md` | 本计划文件（untracked，保护项，**不进任何 commit**） | — | — |

**验收汇总（执行顺序 = 波次）**：T1.0（单行修复 + 复现命令 + `-k 'dirty or worktree or merge or clean'` 回归）→ T1.1（三公开符号可导入 + `_repo_lock_path` 格式断言）→ T1.2（获取顺序 grep 断言 + 逆序释放 + 既有 cmd_run 测试零改动通过）→ T1.3（门面暴露 + 所有权表 grep + ruff I001/RUF022 字母序门禁）→ T2.1（三个测试类绿 + 既有锁测试不回归）→ T2.2（五条集成用例绿 + warn_only 不回归）→ T2.3（脏树单次失败 + 历史回放用例 1/2 <10s，用例 3 60s TimeoutExpired=超时证据 PASS，REFINE-2 口径）→ T3.1（V1 全量零失败 + V3 lint 零错误 + 提交范围 = 4 文件）。Post-Execution 另有 V1-V7 + P1 + M1-M2（见后文）。

**回滚操作手册（按序执行）**：

1. 定位本计划全部 commit：`git log --oneline --grep="[Plan: pm3155-repo-mutex-lock]"`（每个 task 一个 commit，T1.2 因 fix-forward 拆为 2 个，共 8 个；fix-forward 计划 pm3155-repo-mutex-lock-fixforward-o1 追加 1 个 commit 后共 9 个，回滚先 revert 该 fix-forward commit）
2. 逆序 revert：T3.1（若含收尾 commit）→ T2.3 → T2.2 → T2.1 → T1.3 → T1.2-fix-forward(037a6d1) → T1.2(3e9f9fb) → T1.1 → T1.0。**不回退的顺序依据**：测试任务只回退其追加区；T1.2 依赖 T1.1 的 `_acquire_repo_lock`；T1.0 修复被 T2.3/V6 依赖，故最后回退
3. 单 task 失败时：fix-forward 优先（就地修正后重跑该 task 测试）；确认无法修正才 `git revert` 该 task 的单个 commit（每 task 独立 commit，revert 互不牵连）
4. 回滚后验证：`uv run --group dev pytest -q` 确认回到基线（615+ 通过 / 0 failed），并确认 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围原样保留（`git status --porcelain` 仅列出这 3 项）
5. 禁止 `git reset` 实现侧 commit（避免连锁 revert），禁止触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围

## 技术方案

- **方案概述**：新增 `_repo_lock_root_for(root)`（git toplevel 优先、失败回退 `root.resolve()`）→ `_repo_lock_path(root=None)`（`/tmp/loop-kit-repo-locks/<sha256(resolved_root_str)>.lock`）→ `_acquire_repo_lock(paths=None)`（复用 `_LoopLock` 做 flock，成功后 truncate+写 `pid:<pid>`，OSError 一律包装为 RuntimeError fail-closed）。`cmd_run` 在 loop-dir 锁之前获取 repo 锁，finally 逆序释放。
- **关键设计决策**（见下表 D1-D7）：

| # | 决策 | 理由 | 备选（已否决） |
|---|------|------|----------------|
| D1 | 锁文件放 `/tmp/loop-kit-repo-locks/<sha256>.lock`（`tempfile.gettempdir()`） | 仓外→不污染工作树/不影响脏树判定，hash 防路径冲突 | 放 repo 内 → 会被自身脏树检查误伤，放 `.loop/` → 与既有 loop-dir 锁混义 |
| D2 | flock 是唯一权威，**绝不 acquire 前 unlink** | 进程死亡 OS 自动释放（无 stale 阻塞），unlink→recreate 存在双持 inode 竞态（现有 `_cleanup_stale_lock` 的隐患，冻结不改） | 照搬 unlink 清理模式 → 复刻竞态 |
| D3 | pid 记录覆盖式写入（acquire 成功后 truncate+写） | 「stale 清理」= 下次持锁者覆盖旧 pid，无需删文件 |，|
| D4 | PID 复用只影响诊断：冲突时读 pid 行 + `os.kill(pid,0)` 存活探测（REFINE-2：/proc 启动时间比对已随 `_pid_is_live` 死代码简化删除——锁文件只记录 pid 无 start-ticks 记录侧，该比对无意义），只用于文案区分「held by pid N」/「stale or reused pid record (N)」，**不作为拒绝依据** | flock 已是权威，pid 复用不可能造成假冲突或假放行 |，|
| D5 | 获取顺序固定 repo → loop-dir（单点获取，finally 逆序释放），运行时 knowledge lock 更晚 | 全仓唯一获取点 → ABBA 不可能发生 |，|
| D6 | single_round 子进程跳过两把锁（沿用现有 `if not single_round:` 守卫） | 父进程持锁派发子进程，子进程再取锁必自死锁，子进程经 exec 且 fd 有 CLOEXEC（PEP 446），双保险 |，|
| D7 | 冲突 → RuntimeError（消息含 pid 与锁路径）→ StateError → EXIT_LOCK_FAILURE(5) | 复用现有退出码与 cmd_run 异常链，无新退出码（HOLD 姿态） | 新增专用退出码 → 扩大影响面 |
| D8 | hash 输入为 `_repo_lock_root_for()` 结果**resolve 后**的路径字符串 | 符号链接 cwd 不同字符串同仓库 → 锁分裂，resolve 保证一致 |，|

- **假设标注**：
  - `[假设: 单机 /tmp 可写]`，不可写时 fail-closed exit 5（B1），若未来需支持受限环境再引入 `LOOP_REPO_LOCK_DIR` 环境变量（本次不做）
  - `[假设: lane worktree 各自独立互斥是预期语义]`，hash 含 worktree 路径，lane 子仓并发不被主仓锁串行化（符合「防主工作树污染」目标）
  - `[假设: /tmp 残留锁文件无害]`，flock 随进程消亡释放，残留 pid 文件仅为诊断记录，不阻塞后续获取
- **影响范围**：`src/loop_kit/_core.py`、`src/loop_kit/file_bus.py`、`src/loop_kit/orchestrator.py`、`tests/test_orchestrator.py`（共 4 文件）。**不应触碰**：`.loop/`（运行态）、project_management、copilot-agents、执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围、其余测试文件。

## Error & Rescue Map（关键失败路径映射）

| 代码路径/操作 | 可能的失败 | 错误类型 | 已处理？ | 处理方式 | 用户可见行为 |
|-------------|-----------|---------|---------|---------|------------|
| `_repo_lock_path()` → `git rev-parse --show-toplevel` | 非 git 目录 / git 超时（DEFAULT_GIT_TIMEOUT_SEC） | RuntimeError | Y | try/except RuntimeError → 回退 `root.resolve()` | 无（静默降级，hash 仍确定） |
| `_LoopLock.acquire()` → `mkdir / open` | /tmp 不可写 / 权限不足 | OSError | Y | `_acquire_repo_lock` 包装为 RuntimeError → StateError → exit 5（fail-closed，B1） | `Error: repo lock unavailable (...)` + exit 5 |
| `_LoopLock.acquire()` → flock 冲突 | 另一 loop 持锁 | OSError→RuntimeError | Y | 读 pid 行做诊断（≤64B、try/except 防御解析），转 StateError → exit 5 | `another loop run is already using this working tree (pid: N) (lock: <path>)` + exit 5 |
| 锁文件被外部篡改（pid 行非数字/超长/乱码） | 诊断解析失败 | ValueError/OSError | Y | 防御解析失败 → 不带 pid 的通用冲突消息，内容永不执行、只 print 到 stderr（Lens A） | 通用冲突消息 + exit 5 |
| 持锁进程死亡 | flock 自动释放 |，| Y | OS 语义，无需清理，下次持锁者覆盖 pid 记录 | 无阻塞 |
| pid 记录为存活但无关进程（PID 复用） | 误判风险 |，| Y | 判定只看 flock，pid 仅供诊断（D4），`_pid_is_live` 为 kill(0) 单层存活探测（REFINE-2），kill(0) 不存活或 pid==self 时文案标注 stale or reused | 正常获取或正常冲突，无假拒绝 |
| loop-dir 锁获取失败（repo 锁已获） | 部分获取 | RuntimeError→StateError | Y | repo_lock 在 finally 中无条件释放（T1.2 嵌套结构，B7） | exit 5，锁无泄漏 |
| single-round 子进程误取锁 | 自死锁 |，| Y | 沿用 `if not single_round:` 跳过两把锁（D6） | 无 |
| 脏树（确定性故障） | 3 次重试浪费 |，| Y（已存在，本计划只加测试验证） | `_enforce_clean_worktree_or_exit` 单次检查 → exit 4，无内部重试，调度器侧重试属 out-of-scope | 单次快速失败，列出脏文件清单 |

> CRITICAL GAP：无。所有已识别的静默失败路径（B1/B3/B4/B7）均已在本计划 Task 中显式处理。
> 高风险路径降级策略：`/tmp/loop-kit-repo-locks` 整体丢失/被清 → 最坏退化为「无 repo 互斥」（与现状等价，不劣于基线），不会误伤正在运行的 loop（flock 随进程消亡）。

## 执行计划

> 通用前置（每个 Phase 第一步，强制执行）：**基线漂移重检**，`git rev-parse HEAD` + `git status --porcelain` 实测。若 HEAD ≠ `25d4ccf`、或 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围之外出现新脏文件、或本计划锚点行号漂移 → 先更新锚点（以符号/唯一文本为锚，行号仅作参考）再动手。计划内所有 `当前 Lxxx` 均为生成时快照。

### Phase 1: repo 级互斥锁实现（src/loop_kit/）

#### Task 1.0: `_git_at` porcelain 输出剥离修复（REFINE-1 新增，脏树检测正确性前置）

- **目标**：修复 `_git_at` 返回值 `.strip()` 剥离 porcelain XY 前导空格的缺陷，使 `_dirty_tracked_paths` 的 `raw[:2]`/`raw[3:]` 解析恢复正确。
- **背景（REFINE-1 实测证据）**：2026-09-03 用 V6 等价命令做冒烟，发现脏 tmp 仓下 `loop run` 未在 <10s 内 exit 4 而是挂起。逐层定位：`git status --porcelain` 输出 ` M f`，经 `_git_at` 的 `result.stdout.strip()` 后变 `M f`（前导空格为 XY 两列之一，是数据非空白）。后果：1-2 字符脏路径（如 `f`）`raw[3:]` 为空被静默跳过 → 脏树检测**静默失效**进入 `_main_loop`；≥3 字符路径（如 `src/foo.py`）首字符被吞（实测 `dirty==['rc/foo.py']`）→ 错误信息列出的脏文件清单**路径腐蚀**。L7437（`_restore_merge_head_after_failure`）与 L7645（integration worktree_clean 检查）两处 porcelain 调用仅做真值判断，不受影响。
- **依赖**：无
- **input_contracts**：`[]`
- **output_contracts**：见 frontmatter T1.0（`_git_at` 契约）
- **修改内容**：文件 `src/loop_kit/_core.py`，仅改一行——L6882 `    return result.stdout.strip()` → `    return result.stdout.rstrip()`。`.rstrip()` 保留首行前导空格（porcelain XY 列）、仍去除尾部空白/换行。经实测核对（REFINE-2 重数），`_git`/`_git_at` 共 **22 个调用点**（`_git` 19 个 + `_git_at` 直接调用 3 个：L3507/L3511/L7018；另有 `_git` 内部转发 `_git_at` 1 处 L6886 不计入），其中 4 处传 `--porcelain`：L6890 `worktree list --porcelain`（行首为 `worktree <path>` 无 XY 前导空格，不受影响）、L7437/L7645 `status --porcelain --untracked-files=no`（真值语义不受影响）、L7718 `status --porcelain`（得到修复）。其余调用点消费 `rev-parse`/`log`/`diff`/`checkout` 等无前导空格输出，零波及。
- **修改边界**：仅 L6882 单行；不得修改 `_LoopLock`（L1254-1299）、`_cleanup_stale_lock`（L1310-1329）、`_enforce_clean_worktree_or_exit`（L8860-8904）、`_dirty_tracked_paths` 本身；不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围与 tests/。
- **测试要求**：
  - `uv run python -m py_compile src/loop_kit/_core.py`（exit 0）
  - 复现命令（1 字符脏路径检出）：`tmp=$(mktemp -d) && git -C "$tmp" init -q && git -C "$tmp" config user.email t@t && git -C "$tmp" config user.name t && echo x > "$tmp/f" && git -C "$tmp" add -A && git -C "$tmp" commit -qm i && echo y >> "$tmp/f" && cd "$tmp" && uv run --project /home/gw/opt/agent-task-runner python -c "import loop_kit._core as c; assert c._dirty_tracked_paths() == ['f'], c._dirty_tracked_paths()"`（exit 0）
  - 既有回归：`uv run --group dev pytest tests/test_orchestrator.py -k 'dirty or worktree or merge or clean' -q`（exit 0）
- **验收标准**：
  - claim: 单行修复落地 → verify: `grep -n 'return result.stdout' src/loop_kit/_core.py` → expected: 唯一命中且为 `.rstrip()` 版本
  - claim: 1 字符脏路径检出 → verify: 上述复现命令 → expected: exit 0（`_dirty_tracked_paths()==['f']`）
  - claim: 既有相关测试不回归 → verify: `uv run --group dev pytest tests/test_orchestrator.py -k 'dirty or worktree or merge or clean' -q` → expected: exit 0
- **潜在风险**：`.rstrip()` 使其余调用点得到的首行保留前导空格——已核查 22 个调用点（REFINE-2 重数，`_git` 19 + `_git_at` 直接 3）无消费首行前导空格的解析（porcelain 之外的 git 输出无前导空格，L6890 worktree porcelain 行首亦无 XY 列），风险极低；全量回归 V1 兜底。
- **回滚**：`git revert <T1.0 commit>` 即恢复原状；T1.0 独立 commit，不影响其余任务产物。
- **预留歧义标注**：
  - [x] 无歧义：单行 diff、复现命令、回归命令均给定。

#### Task 1.1: `_core.py` 新增 repo 锁函数组（3 公开 + 内部诊断辅助）

- **目标**：在 `_core.py` 新增 `_repo_lock_root_for` / `_repo_lock_path` / `_acquire_repo_lock`（及诊断辅助），实现 repo 级互斥锁核心。
- **依赖**：无（与 T1.0 同 wave；两者修改 `_core.py` 不相邻区域，但为防同文件写冲突，TE 按 T1.0 → T1.1 顺序执行）
- **input_contracts**：`[]`
- **output_contracts**：见 frontmatter T1.1（3 个 function 契约）
- **修改内容**：文件 `src/loop_kit/_core.py`，在 `_cleanup_stale_lock` 函数体结束后（当前 L1329）、`def _heartbeat_path(`（当前 L1332）之前插入以下函数组（**完整参考实现**，TE 可直接落地，仅允许按 ruff 风格微调空白）：

```python
_REPO_LOCK_DIR_NAME = "loop-kit-repo-locks"


def _repo_lock_root_for(root: Path) -> Path:
    """Resolve the canonical repo root used for lock hashing."""
    if _is_git_repo_root(root):
        try:
            toplevel = _git_at(root, "rev-parse", "--show-toplevel")
        except RuntimeError:
            pass
        else:
            if toplevel.strip():
                return Path(toplevel.strip()).resolve()
    return root.resolve()


def _repo_lock_path(root: Path | None = None) -> Path:
    """Repo-level mutex lock path: /tmp/loop-kit-repo-locks/<sha256(root)>.lock."""
    resolved = _repo_lock_root_for(root if root is not None else ROOT)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
    lock_dir = Path(tempfile.gettempdir()) / _REPO_LOCK_DIR_NAME
    return lock_dir / f"{digest}.lock"


def _repo_lock_diagnostic(lock_path: Path) -> str:
    """Best-effort holder description; never raises, content never executed."""
    try:
        first = lock_path.read_text(encoding="utf-8", errors="replace")[:64].split("\n")[0]
        if first.startswith("pid:"):
            pid = int(first[4:].strip())
            if pid != os.getpid() and _pid_is_live(pid):
                return f"held by pid {pid}"
            return f"stale or reused pid record ({pid})"
    except (OSError, ValueError, IndexError):
        pass
    return "holder unknown"


def _pid_is_live(pid: int) -> bool:
    """PID liveness probe: kill(pid, 0). Diagnostics only; never gates locking.

    REFINE-2 simplification: the /proc/<pid>/stat start-time comparison was
    removed as dead code — the lock file records only ``pid:`` (no recorded
    start-ticks side to compare against), so that check was a tautology.
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_repo_lock(paths: LoopPaths | None = None) -> _LoopLock:
    """Acquire the repo-level mutex. flock is the sole authority.

    Never unlinks the lock file (avoids the unlink→recreate inode race present
    in the legacy loop-dir cleanup path). PID record is overwritten after a
    successful acquisition; on conflict it is read for diagnostics only.
    """
    _ = paths  # interface symmetry with _acquire_run_lock
    lock_path = _repo_lock_path()
    try:
        lock = _LoopLock(lock_path)
        lock.acquire()
    except RuntimeError as e:
        holder = _repo_lock_diagnostic(lock_path)
        raise RuntimeError(
            f"another loop run is already using this working tree "
            f"({holder}) (lock: {lock_path})"
        ) from e
    except OSError as e:
        raise RuntimeError(f"repo lock unavailable ({lock_path}): {e}") from e
    try:
        lock_path.write_text(f"pid:{os.getpid()}\n", encoding="utf-8")
    except OSError:
        pass
    return lock
```

> 注 1（import 状态，REFINE-1）：`hashlib` 与 `tempfile` 的 import 状态已核实——`import hashlib` 已存在（L18），`import tempfile` **缺失**，TE 在 `_core.py` 顶部 import 区按字母序补 `import tempfile`（`import sys` L29 之后）。
> 注 2（`_pid_is_live` 死代码简化，REFINE-2 已在上方参考实现落地）：`_pid_is_live` 为 `os.kill(pid, 0)` 单层存活探测。原草稿中的 `/proc/<pid>/stat` 启动时间比对（`self_ticks` 计算、`if start_ticks != self_ticks ...: pass` 死代码行、`_pid_start_ticks_match`、`_pid_is_self_start_match`）**已全部删除**。删除理由：锁文件只记录 `pid:`，无 start-ticks 记录侧可比对，该检查恒真。核心不变量不变：**pid 检查绝不参与是否放行的判定**。
> 注 3（`_repo_lock_root_for` 与既有 `_git_toplevel` 的关系，REFINE-2 注明）：`_git_toplevel()`（L12950）**已存在**（无参、固定作用于全局 ROOT、失败回退 ROOT），`_repo_lock_root_for(root)` **不复用**它，理由：① `_git_toplevel` 无 root 参数，无法支持任意 root（T2.1/T2.3 测试与回放子进程需对 tmp repo 取锁）；② 回退语义不同（`_git_toplevel`→ROOT，`_repo_lock_root_for`→`root.resolve()`）。两者内部命令同为 `rev-parse --show-toplevel`，属同一 git 原语的参数化新包装，非重复实现（CAP 口径：ROOT 专用版本保留不动）。`_is_git_repo_root`（L7702）已存在，参考实现直接复用。

- **修改边界**：不得修改 `_LoopLock`（L1254-1299）、`_cleanup_stale_lock`（L1310-1329）、`_enforce_clean_worktree_or_exit`（L8860-8904）、`_acquire_run_lock`（L1302），不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围，不得修改 tests/ 与其他模块。
- **测试要求**：`uv run python -m py_compile src/loop_kit/_core.py`（exit 0），`uv run python -c "from loop_kit.orchestrator import _repo_lock_path, _acquire_repo_lock, _repo_lock_root_for"`（exit 0）。
- **验收标准**：
  - claim: 三符号可导入 → verify: `uv run python -c "from loop_kit.orchestrator import _repo_lock_path, _acquire_repo_lock"` → expected: exit 0
  - claim: `_repo_lock_path()` 返回 `<tempdir>/loop-kit-repo-locks/<64hex>.lock` → verify: `uv run python -c "from loop_kit import orchestrator as o; import re,pathlib; p=o._repo_lock_path(pathlib.Path('/x/y')); print(p); assert p.parent.name=='loop-kit-repo-locks' and re.fullmatch(r'[0-9a-f]{64}\.lock', p.name)"` → expected: exit 0
- **潜在风险**：`tempfile`/`hashlib` 遗漏 import → 编译期即失败（低风险）。
- **预留歧义标注**：
  - [x] 无歧义：锚点（`def _heartbeat_path(` 唯一）、实现文本、边界均给定，可直接执行。

#### Task 1.2: `cmd_run` 接入 repo 锁（先 repo 后 loop-dir）

- **目标**：`cmd_run` 中 repo 锁先于 loop-dir 锁获取，finally 逆序释放，部分获取失败不泄漏。
- **依赖**：T1.1
- **input_contracts**：`[{type: "function", identifier: "_acquire_repo_lock", contract_signature: "def _acquire_repo_lock(paths: LoopPaths | None = None) -> _LoopLock"}]`
- **output_contracts**：见 frontmatter T1.2（cmd_run 契约）
- **修改内容**：文件 `src/loop_kit/_core.py`，两处替换（锚点=当前唯一文本，行号为 25d4ccf 快照）：

  替换 ①（当前 L12620-12628，锚文本 `        lock: _LoopLock | None = None` 起、第二个 `raise StateError(str(e)) from e` 止）：

```python
        lock: _LoopLock | None = None
        repo_lock: _LoopLock | None = None
        # Lock order is fixed repo-level → loop-dir to prevent ABBA deadlock.
        # Single-round subprocesses are spawned by the parent loop which already
        # holds both locks，skip lock acquisition to avoid self-deadlock.
        if not single_round:
            try:
                repo_lock = _acquire_repo_lock(paths=resolved_paths)
            except RuntimeError as e:
                print(f"Error: {e}", file=sys.stderr)
                raise StateError(str(e)) from e
            try:
                lock = _acquire_run_lock(paths=resolved_paths)
            except RuntimeError as e:
                print(f"Error: {e}", file=sys.stderr)
                raise StateError(str(e)) from e
```

  替换 ②（当前 L12700-12702 finally 块，REFINE-1 实测修正）：

```python
        finally:
            if lock is not None:
                lock.release()
            if repo_lock is not None:
                repo_lock.release()
```

- **修改边界**：不得移动 daemon idle 早退（L12630-12639），不得改动 `_enforce_clean_worktree_or_exit` 调用（`allow_dirty`/`warn_only`/`in_scope` 传参不变），不得新增退出码，不得触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围与 tests/。
- **测试要求**：`uv run python -m py_compile src/loop_kit/_core.py`（exit 0），`uv run --group dev pytest tests/test_orchestrator.py -k 'cmd_run' -q --no-header -x`（exit 0，既有 cmd_run 测试不回归，既有测试已 monkeypatch `_acquire_run_lock`，若本改动导致任何既有测试需要同步 monkeypatch `_acquire_repo_lock`，即说明实现有误，回退重做：正确实现下既有测试**无需改动**即可通过，因为 `_acquire_repo_lock` 在 tmp ROOT 下会真实获取仓外 hash 锁并成功，若测试环境 `/tmp` 不可写则这是实现 bug 而非测试问题）。
- **验收标准**：
  - claim: 获取顺序 repo 先于 loop-dir → verify: `grep -n "_acquire_repo_lock(paths=resolved_paths)" src/loop_kit/_core.py` 命中的行号 < `grep -n "_acquire_run_lock(paths=resolved_paths)" src/loop_kit/_core.py` 命中行号（各恰 1 处） → expected: true
  - claim: 逆序释放 → verify: `sed -n '/finally:/,/except DirtyWorktreeError:/p' src/loop_kit/_core.py | grep -n "release"` 输出中 `lock.release()` 在 `repo_lock.release()` 之前 → expected: true
  - claim: 既有 cmd_run 测试不回归 → verify: `uv run --group dev pytest tests/test_orchestrator.py -k 'cmd_run' -q --no-header -x` → expected: exit 0
- **潜在风险**：既有测试中某些用例在真实 ROOT（本 repo）下跑 cmd_run 且未 mock `_acquire_run_lock` 时，现在会额外真实获取 `/tmp/loop-kit-repo-locks/...` 锁，因真实 ROOT 是干净 git 仓、无并发持锁，获取必成功、finally 必释放，无回归风险，若个别测试断言了「.loop/lock 文件内容」之类细节而受 repo 锁文件干扰，不可能（锁文件在 /tmp，与 .loop 无关）。
- **预留歧义标注**：
  - [x] 无歧义：替换块全文给定。

#### Task 1.3: 门面与所有权表同步

- **目标**：`file_bus.py` 门面与 `orchestrator.py` `_SECTION_OWNERSHIP_MAP["lock"]` 暴露新符号。
- **依赖**：T1.1
- **input_contracts**：T1.1 的 2 个 function 契约
- **output_contracts**：见 frontmatter T1.3
- **修改内容**（REFINE-2 字母序位置修正，实测 file_bus.py 快照锚定）：
  - 文件 `src/loop_kit/file_bus.py`：显式 import 列表（L10-31）按字母序加入 `_acquire_repo_lock,`（在 L11 `_acquire_run_lock,` **之前**：repo<run）与 `_repo_lock_path,`（在 `_prepare_bus_file,` 之后、`_unlock_file,` 之前：parse<prepare<repo<unlock）。执行时以唯一符号文本为锚；错误位置会触发 ruff I001。`__all__` 列表（L34-56）同位置加入 `'_acquire_repo_lock',`（L38 `'_acquire_run_lock',` 之前）与 `'_repo_lock_path',`（L54 `'_prepare_bus_file',` 与 L55 `'_unlock_file',` 之间），违反将触发 ruff RUF022。
  - 文件 `src/loop_kit/orchestrator.py`：将 L37 `    "lock": ("_lock_file", "_unlock_file", "_LoopLock", "_acquire_run_lock"),` 替换为 `    "lock": ("_lock_file", "_unlock_file", "_LoopLock", "_acquire_run_lock", "_repo_lock_path", "_acquire_repo_lock"),`。
- **修改边界**：不新增/删除其他符号，不改 `_SECTION_MODULE_PATHS`，不碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围与 tests/。
- **测试要求**：`uv run python -c "from loop_kit.file_bus import _acquire_repo_lock, _repo_lock_path; from loop_kit import orchestrator as o; assert hasattr(o, '_acquire_repo_lock')"`（exit 0），`uv run python -m py_compile src/loop_kit/file_bus.py src/loop_kit/orchestrator.py`（exit 0），`uv run ruff check --preview --select I001,RUF022 src/loop_kit/file_bus.py`（exit 0，REFINE-2 门禁：RUF022 为 preview 规则，验证 `__all__` 排序正确）。
- **验收标准**：
  - claim: 门面暴露 → verify: `uv run python -c "from loop_kit.file_bus import _acquire_repo_lock, _repo_lock_path"` → expected: exit 0
  - claim: 所有权表含新符号 → verify: `grep -c '_acquire_repo_lock' src/loop_kit/orchestrator.py` → expected: `>=1`
  - claim: 字母序位置正确（I001/RUF022）→ verify: `uv run ruff check --preview --select I001,RUF022 src/loop_kit/file_bus.py` → expected: exit 0
- **潜在风险**：`__all__`/import 顺序错位导致 ruff I001/RUF022 告警——已给定精确字母序插入位置（REFINE-2 实测锚定：`_prepare_bus_file,` 之后、`_unlock_file,` 之前；执行时以唯一符号文本为准）并增加定向 ruff 门禁兜底。
- **预留歧义标注**：
  - [x] 无歧义。

### Phase 2: 测试（仅 tests/test_orchestrator.py 文件末尾追加）

> 追加区相互顺序：T2.1 → T2.2 → T2.3，均以**当时 EOF** 为锚点顺序追加。既有 603 个测试函数一律不动。
> 测试风格参照既有约定：`_isolate_orchestrator_path_globals` autouse fixture 自动恢复 `ROOT`/`_stored_paths`，monkeypatch 直接对 `orchestrator.` 属性生效（模块别名），`_run_config()` 助手（L3874），`_NoopLock` 模式（L4466-4471，REFINE-1 实测修正起点行号）。git 仓创建模式见 L2172：`subprocess.run(["git", "init", "-q"], cwd=repo, check=True)`。

#### Task 2.1: repo 锁单元测试（路径哈希 / 获取 / 冲突 / pid 记录）

- **目标**：追加 `TestRepoLockPath` / `TestAcquireRepoLock` / `TestRepoLockPidRecord`，覆盖哈希确定性、冲突报错、覆盖式 pid、PID 复用不误判。
- **依赖**：T1.1
- **input_contracts**：`[{type: "function", identifier: "_repo_lock_path", ...}, {type: "function", identifier: "_acquire_repo_lock", ...}]`
- **output_contracts**：见 frontmatter T2.1
- **修改内容**：文件 `tests/test_orchestrator.py` 末尾追加三个测试类。**用例清单（TE 据此实现，断言目标即验收）**：

`TestRepoLockPath`：
  1. `test_same_root_same_path`，同 root 两次调用返回相同 Path
  2. `test_different_roots_different_paths`，两个不同 root 路径不同
  3. `test_lock_filename_is_sha256_hex`，文件名匹配 `[0-9a-f]{64}\.lock`
  4. `test_git_repo_uses_toplevel`，tmp_path 下 `git init` + `git config user.*` + `git commit`（复用既有 L2172 模式：`subprocess.run(["git", "init", "-q"], cwd=repo, check=True)`），`_repo_lock_path(root=repo)` 的 hash 与 `_repo_lock_path(root=repo.resolve())` 一致（toplevel 归一）
  5. `test_non_git_falls_back_to_resolve`，非 git tmp dir：`_repo_lock_path(root=d)` == `_repo_lock_path(root=d.resolve())`

`TestAcquireRepoLock`：
  1. `test_acquire_and_release`，monkeypatch `orchestrator.ROOT` 为 tmp_path 后走**完整 `_acquire_repo_lock` 路径（唯一路径，REFINE-2 修正）**，断言：① 返回 `_LoopLock` 实例；② `release()` 后可再次 `_acquire_repo_lock` 成功；③ 首次获取成功后锁文件内容 == `pid:{os.getpid()}\n`（覆盖式写入语义直接在用例 1 断言）。**禁止**绕过 `_acquire_repo_lock` 直接实例化/操作 `_LoopLock` 来验证（原计划的「或直接调用 `orchestrator._LoopLock(...)` 验证底层」分支删除——`_LoopLock` 只被 `_acquire_repo_lock` 内部复用，测试不得触碰，否则覆盖式写入语义漏测）
  2. `test_conflict_raises_with_distinct_message`，先获取锁，二次 `_acquire_repo_lock` 抛 RuntimeError 且消息含 `"another loop run is already using this working tree"`（不含旧消息 `"another orchestrator instance"`）
  3. `test_oserror_wrapped_fail_closed`，monkeypatch `_LoopLock` 为 acquire 时抛 OSError 的替身（或 monkeypatch `_repo_lock_path` 指向不可写路径如 `/proc/x/y`），断言 `_acquire_repo_lock` 抛 RuntimeError（非裸 OSError）
  4. `test_single_round_and_daemon_unaffected_at_unit_level`，不适用（单元层不涉及），跳过，改由 T2.2 覆盖

`TestRepoLockPidRecord`：
  1. ~~`test_acquire_overwrites_stale_pid`~~（**REFINE-3 删除，不实现**：原设计直接 `_LoopLock(_repo_lock_path(root=tmp_path)).acquire()` 并断言覆盖式写入，触碰 `_LoopLock` 违反冻结区边界；且其断言「获取后锁文件 == `pid:{os.getpid()}\n`」与 `TestAcquireRepoLock` 用例 1 断言 ③ 完全重复——覆盖式写入/覆盖式清理语义已由 `TestAcquireRepoLock` 用例 1 经 `_acquire_repo_lock` 完整路径断言，本重复用例不再实现）
  2. `test_alive_unrelated_pid_does_not_block`，monkeypatch `orchestrator.ROOT` 为 tmp_path，预写 `_repo_lock_path()`（无参，经 ROOT 解析）锁文件内容 `pid:{os.getpid()}\n`（当前测试进程自身 pid：存活但未持 flock）→ 走**完整 `_acquire_repo_lock` 路径**（唯一路径，禁止直接 `_LoopLock`，REFINE-3 明确）acquire 成功（flock 唯一权威，PID 复用防护）
  3. `test_diagnostic_reads_pid_but_never_authoritative`，经**完整 `_acquire_repo_lock` 路径**（monkeypatch `orchestrator.ROOT`=tmp_path）先持锁并确保文件含当前 pid（== os.getpid()），用另一线程二次 `_acquire_repo_lock` 捕获 RuntimeError，断言（REFINE-2 适配同进程 self-pid 分支）消息**含当前 pid 数字**（`str(os.getpid()) in msg`）或含 `"holder unknown"`——self-pid 分支下 `_repo_lock_diagnostic` 返回 `stale or reused pid record (N)`（含 pid 数字），**不得**断言 `"held by pid"`（该文案仅在 pid 非自身且 kill(0) 存活时出现，同进程测试无法触发，误断言必失败）；随后把文件改成 `not-a-pid`，再次冲突断言消息不含数字 pid 且不抛解析异常（防御解析，兜底 `"holder unknown"`）
  4. `test_malformed_pid_line_tolerated`，monkeypatch `orchestrator.ROOT` 为 tmp_path，预写 `_repo_lock_path()`（无参）锁文件内容为 64+ 字节乱码 → 走**完整 `_acquire_repo_lock` 路径** acquire 不受影响

- **修改边界**：只追加，不改既有测试函数/conftest，测试内调用 `_repo_lock_path()` 必须传 `root=tmp_path` 或先 monkeypatch `ROOT`（禁止对真实 repo 加锁），不碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围。**REFINE-2 补充**：测试不得直接实例化 `_LoopLock` 来验证 `_acquire_repo_lock` 语义（`_LoopLock` 只由 `_acquire_repo_lock` 内部复用，绕过即漏测覆盖式写入；唯一例外是 T2.3 用例 2 以测试进程扮演外部持锁者时的 holder 用法）。**REFINE-3 追加（冻结区边界终态）**：`TestRepoLockPidRecord` 原用例 1（直接 `_LoopLock(...).acquire()` 断言覆盖式写入）已删除，覆盖式写入语义由 `TestAcquireRepoLock` 用例 1 经完整路径断言；本类剩余用例（2/3/4）全部走完整 `_acquire_repo_lock` 路径（已逐用例标注）。**全计划直接使用 `_LoopLock` 的唯一允许点 = T2.3 用例 2 外部持锁者 holder**。
- **测试要求**：`uv run --group dev pytest tests/test_orchestrator.py -k 'RepoLockPath or AcquireRepoLock or RepoLockPidRecord' -v` → 预期 exit 0、全部通过。
- **验收标准**：
  - claim: 三个新测试类全绿 → verify: 上述 pytest -k 命令 → expected: exit 0
  - claim: 既有锁测试不回归 → verify: `uv run --group dev pytest tests/test_orchestrator.py -k '_LoopLock or acquire_run_lock or cleanup_stale_lock' -q` → expected: exit 0
- **潜在风险**：`test_git_repo_uses_toplevel` 依赖本机 git 可用（既有测试已依赖，见 L2172），ROOT monkeypatch 与 autouse fixture 恢复顺序（monkeypatch 先于 fixture teardown 恢复，无泄漏）。
- **预留歧义标注**：
  - [x] 无歧义：用例清单逐条给定。

#### Task 2.2: cmd_run 锁语义集成测试

- **目标**：追加 `TestCmdRunRepoLock`：获取顺序、single_round 跳过、冲突 exit 5、部分获取失败不泄漏、daemon warn_only 语义不变。
- **依赖**：T1.2、T2.1
- **input_contracts**：`[{type: "function", identifier: "cmd_run", ...}]`
- **output_contracts**：见 frontmatter T2.2
- **修改内容**：文件 `tests/test_orchestrator.py` 末尾（T2.1 之后）追加。**用例清单**：

  1. `test_cmd_run_acquires_repo_lock_before_loop_lock`，monkeypatch `_acquire_repo_lock`/`_acquire_run_lock` 为记录调用顺序的 recorder（返回 `_NoopLock` 实例，含 release()），monkeypatch `_dirty_tracked_paths` → []、`_main_loop` → noop，`cmd_run(_run_config(".loop/task_card.json"), single_round=False, round_num=None)` 正常返回后断言顺序 == ["repo", "loop_dir"] 且两个 release 均被调用、release 顺序 == ["loop_dir", "repo"]
  2. `test_cmd_run_single_round_skips_repo_lock`，monkeypatch `_acquire_repo_lock` 为 `lambda paths=None: (_ for _ in ()).throw(AssertionError("must not be called"))`，monkeypatch `_run_single_round` noop，`cmd_run(..., single_round=True, round_num=1)` 正常返回（参照 L4485 test_cmd_run_allow_dirty_bypasses_guard 模式）
  3. `test_cmd_run_repo_lock_conflict_exits_5`，monkeypatch `_acquire_repo_lock` 抛 `RuntimeError("another loop run is already using this working tree (held by pid 1) (lock: /tmp/x)")`，`pytest.raises(SystemExit)` code == 5 且 capsys stderr 含该消息（参照 L8856 模式）
  4. `test_cmd_run_releases_repo_lock_when_loop_lock_fails`，recorder1 返回可用 `_NoopLock`，`_acquire_run_lock` 抛 RuntimeError，断言 exit 5 且 recorder1 的 release 已被调用（B7 部分获取释放）
  5. `test_cmd_run_daemon_warn_only_semantics_unchanged`，`_dirty_tracked_paths` → ["src/foo.py"]，`_acquire_repo_lock`/`_acquire_run_lock` → `_NoopLock`，`_main_loop` noop，写入最小 task card（`{"task_id":"T-DAEMON-1","title":"t","goal":"g"}`）到 tmp loop dir 并让 `_load_task_card_or_raise` 读它，`cmd_run(..., daemon_mode=True)` 正常返回（warn_only 放行），再以 `in_scope=["src/foo.py"]` 配置的 card 断言 exit 4（scope overlap 拒绝路径）。若 `_load_task_card_or_raise` monkeypatch 复杂度过高，降级为：直接断言 `_enforce_clean_worktree_or_exit` 收到的 `warn_only == daemon_mode`（recorder 包装）+ 既有 warn_only 测试（L14866-14877）作为语义不回归的权威守卫。

- **修改边界**：只追加，不得改写 `_enforce_clean_worktree_or_exit` 实现，不得修改 T2.1 追加区，不碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围。
- **测试要求**：`uv run --group dev pytest tests/test_orchestrator.py -k 'CmdRunRepoLock or enforce_clean_worktree_warn_only' -v` → exit 0。
- **验收标准**：
  - claim: 五条集成用例全绿 → verify: pytest -k 'CmdRunRepoLock' -v → expected: exit 0
  - claim: warn_only 既有测试不回归 → verify: `uv run --group dev pytest tests/test_orchestrator.py -k 'warn_only' -v` → expected: exit 0
- **潜在风险**：用例 5 依赖 `_load_task_card_or_raise` 对 card 字段的容忍度，若 TE 发现该函数对最小 card 抛 ConfigError，按「降级方案」实施 recorder 断言（已在用例 5 中写明降级路径，不阻塞）。
- **预留歧义标注**：
  - [x] 无歧义（含降级路径）。

#### Task 2.3: 脏树单次失败无重试 + 历史回放测试

- **目标**：追加 `TestDirtyTreeFailFastNoRetry`（in-process 计数断言）与 `TestHistoricalReplayT3151T3152`（真实子进程回放）。
- **依赖**：T1.2、T2.2
- **input_contracts**：`[{type: "function", identifier: "_repo_lock_path", ...}, {type: "function", identifier: "cmd_run", ...}]`
- **output_contracts**：见 frontmatter T2.3
- **修改内容**：文件 `tests/test_orchestrator.py` 末尾追加。**用例清单**：

`TestDirtyTreeFailFastNoRetry`：
  1. `test_dirty_tree_enforced_exactly_once_and_exits_4`，用计数包装器包裹 `_enforce_clean_worktree_or_exit`（`calls+=1` 后调用原函数），`_dirty_tracked_paths` → ["src/foo.py"]，`_acquire_repo_lock`/`_acquire_run_lock` → `_NoopLock`，`_main_loop` 用「被调用即失败」哨兵，`cmd_run(...)` 断言：`SystemExit.code == 4`、`calls == 1`、`_main_loop` 哨兵未被触发、`time.monotonic()` 耗时 < 1.0s、capsys stderr 含 "src/foo.py"（脏文件清单）
  2. `test_dirty_tree_error_message_lists_dirty_files`，复用用例 1 结构，断言 stderr 含 "dirty git working tree" 与全部脏路径（验证 PM 产出 1 已满足、不回退）

`TestHistoricalReplayT3151T3152`（全部用 tmp_path 内真实 git 仓 + 真实子进程 `[sys.executable, "-m", "loop_kit", "run", "--loop-dir", str(repo/".loop"), "--task", str(card)]`，`cwd=repo`，`capture_output=True, text=True, timeout=60`）：
  1. `test_replay_t3151_dirty_tree_fails_once_fast`，建仓→commit→改 tracked 文件→写最小 task card，断言 `returncode == 4`、耗时 < 10s（历史基线约 300s，10s 上限仅为防 CI 抖动，证明「无 3 次重试等待」）、stderr 含 "dirty git working tree" 与脏文件名、stdout+stderr 不含 "[Worker] Running"（未进入 dispatch/重试）
  2. `test_replay_repo_lock_conflict_exits_5_fast`，建仓→commit→card，测试进程内先 `holder = orchestrator._LoopLock(orchestrator._repo_lock_path(root=repo)); holder.acquire()`（**必须经 `_repo_lock_path(root=repo)` 取路径，保证与子进程 hash 完全一致**，Lens C3），`try/finally` 中跑子进程，断言 `returncode == 5`、耗时 < 10s、stderr 含 "another loop run is already using this working tree"，finally 中 `holder.release()`
  3. `test_replay_clean_tree_after_release_acquires_normally`，用例 2 释放后重跑子进程（此时会越过 repo 锁与脏树检查、进入 `_main_loop`）。**REFINE-2：显式捕获 `subprocess.TimeoutExpired` 并定义超时证据语义，避免测试 ERROR**（`subprocess.run(..., timeout=60)` 超时即抛 TimeoutExpired，原计划未捕获 → 该用例必然 ERROR 而非 PASS）：
     - 捕获 `subprocess.TimeoutExpired` → 测试 **PASS**（超时证据语义：子进程未在 60s 内退出，说明它已越过 repo 锁（未 exit 5）、越过脏树检查（未 exit 4）、进入后续阶段等待 PM 依赖——恰好证明本用例验收目标「锁已释放且脏树检查通过」；在测试注释与 `assert` 失败消息中显式写明该语义，使超时路径不被误读为测试失败）
     - 未超时 → 断言 `returncode not in (4, 5)`（证明锁已释放且脏树检查通过进入后续阶段，后续阶段可能因缺 PM 依赖退出其他码，故不断言具体码，仅排除 4/5）
     - 用例 1/2 **不得**捕获 TimeoutExpired（那两处超时=失败证据，`<10s` 断言必须有约束力）

- **修改边界**：只追加，严禁在真实 repo 上跑回放，不依赖网络/PM，不碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围。
- **测试要求**：`uv run --group dev pytest tests/test_orchestrator.py -k 'DirtyTreeFailFastNoRetry or HistoricalReplay' -v --durations=10` → exit 0 且用例 1/2 <10s，用例 3 60s 超时证据 PASS。
- **验收标准**：
  - claim: 脏树单次失败无重试用例通过 → verify: pytest -k 'DirtyTreeFailFastNoRetry' -v → expected: exit 0
  - claim: 历史回放用例 1/2 通过且 <10s，用例 3 60s 超时证据 PASS → verify: pytest -k 'HistoricalReplay' -v --durations=10 → expected: exit 0
- **潜在风险**：子进程 `loop run` 需要 `.loop` 目录可建（tmp 仓内，无风险），用例 3 的后续阶段行为在未来版本可能变化，已用「排除 4/5」而非「断言具体码」+「TimeoutExpired 显式捕获 → 超时证据 PASS」（REFINE-2）双重消解脆弱性与 ERROR 风险。
- **预留歧义标注**：
  - [x] 无歧义。

### Phase 3: 全量回归与收尾

#### Task 3.1: 全量回归 + lint + 提交 + PM 建议

- **目标**：全量验证零回归，按 commit 约定提交（每 task 一 commit，`[Plan: pm3155-repo-mutex-lock] T<x.y>` 前缀），复核提交范围。
- **依赖**：T1.3、T2.3
- **input_contracts**：`[]`
- **output_contracts**：见 frontmatter T3.1（git:committed state_change）
- **修改内容**：无源码修改。执行：
  1. `git status --porcelain` 复核：仅本计划 4 源码文件（改动的）+ 3 个 pre-existing untracked 项（`.github/plans/biweekly-reporting-restore-2026-08-27.md`、`.github/plans/pm3155-repo-mutex-lock.md` 本计划文件自身、`data/`——三者**绝不进 commit**）
  2. 逐文件 `git add src/loop_kit/_core.py src/loop_kit/file_bus.py src/loop_kit/orchestrator.py tests/test_orchestrator.py`（**禁止 `git add -A`**）
  3. `git diff --cached --stat` 负向验证（AGENTS.md Commit Scope Verification）：无 surprise hunks
  4. commit，随后运行 Post-Execution Verification 全部命令
  5. 若全部通过：建议（不直接执行）经 pm-coordinator 更新 PM #3155 状态/notes
- **修改边界**：不修改任何文件内容，不触碰 执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围，不直接调用 PM 写工具。
- **测试要求**：见 Post-Execution Verification V1-V6。
- **验收标准**：
  - claim: 全量测试零失败 → verify: `uv run --group dev pytest -q` → expected: exit 0
  - claim: lint 零错误 → verify: `uv run ruff check src/loop_kit tests` → expected: exit 0
  - claim: 提交范围正确 → verify: `git show --stat --oneline HEAD` 仅含 4 个计划内路径 → expected: true
- **潜在风险**：全量测试耗时较长（615+ 用例），TE 需设置充足 timeout，若出现与本计划无关的既有失败，记录但不得在本任务内修复（范围外）。
- **预留歧义标注**：
  - [x] 无歧义。

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | 依赖已完成 |
|------|------------|------------|
| W1 | T1.0, T1.1（同文件 `_core.py` 不相邻区域，TE 按 T1.0→T1.1 顺序执行防写冲突） |，|
| W2 | T1.2, T1.3 | W1 |
| W3 | T2.1 | W2 |
| W4 | T2.2 | W3 |
| W5 | T2.3 | W4 |
| W6 | T3.1 | W5 |

**排序理由（CoT Stage 4）**：⓪ T1.0（REFINE-1 新增）先于/同波次于 T1.1——它是 V6/T2.3 回放可执行性的前置修复，但与 T1.1 修改 `_core.py` 不相邻区域，故同 wave 按序执行；① T1.1 先于 T1.2/T1.3/T2.1（均消费其函数契约），② T1.2 与 T1.3 修改互不相交文件（_core.py vs file_bus.py+orchestrator.py）故可并行，但都依赖 T1.1，③ T2.1→T2.2→T2.3 全部追加于同一文件 `tests/test_orchestrator.py`，技术上可并行编辑，但同文件追加会互相锚定 EOF 造成冲突/覆盖，故强制串行（此为该计划唯一的非并行点，明确选择），④ T3.1 聚合全部验证与提交。
**失败回滚策略（逐 task）**：每个 task 独立 commit，失败即 `git revert <commit>`（fix-forward 优先：就地修正后重跑该 task 测试），T1.0 失败（回归）直接 revert T1.0 单 commit；T1.2 失败不影响 T1.1/T1.3 产物（T1.3 仅门面暴露，函数存在即可），测试 task 失败只需 revert 该测试追加区，不影响实现，全程不 reset 实现侧 commit（避免连锁 revert）。完整回滚顺序见「修改文件清单与验收/回滚汇总」节。

## Post-Execution Verification

Task Executor 在所有 plan task 执行完毕后**必须**运行本节中的验证命令。

### Automated Verification（Task Executor 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量单元测试（排除 e2e） | `uv run --group dev pytest -q` | exit 0，0 failed |
| V2 | 新功能定向测试 | `uv run --group dev pytest tests/test_orchestrator.py -k 'RepoLockPath or AcquireRepoLock or RepoLockPidRecord or CmdRunRepoLock or DirtyTreeFailFastNoRetry or HistoricalReplay' -v` | exit 0 |
| V3 | Lint | `uv run ruff check src/loop_kit tests` | exit 0，0 errors（PM #2749 基线）；RUF022 为 preview 规则由 T1.3 定向校验 `--preview --select I001,RUF022` 覆盖 |
| V4 | 编译检查 | `uv run python -m py_compile src/loop_kit/_core.py src/loop_kit/file_bus.py src/loop_kit/orchestrator.py` | exit 0 |
| V5 | 门面暴露核查 | `grep -c "_acquire_repo_lock" src/loop_kit/file_bus.py` && `grep -c "_repo_lock_path" src/loop_kit/file_bus.py` && `grep -c "_acquire_repo_lock" src/loop_kit/orchestrator.py` | 三个输出均 `>=2` / `>=2` / `>=1` |
| V6 | 脏树快失败复现（独立脚本） | `tmp=$(mktemp -d) && git -C "$tmp" init -q && git -C "$tmp" config user.email t@t && git -C "$tmp" config user.name t && echo x > "$tmp/f" && git -C "$tmp" add -A && git -C "$tmp" commit -qm i && echo y >> "$tmp/f" && echo '{"task_id":"V6","title":"t","goal":"g"}' > "$tmp/card.json" && start=$(date +%s); (cd "$tmp" && uv run --project /home/gw/opt/agent-task-runner python -m loop_kit run --loop-dir "$tmp/.loop" --task "$tmp/card.json" >/dev/null 2>"$tmp/err"); rc=$?; end=$(date +%s); cat "$tmp/err"; echo "rc=$rc elapsed=$((end-start))"; rm -rf "$tmp"; test $rc -eq 4 -a $((end-start)) -lt 10 | exit 0，输出 rc=4 elapsed<10，stderr 含 dirty git working tree |
| V7 | 计划文件 AI 痕迹门禁（Plan 侧） | `de-ai-fier/deai_review_file(path=.github/plans/pm3155-repo-mutex-lock.md, doc_type="plan", strict=false)` | 无 error/critical 级 finding，MCP 不可用标注 [⚠️ skipped] |

### Deferred (needs restart / deployment)

- 无（本计划不涉及服务重启/部署）

### Probe (best-effort, run if available)

- [ ] P1: `uv run python -c "import tempfile, pathlib; from loop_kit import orchestrator as o; print(o._repo_lock_path(pathlib.Path('/probe/x')))"` → 输出以 `/tmp/loop-kit-repo-locks/` 开头（验证运行时 tempdir 解析正常）

### Manual（真正需要人工判断）

- [ ] M1: 人工复核 `/tmp/loop-kit-repo-locks/` 目录，确认残留锁文件为覆盖式 `pid:` 记录（残留属预期、非泄漏），若发现长期堆积且无 loop 运行，可清理（清理前确认无 `loop run` 进程）
- [x] M2: 人工确认 PM #3155 状态更新（经 pm-coordinator 委派，属建议步骤）（回填 2026-10-13：PM #3155 = done，DB 实测）

## 风险 / 回滚矩阵

| # | 风险 | 概率 | 影响 | 缓解措施 | 回滚动作 |
|---|------|------|------|---------|---------|
| R1 | 与既有 loop-dir 锁/脏树检查行为互扰，造成回归 | 低 | 高（核心路径） | 不改旧函数一行，全量 pytest（V1）+ lint（V3）门禁，T1.2 要求「既有测试零改动通过」作为正确性判据 | `git revert` 对应 task commit（每 task 独立 commit） |
| R2 | `/tmp` 不可写/受限环境 → 所有 loop run 被 fail-closed 阻断 | 低 | 高（可用性） | `_acquire_repo_lock` OSError → RuntimeError → exit 5 显式报错（不静默），未来可加 `LOOP_REPO_LOCK_DIR` 环境变量（本计划不做） | revert T1.1+T1.2，或临时 `chmod` 恢复 /tmp 写权限 |
| R3 | 锁文件残留堆积（/tmp 清理策略缺失） | 中 | 低（仅磁盘占用） | flock 随进程消亡释放，残留文件为纯诊断记录，不影响后续获取，M1 人工清理通道 | `rm /tmp/loop-kit-repo-locks/*.lock`（确认无 loop 运行后） |
| R4 | 多 worktree / lane 子仓并发未被主仓锁覆盖（语义误解） | 中 | 中（保护面不全） | 设计即预期：hash 含 worktree 路径，各 worktree 独立互斥，主工作树污染仍被各自锁防护 | 无（若未来需跨 worktree 互斥，属新需求，不在此回滚） |
| R5 | 子进程与父进程 hash 不一致 → 回放测试假阳性/假阴性 | 低 | 中（测试可信度） | 双方统一经 `_repo_lock_path(root=...)` 计算，T2.3 用例 2 显式用同一 helper（Lens C3 修正） | 修正测试内路径获取方式，无需回滚实现 |
| R6 | PID 复用误判（假冲突/假放行） | 低 | 低（诊断失真） | flock 唯一权威（D2/D4），pid 仅入诊断文案（`_pid_is_live` 为 `os.kill(pid,0)` 单层存活探测，不参与放行判定） | revert（若未来平台差异引发问题） |
| R7 | 脏树 fail-fast 语义被误伤（warn_only/daemon） | 低 | 高（历史故障复发） | `_enforce_clean_worktree_or_exit` 及其调用点零改动（T1.2 边界），T2.2 用例 5 + 既有 warn_only 测试（L14866-14877）双守卫 | revert T1.2 |
| R8 | 计划锚点漂移（_core.py 行号变动） | 中 | 低（执行歧义） | 每 Phase 首步基线漂移重检，锚点以唯一文本为主、行号为辅，T1.x 均附完整替换文本 | 更新锚点后重执行，无需回滚 |
| R9 | 全量测试耗时/环境抖动导致 V1 假失败 | 低 | 低 | TE 设充足 timeout，与计划无关的既有失败只记录不修复 | 重跑 V1，定位与计划外失败隔离 |
| R10 | `_git_at` porcelain 输出前导空格被 `.strip()` 剥离 → 脏树检测静默失效/路径腐蚀（REFINE-1 实测确认，已由 T1.0 修复） | 已发现（修复前：1-2 字符脏路径 100% 静默通过） | 高（脏树 fail-fast 正确性、V6/T2.3 可执行性） | T1.0 单行修复 `.rstrip()` + 复现命令 + `-k 'dirty or worktree or merge or clean'` 回归；L7437/L7645 两处真值消费点经核对不受影响 | revert T1.0（若 T1.0 尚未落地时跳过 T2.3/V6 不可接受——必须先修后测） |

**整体回滚**：所有 commit 携带 `[Plan: pm3155-repo-mutex-lock]` 前缀，`git log --grep` 可一次性定位并逆序 revert，回滚后运行 V1 确认回到基线（615+ 通过 / 0 failed）。

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（字段/编号/契约完备性） | 2 | 2 | 0 |
| R1.5 | 外部引用事实核查（锚点/符号/命令逐一 read+grep 验证） | 3 | 3 | 0 |
| R2 | 可执行性（粒度 ≤3 文件/依赖无环/脚本干跑） | 2 | 2 | 0 |
| R2.8 | LLM 可执行性审查（歧义消解） | 4 | 4 | 0 |
| R3 | 风险与边缘（跨轮一致性 + What-If + 回滚安全） | 2 | 2 | 0 |
| REFINE-1 | 执行前基线重核（HEAD/sha256/untracked 项/锚点全量实测 + V6 冒烟） | 5 | 5 | 0 |
| REFINE-2 | CT 四项 blocking 落实（T1.3 字母序位置 / T2.1 用例 1、3 / T2.3 用例 3 TimeoutExpired）+ 调用点重数 + 死代码简化注明 | 6 | 6 | 0 |
| REFINE-3 | CT 最终发现落实（T2.1 TestRepoLockPidRecord 用例 1 删除 + 用例 2/3/4 全走 `_acquire_repo_lock`；R6/T1.1 风险 `/proc/<pid>/stat` 残留文字清理；冻结区边界唯一例外收窄为 T2.3 用例 2） | 3 | 3 | 0 |
| **终止** | **[T1]，收敛终止（REFINE-3 落实 CT 最终发现后复审通过，剩余 issue=0，详见 REFINE-3 Issues 节）** | | | **0** |

### R1 Issues
- **Issue R1-1**: T2.x 三个任务同文件追加，Execution Wave 若并行会互相覆盖 EOF 锚点 → 强制串行 W3-W5 并在 CoT Stage 4 写明理由 ✅ 已修正
- **Issue R1-2**: T3.1 无 modify_specs 但 R2.5 要求字段非空 → T3.1 明确 `modifications: []` + `modify_specs: []`（纯验证任务语义）并补 input/output_contracts ✅ 已修正

### R1.5 Issues
- **Issue R1.5-1**: `_cleanup_stale_lock` 结束行/`_heartbeat_path` 定义行锚点凭记忆 → 原始 read 确认写入 L1332/L1338（25d4ccf 快照）[verified: src/loop_kit/_core.py:L1311-1338] ✅ 已修正。**REFINE-1 复核：原始行号有误**，实测 `_log(...)` 末行=L1329、`def _heartbeat_path`=L1332、`_cleanup_stale_lock`=L1310-1329，已全部就地更新（见 REFINE-1 记录）
- **Issue R1.5-2**: 命令 `uv run python -m loop_kit run` 在 V6 中的 `--project` 用法未验证 → 改写为 `(cd "$tmp" && uv run --project /home/gw/opt/agent-task-runner python -m loop_kit ...)`，保证 venv 解析独立于 cwd [verified: pyproject 位于仓根] ✅ 已修正
- **Issue R1.5-3**: 既有测试数/门面文件结构凭记忆 → 实测 603 个测试函数、file_bus.py 显式 import 列表结构、orchestrator.py 模块别名机制 [verified: read 实测] ✅ 已修正
- **CAP-OK**: 新增组件 `_repo_lock_path`/`_acquire_repo_lock` 与既有能力（`_LoopLock`/`_acquire_run_lock`）无重复，明确为「复用 flock 机制 + 新命名空间」，非重建 ✅

### R2 Issues
- **Issue R2-1**: T1.1 实现草稿中 `_pid_is_live` 的 /proc 解析分支过度复杂（`_pid_is_self_start_match` 冗余）→ 简化为「kill(0) + /proc 启动时间比对 + 全面 try/except 兜底」，并在计划中显式允许 TE 进一步简化，仅锁定「pid 不参与放行判定」不变量 ✅ 已修正
- **Issue R2-2**: V6 脚本中 `git config` 缺失 → 补 user.email/user.name ✅ 已修正

### R2.8 Issues
- **Issue R2.8-1** [AMBIGUITY-FIXED]: T2.1 用例 1「或直接调用底层」存在二义 → 明确「monkeypatch ROOT=tmp_path 走完整 `_acquire_repo_lock` 路径」为主路径 ✅
- **Issue R2.8-2** [AMBIGUITY-FIXED]: T2.2 用例 5 对 `_load_task_card_or_raise` 的 card 容忍度不确定 → 写明降级路径（recorder 断言 + 既有 warn_only 测试守卫），不阻塞 ✅
- **Issue R2.8-3** [AMBIGUITY-FIXED]: T2.3 用例 3 对全流程断言太脆弱 → 改为「排除 4/5」而非断言具体码 ✅
- **Issue R2.8-4** [BLIND-SPOT]: `_acquire_repo_lock` 未在 `_SECTION_OWNERSHIP_MAP`/file_bus 门面暴露 → T1.3 专设（依赖 T1.1，顺序正确无先鸡后蛋）✅

### R3 Issues
- **Issue R3-1**: T1.2 若 `_acquire_run_lock` 失败而 repo_lock 已获 → 泄漏风险 → 嵌套 try + finally 无条件释放 repo_lock（B7），并加 T2.2 用例 4 显式覆盖 ✅ 已修正
- **Issue R3-2**（跨轮一致性）: T2.3 回放用例 2 需与 T1.1 的 hash 实现严格一致 → 统一经 `_repo_lock_path(root=repo)`（Lens C3），与前轮「hash 归一」原则无冲突 ✅ 已修正

### REFINE-1 Issues（2026-09-03 执行前基线重核，全实测）

- **Issue REFINE-1-1 [FIXED — untracked 项过期]**: 计划快照写「执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围」，实测 `git status --porcelain` 为 **3 项**：新增第 3 项 = 本计划文件自身 `.github/plans/pm3155-repo-mutex-lock.md`（计划生成于快照之后且未 commit）。全文 18 处措辞统一为 3 项，并在两处枚举清单中补入计划文件自身 ✅
- **Issue REFINE-1-2 [FIXED — 锚点过期/原始行号错误]**: HEAD 与 4 文件 sha256 均与 context 快照一致（代码零漂移），但原始计划多处行号与实测不符，逐一修正：`_cleanup_stale_lock` L1311-1332→**L1310-1329**、`_log(...)` L1332→**L1329**、`_heartbeat_path` L1338→**L1332**、`_LoopLock` 尾 L1298→**L1299**、`_enforce_clean_worktree_or_exit` 尾 L8903→**L8904**、daemon idle 早退 L12631-12641→**L12630-12639**、finally 块 L12699-12701→**L12700-12702**、`main()` L13818→**L13811**、`_knowledge_write_lock` L10971→**L10970**、`_NoopLock` L4467→**L4466** ✅
- **Issue REFINE-1-3 [FIXED — 测试锚点精确化]**: 「既有 L2172 模式」实为 `subprocess.run(["git", "init", "-q"], cwd=repo, check=True)`（裸 grep `git init` 零命中会误导 TE），已在 Phase 2 导言/T2.1 用例 4/T2.3 边界三处补精确文本 ✅
- **Issue REFINE-1-4 [FIXED — import 状态确认]**: `import hashlib` 已存在（L18），`import tempfile` 缺失需补——原注「当前快照未确认」升级为「已核实」并给定插入位置（`import sys` L29 之后字母序） ✅
- **Issue REFINE-1-5 [FIXED — V6/T2.3 前置缺陷，新增 T1.0]**: V6 等价冒烟实测（tmp 脏仓 + `uv run --project ... python -m loop_kit run`）未在 <10s 内 exit 4 而是挂起至 60s SIGTERM（rc=124）。根因：`_git_at` L6882 `result.stdout.strip()` 剥离 porcelain XY 前导空格 → `_dirty_tracked_paths` 解析错位（1-2 字符路径静默跳过、≥3 字符路径首字符被吞，实测 `['rc/foo.py']`）。新增 **T1.0** 单行修复（`.strip()`→`.rstrip()`），冻结名单（`_LoopLock`/`_cleanup_stale_lock`/`_enforce_clean_worktree_or_exit`）未触碰；L7437/L7645 两处 porcelain 真值消费点经核对不受影响。同时补齐产出 1 scope 澄清、修改文件清单、验收/回滚手册三节 ✅
- **CAP-OK（REFINE-1 复检）**: T1.0 修复复用既有 `_git_at` 函数（1 行变更），非新增平行能力；T1.1 函数组与既有 `_LoopLock`/`_acquire_run_lock` 为「复用 flock 原语 + 新命名空间」关系不变 ✅

### REFINE-2 Issues（2026-09-03 CT 四项 blocking 落实，全部实测核对）

- **Issue REFINE-2-1 [FIXED — CT blocking 1：T1.3 插入位置字母序错误]**：原计划写 `_repo_lock_path,` 插在 `_parse_artifact_identity,` 之前。实测 file_bus.py：`_parse_artifact_identity`（L27）、`_prepare_bus_file`（L28）、`_unlock_file`（L29）；字母序 `_parse`(pa) < `_prepare`(pre) < `_repo`(re) < `_unlock`(un)，正确位置为 `_prepare_bus_file` 与 `_unlock_file` **之间**，原位置必触发 ruff I001（import 排序）。已同步修正 frontmatter modify_specs、修改文件清单表、正文 T1.3，并在 T1.3 test_commands/验收标准增加 `uv run ruff check --preview --select I001,RUF022 src/loop_kit/file_bus.py` 定向门禁（RUF022 = `__all__` 排序，preview 规则）。`_acquire_repo_lock` 插 `_acquire_run_lock` 前的位置原计划正确（repo<run），保留 ✅
- **Issue REFINE-2-2 [FIXED — CT blocking 2：T2.1 用例 1 触碰 `_LoopLock`]**：原用例 1 含「或直接调用 `orchestrator._LoopLock(...)` 验证底层」的二义分支，绕过 `_acquire_repo_lock` 将漏测覆盖式写入语义。已删除该分支，改为唯一路径 monkeypatch `ROOT=tmp_path` 走完整 `_acquire_repo_lock`，并新增断言 ③ 获取后锁文件 == `pid:{os.getpid()}\n`；T2.1 边界同步补「测试不得直接实例化 `_LoopLock`」条款（T2.3 用例 2 外部持锁者 holder 用法为唯一例外）✅
- **Issue REFINE-2-3 [FIXED — CT blocking 3：T2.1 用例 3 误断言 held by pid]**：同进程 self-pid 分支下 `_repo_lock_diagnostic` 返回 `stale or reused pid record (N)`（`pid != os.getpid()` 条件不成立），原断言「消息含 `held by pid`」必失败。已改为断言消息含当前 pid 数字（`str(os.getpid()) in msg`）或 `"holder unknown"`，并显式写明**不得**断言 `"held by pid"`（该文案仅 pid 非自身且存活时出现，同进程无法触发）✅
- **Issue REFINE-2-4 [FIXED — CT blocking 4：T2.3 用例 3 TimeoutExpired 未捕获 → 测试 ERROR]**：用例 3 子进程进入 `_main_loop` 后可能因缺 PM 依赖长时间运行，`subprocess.run(timeout=60)` 必抛 `subprocess.TimeoutExpired` → 测试 ERROR。已改为显式 `try/except subprocess.TimeoutExpired`，超时 → PASS（证据语义：未 exit 5/4 即证明锁已释放且脏树检查通过，在注释与断言消息中写明），未超时 → `returncode not in (4, 5)`；并注明用例 1/2 不得捕获 TimeoutExpired（超时=失败证据）✅
- **Issue REFINE-2-5 [FIXED — 调用点 19→22]**：重数 `_git`/`_git_at` 调用点：`_git` 19 个 + `_git_at` 直接调用 3 个（L3507/L3511/L7018）= **22**（`_git` 内部转发 `_git_at` 1 处 L6886 不计）。同时精确化 porcelain 调用点：4 处 `--porcelain`（L6890 worktree list 行首无 XY 列不受影响、L7437/L7645 真值语义不受影响、L7718 得到修复）。T1.0 修改内容与潜在风险两处「19 个调用点」同步修正 ✅
- **Issue REFINE-2-6 [FIXED — `_pid_is_live` 死代码 + `_git_toplevel` 关系注明]**：参考实现中 `self_ticks` 计算、`if start_ticks != self_ticks ...: pass` 死代码行、`_pid_start_ticks_match`、`_pid_is_self_start_match` 已从 T1.1 参考实现删除——`_pid_is_live` 简化为 kill(0) 单层（锁文件只记录 `pid:` 无 start-ticks 记录侧，比对恒真）。frontmatter T1.1 goal、修改文件清单表、D4、Error & Rescue Map 同步。新增注 3 说明 `_repo_lock_root_for(root)` 不复用既有 `_git_toplevel()`（L12950）的理由（无 root 参数 + 回退语义不同），并注明 `_is_git_repo_root`（L7702）直接复用 ✅
- **CAP-OK（REFINE-2 复检）**：`_repo_lock_root_for` 为 `_git_toplevel` 的参数化新包装（非重复实现）；删除 `_pid_start_ticks_match` 后函数组无孤儿引用；`_git_at`/`_is_git_repo_root` 均为既有函数复用 ✅

### REFINE-3 Issues（2026-09-03 CT 最终发现落实，冻结区边界收紧）

- **Issue REFINE-3-1 [FIXED — T2.1 TestRepoLockPidRecord 用例 1 直接 `_LoopLock(...).acquire()`]**：原用例 1 `test_acquire_overwrites_stale_pid` 直接 `_LoopLock(_repo_lock_path(root=tmp_path)).acquire()` 并断言覆盖式写入，绕过 `_acquire_repo_lock` 完整路径，违反「测试不得直接实例化 `_LoopLock`」冻结区边界；且其断言（获取后锁文件 == `pid:{os.getpid()}\n`）与 `TestAcquireRepoLock` 用例 1 断言 ③ 完全重复。处置：**删除该用例**（用例清单原位标注「已由 `TestAcquireRepoLock` 用例 1 覆盖」，不实现），T2.1 边界追加 REFINE-3 终态条款。✅
- **Issue REFINE-3-2 [FIXED — 用例 2/3/4 获取路径未显式声明]**：用例 2（`test_alive_unrelated_pid_does_not_block`）原文仅写「acquire 成功」未声明获取方式，存在直接 `_LoopLock(...).acquire()` 的误实现空间；用例 3「先持锁」、用例 4「acquire 不受影响」同样未声明。已逐用例明确：全部走完整 `_acquire_repo_lock` 路径（monkeypatch `orchestrator.ROOT`=tmp_path，预写 `_repo_lock_path()` 无参锁文件）。冻结区边界终态：**全计划直接使用 `_LoopLock` 的唯一允许点 = T2.3 用例 2 外部持锁者 holder**。✅
- **Issue REFINE-3-3 [FIXED — `/proc/<pid>/stat` 启动时间比对残留文字]**：REFINE-2 已将该比对作为死代码从 `_pid_is_live` 删除（REFINE-2-6），但 T1.1 潜在风险（原 L447）与 R6 缓解列（原 L688）仍残留「`/proc/<pid>/stat` 解析退化兜底」「启动时间比对加固文案」等已不存在机制的描述。已清理：T1.1 潜在风险删除该半句（保留 `tempfile`/`hashlib` import 风险），R6 缓解改为「flock 唯一权威 + pid 仅入诊断文案（`os.kill(pid,0)` 单层存活探测，不参与放行判定）」。D4/参考实现 docstring/注 2/R2-1/REFINE-2-6 等「已删除」性质的历史记录文字保留不动（属准确史实）。✅

### What-If Preview（R3-7）
- `_core.py:cmd_run` 修改 → 引用方：`main()`（L13811 调用，REFINE-1 实测修正，无需改动，异常链不变）[影响预览: _core.py:main() → cmd_run()]
- `_core.py:_LoopLock` 未改 → 引用方（`_acquire_run_lock`、`_knowledge_write_lock` L10970）零波及 ✅
- 新符号 `_acquire_repo_lock/_repo_lock_path` 无既有引用（新增）✅
- `file_bus.py`/`orchestrator.py` 门面改动 → 无其他消费者依赖旧 `__all__` 长度 ✅

### Red-Team Round（阶段 2.5）
- 委派 `critical-thinking` 两次失败（`Subagent depth limit reached (1)`）→ 按委派空返回防护降级为编排者自审 `[DELEGATION-EMPTY: critical-thinking，fallback self-review]`，三-lens 结果：
  - **Lens A（注入）**：pid 行来自磁盘 → 防御解析（≤64B、errors="replace"、try/except、只 print 不执行）✅ 已入 T1.1，hash 输入经 `resolve()` 归一（D8）✅
  - **Lens B（静默失败）**：`/tmp` 不可写 OSError 裸抛（B1，Medium）✅ 已入 T1.1 包装，部分获取泄漏（B7，Medium）✅ 已入 T1.2+T2.2，git rev-parse 超时回退（B3）✅，pid 文件损坏（B4）✅，unlink 竞态（B5）→ 设计规避 + 旧路径冻结不改 ✅
  - **Lens C（跨任务漂移）**：hash 双侧一致（C3，Medium）✅ 已入 T2.3，门面/所有权表同步（C1）✅ T1.3
  - **结论：可通过**（top-3 必须修正项 B1/B7/C3 已全部折入任务）

### Spec Artifact
- `[Spec Artifact: SKIPPED，trigger not met]`（修改 4 文件、1 核心模块、无外部 API/schema 破坏，未达触发条件）

### Schema Self-Validation
- `python -m agent_workflows.tools.validate_plan <path> --strict`：本仓无 `agent_workflows` 包（实测 import 失败）→ `[Schema: WARN，validator unavailable in this repo，frontmatter 按 v1.1 手写核对]`

## Pre-Delivery Audit（Gate D.3，L1-Lite，纯代码/流程计划）

| 检查项 | 结果 |
|--------|------|
| 安全：无仿真/核/辐射参数、无凭据写入、无破坏性命令 | ✅ |
| 范围：仅 4 个计划内文件，执行时动态核对的 pre-existing untracked 项；计划文件自身不纳入源码提交范围与 project_management/copilot-agents/.loop 明确排除 | ✅ |
| 可逆性：每 task 独立 commit + revert 路径 + 整体回滚说明 | ✅ |
| 事实性：全部锚点经 read/grep 实测（R1.5 零未验证项） | ✅ |
| 授权归因：本计划无「已获授权」类声明，PM #3155 状态回写标注为「建议经 pm-coordinator 委派」 | ✅ |

### Gate D.0（De-AI-Fier，L1-Tone）记录 — ⚠️ degradation notice

- 执行 3 轮 `deai_review_file(doc_type="plan", strict=false)` 反馈循环（协议上限）：
  - R1：blocking 11（分号 5 / 破折号 5 / TTR 1）→ 定向修正 9 处（goal 分号、contract_signature 破折号、边界破折号、「覆盖式」→「pid 重写」措辞）
  - R2：blocking 11 → 全局修正 128 处全角分号、17 处破折号、表格填充符
  - R3：blocking 1（仅 `lexical_diversity_low`，TTR=0.41，文档级指标）
- 剩余 1 条不修正的理由：该指标由文档结构主导（约四成内容为 YAML frontmatter 字段名、可执行 verify 命令如 `exit 0`、行号/符号锚点），此类内容按 R2.8「消除下游猜测」原则必须保持机器可读精确形式，改写将损害 TE 可执行性。
- 无 error/critical 级 finding；术语/单位类 finding 按 plan 文件 L1-Tone 范围豁免（`term_unrecognized` 均为 agent 名与锚点描述，`number_without_unit` 均为 YAML 版本号/行号/退出码）。

## Completion Summary

| 维度 | 结果 |
|------|------|
| 背景与目标 | 完整（问题/根因/目标/非目标/复用分析）+ 产出 1 Scope 澄清（REFINE-1） |
| 技术方案 | 完整（D1-D8 决策表 + 3 条假设标注） |
| Error & Rescue Map | 9 条路径，CRITICAL GAP 0 |
| 执行计划 | 3 Phase、8 Task（T1.0-T1.3/T2.1-T2.3/T3.1，T1.0 为 REFINE-1 新增） |
| Execution Wave | W1-W6，唯一串行点为同文件测试追加（已说明理由）；W1 含 T1.0+T1.1 同文件按序执行 |
| Post-Execution Verification | Automated 7（V1-V7）+ Probe 1（P1）+ Manual 2（M1-M2） |
| 风险/回滚矩阵 | 10 项（R1-R10）+ 整体回滚路径 + 回滚操作手册（REFINE-1） |
| 已知局限 | ① `agent_workflows` 校验器本仓不可用（手写核对），② Red-Team 降级自审，③ Gate D.0 经 3 轮修正后余 1 条文档级 TTR 指标（degradation notice 已记录），④ 调度器侧 3 次重试治理属 RESEARCH-PM 主防线（本计划仅加测试锁定 loop-kit 内语义），⑤ REFINE-1 发现 `_git_at` porcelain 剥离缺陷（已由 T1.0 修复，见 REFINE-1-5） |



