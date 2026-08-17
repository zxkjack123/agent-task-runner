# 修复计划：agent-task-runner daemon 空闲 crash-restart 循环

> **状态**: ✅ 已完成并归档（PM #2747，2026-08-17；执行日志见下方 Execution Log，合入为 9b51310）
> **Scope Mode**: HOLD（bug 修复，严格保持范围不扩不缩）
> **范围**: `src/loop_kit/_core.py` + `tests/test_orchestrator.py` + systemd user unit（git 外）
> **基线**: HEAD=c6d6e39，测试基线 2 failed / 604 passed（预存在，非本计划修复对象）

---

## 背景与目标

### 需求分解（CoT Stage 1）

```
REQUIREMENT: daemon（systemd user unit，ExecStart=`python -m loop_kit run` 无参形态）
  空闲时高频 crash-restart（NRestarts=1633+，每 ~30s 增长一次）
↓
CONSTRAINTS:
  - 不走 ATR（本任务修复对象即 ATR 依赖的 daemon，自我引用）
  - 不改变 daemon 对有效任务卡的处理语义（回归不破坏）
  - 与 #2622 会话并发：M .github/plans/pm2622-doc-pipeline.md + ?? traces/ 属于该会话，勿动
  - idle 检测必须置于 dirty check 之前（时序约束，否则只修无卡路径不生效）
  - 显式任务模式下 dirty check 仍 hard fail（语义保留）
↓
BOUNDARY (IN):
  - loop_kit daemon 形态 idle 判定前置（dirty check 之前，优雅 exit 0）
  - daemon 模式 dirty check 降级 warning（仅 daemon 模式）
  - systemd unit Restart=always → Restart=on-failure
  - 单元测试（idle exit 0 / 降级 warning / 显式模式回归）
BOUNDARY (OUT):
  - 不引入 sleep 轮询（方案 B，成本高，notes 已定调不选）
  - 不修改 _LoopLock 实现（现有 finally release 已覆盖 idle 路径）
  - 不修改 auto_dispatch 语义、不修改 .loop/tasks/ 拾取逻辑
  - 不动 #2622 会话的文件
↓
ACCEPTANCE (二元可验证):
  A1: daemon 无卡空闲时 NRestarts 在观察窗口内零增长（Probe 对比快照）
  A2: 无卡+脏树场景不再循环（journal 无 "Refusing to start" 新记录）
  A3: 显式任务模式（--task / task_ref）无卡仍 exit 1、脏树仍 exit 4（单测断言）
  A4: daemon 有卡+脏树时 warning 后继续执行（单测断言 _main_loop 被调用）
```

### 根因分析（已核实调用链）

| 退出路径 | 调用链（行号为 c6d6e39 实测） | 退出码 |
|---------|------------------------------|--------|
| (a) 无卡 | `main()` → `cmd_run` → `_run_multi_round_via_subprocess` → `_sync_task_card_to_bus`(_core.py:12046) → `_load_task_card`(:10125) → `_load_task_card_or_raise`(:8033) → `sys.exit(1)` | 1 |
| (b) 脏树 | `cmd_run`(:12398) `_enforce_clean_worktree_or_exit`(:8666) → `sys.exit(4)`；`_run_multi_round_via_subprocess`(:12021) 同样有 | 4 |

当前 `cmd_run` 顺序（:12388-12398）：`_sync_task_card` → `_enforce_clean_worktree_or_exit` → `_main_loop`。**(b) 在 (a) 之前执行**——只修无卡路径无法阻断脏树循环；且 idle 检测必须放在 `_enforce_clean_worktree_or_exit` 之前。

### 关键设计决策（CoT Stage 3 Trade-off）

**DECISION 1: daemon 模式判定 = 入口参数形态（无 task_ref 且无 --task）**

```
DECISION: daemon_mode = (args.task is None and args.task_ref is None)，main() 层计算，以 keyword-only 参数传给 cmd_run
ALTERNATIVES: (i) 比较 config.task_path 是否等于默认卡路径——被拒：显式传 .loop/task_card.json 路径的用户会误判；路径比较脆弱
              (ii) 环境变量 LOOP_DAEMON=1（systemd Environment 注入）——被拒：引入新配置契约，systemd unit 需同步改 Environment，侵入面更大
RATIONALE: 入口参数形态是 daemon 与显式模式的本质区别；ExecStart 固定无参，用户/ATR 显式调用必带 task 参数。判定逻辑单点、可单测
RISK: 若有第三方脚本无参调用 `loop_kit run` 且期望报错 → 行为变为 exit 0。缓解：概率极低且 exit 0 语义更合理；全量测试兜底
```

**DECISION 2: idle 精确条件 = daemon 模式 且 默认卡路径不存在**

```
DECISION: if daemon_mode and not Path(config.task_path).exists(): return（exit 0）
ALTERNATIVES: (i) 同时扫描 .loop/tasks/*.json 找可拾取任务——被拒：无参 daemon 只读默认卡路径（_resolve_task_path 仅在传 task_ref 时扫 tasks/），扩展拾取逻辑超出 HOLD 范围
              (ii) sys.exit(0) 显式退出——被拒：return 更干净，走 finally 释放锁后自然 exit 0
RATIONALE: 对齐 _load_task_card_or_raise 的 .exists() 判定口径；最小语义
RISK: 卡被误删时 daemon 静默 idle → 缓解：idle 消息打印 stdout（journal 可查）+ _log 事件
```

**DECISION 3: dirty 降级 = `warn_only` 关键字参数（默认 False）**

```
DECISION: _enforce_clean_worktree_or_exit(*, allow_dirty, warn_only=False)；cmd_run 传 warn_only=daemon_mode
          _run_multi_round_via_subprocess(:12021) 的调用保持不传（默认 False，语义不变）
ALTERNATIVES: (i) 复用 allow_dirty 语义——被拒：allow_dirty 是用户显式 flag，语义混淆；(ii) 新增独立函数——被拒：重复代码
RATIONALE: 默认参数向后兼容；现有测试（test_orchestrator.py:9536-9547）与 monkeypatch（:9719 `lambda allow_dirty: None`，其调用路径 _run_multi_round_via_subprocess 不传 warn_only）全部兼容
RISK: daemon 有卡+脏树时继续执行，任务提交可能包含非任务文件 → 缓解：worker commit scope 已有负向验证机制（AGENTS.md 规则 8），且仅 daemon 模式受影响
```

**DECISION 4: systemd Restart=always → on-failure，timer 不动**

```
DECISION: 只改 Restart 一行。RestartSec=30 保留（真实失败仍 30s 重试）。agent-task-runner.timer（每 5 分钟启动 service）保留——空闲时每次启动立即 idle exit 0，属于期望的轮询语义，NRestarts 不增长
RATIONALE: exit 0 在 on-failure 下不重启；exit 1/4/5（真实错误）仍会重启，错误信号不丢失
RISK: 无（回滚路径见风险节）
```

**DECISION 5: _LoopLock 零修改**

```
cmd_run 的 try/finally（:12431-12433）保证 idle return 时 lock.release()。idle 检测放在锁获取之后，保持互斥语义
```

### 假设枚举（CoT Stage 2）

1. `[假设: daemon_mode 判定基于 run 子命令参数，其他子命令（status/health 等）不受影响]` — 已核实 main() 各子命令分支独立；若错误，影响面仅 cmd_run 测试
2. `[假设: TE 执行环境可以 systemctl --user / journalctl --user（XDG_RUNTIME_DIR 正常）]` — 若不可用，Phase 2 命令记录待用户执行（计划含 fallback）
3. `[假设: 执行期 _core.py 行号未漂移（#2622 会话只改 .github/plans 与 traces，不动 _core.py）]` — 计划使用"符号名锚点 + 当前行号"双锚定，执行前 grep 符号名即可定位
4. `[假设: 观察窗口 90s 足够证明 NRestarts 零增长（原循环周期 30s）]` — 若需更严格，验收命令可延长窗口

---

## 修改方案

**修改路径分类**: Light（~30 行代码 + ~60 行测试 + 1 行 systemd）

**方案概述**:
1. `_core.py` 三处：
   - `_enforce_clean_worktree_or_exit`（:8666）签名加 `warn_only: bool = False`
   - `cmd_run`（:12365）签名加 `*, daemon_mode: bool = False`；try 块最前（:12387 之后、reset 分支之前）插入 idle 检测
   - `main()`（:13313）调用处计算并传入 `daemon_mode`
2. `tests/test_orchestrator.py` 追加 `TestDaemonIdle` 类（复用现有 `_configure_loop_paths`(:3841) / `_run_config`(:3868) helper）
3. `~/.config/systemd/user/agent-task-runner.service` 改 Restart 一行

**影响范围**: `src/loop_kit/_core.py`、`tests/test_orchestrator.py`、systemd unit（git 外）、`CHANGELOG.md`

---

## 执行计划

### Phase 0: 准备与冻结（阻断 daemon 加载半成品代码）

> ⚠️ **时序约束（必须最先执行）**：daemon 每 ~30s 重启一次并加载 `_core.py`。代码修改中途 daemon 可能加载半成品 → 崩溃行为不可预测。**先停 service 与 timer，再改代码。**

#### Task 0.1: 冻结 daemon 与 timer

- **目标**: 停止 crash 循环，隔离代码修改期
- **依赖**: 无
- **frontier**: 是
- **执行者**: Task Executor
- **修改内容**: 无文件修改（仅命令）
- **命令**:
  ```bash
  systemctl --user stop agent-task-runner.service
  systemctl --user stop agent-task-runner.timer
  systemctl --user show agent-task-runner.service -p ActiveState -p NRestarts   # 记录基线快照 S0（NRestarts 值）
  ```
- **修改边界**: 不删除 unit 文件，不 disable
- **验收标准**:
  - ✅ `ActiveState=inactive` 或 `failed`（stop 后）
  - ✅ 记录到 `NRestarts` 基线值（后续对比用）
- **潜在风险**: systemctl --user 不可用（无 XDG_RUNTIME_DIR）→ fallback: `loginctl enable-linger gw` 后重试；仍失败则记录 `⚠️ PENDING MANUAL: 请用户执行 stop 命令`
- **预留歧义标注**: 无歧义

### Phase 1: 代码修改（loop_kit）

#### Task 1.1: `_enforce_clean_worktree_or_exit` 增加 warn_only 降级参数

- **目标**: daemon 模式脏树降级为 warning，显式模式保持 hard fail
- **依赖**: T0.1
- **frontier**: 是
- **执行者**: Task Executor
- **修改内容**:
  - 文件 `src/loop_kit/_core.py`（repo-root-relative）:
    1. 函数签名（锚点: `def _enforce_clean_worktree_or_exit(*, allow_dirty: bool) -> None:`，当前行 8666）改为：
       ```python
       def _enforce_clean_worktree_or_exit(*, allow_dirty: bool, warn_only: bool = False) -> None:
       ```
    2. 函数体（锚点: `if allow_dirty:` 块之后、`print("Refusing to start. Re-run with --allow-dirty to bypass.", file=sys.stderr)` 之前，当前约 8675-8678 行之间）插入：
       ```python
           if warn_only:
               print("Warning: dirty git working tree detected (daemon mode); proceeding.", file=sys.stderr)
               return
       ```
    3. docstring/注释：函数上方如有注释块，补一行说明 `warn_only` 仅用于 daemon 空闲容忍场景
- **修改边界**: 不修改 `_dirty_tracked_paths`；不修改 :12021 的调用点（保持默认 False）；不触碰 `_run_multi_round_via_subprocess`
- **质量检查方式**:
  - `uv run python -m py_compile src/loop_kit/_core.py` exit 0
  - 检查项：`grep -n "def _enforce_clean_worktree_or_exit" src/loop_kit/_core.py` 确认签名
- **验收标准**:
  - ✅ 签名含 `warn_only: bool = False`
  - ✅ 现有 `TestEnforceCleanWorktree` 3 个测试通过（默认 False 行为不变）
- **潜在风险**: 插入位置错误导致 allow_dirty 分支被跳过 → 用现有测试兜底
- **预留歧义标注**: 无歧义

#### Task 1.2: `cmd_run` 增加 daemon_mode 参数 + idle 检测（dirty check 之前）

- **目标**: daemon 无卡空闲优雅 exit 0；idle 判定先于 dirty check；dirty 降级接线
- **依赖**: T1.1（warn_only 参数存在）
- **frontier**: 否（依赖 T1.1）
- **执行者**: Task Executor
- **修改内容**:
  - 文件 `src/loop_kit/_core.py`:
    1. `cmd_run` 签名（锚点 `def cmd_run(`，当前行 12365，结尾参数 `paths: LoopPaths | None = None,` 之后）追加 keyword-only 参数：
       ```python
       *,
       daemon_mode: bool = False,
       ```
    2. idle 检测插入（锚点: `try:` 之后（当前 12387 行）、`if reset and not single_round:` 之前（当前 12388 行））：
       ```python
           # Daemon idle: no task card and not an explicit task invocation →
           # exit cleanly BEFORE the dirty-worktree check so an idle daemon
           # never crash-loops on unrelated dirty files.
           if daemon_mode and not Path(config.task_path).exists():
               _log(f"Idle: no task card at {config.task_path}; exiting cleanly (daemon mode)")
               print(f"Idle: no task card found ({config.task_path}); exiting cleanly.", file=sys.stderr)
               return
       ```
       > 注：`Path` 已在 _core.py 顶部导入（已核实全文件大量使用 `Path(...)`）
    3. dirty check 调用（锚点 `_enforce_clean_worktree_or_exit(allow_dirty=config.allow_dirty)`，当前 12398 行）改为：
       ```python
               _enforce_clean_worktree_or_exit(allow_dirty=config.allow_dirty, warn_only=daemon_mode)
       ```
- **修改边界**: 不修改 `_LoopLock`、`_acquire_run_lock`、finally 释放逻辑；不修改 `single_round` 路径语义；不修改 `_run_multi_round_via_subprocess` 内 :12021 的调用
- **质量检查方式**:
  - `uv run python -m py_compile src/loop_kit/_core.py` exit 0
  - `uv run python -c "from loop_kit.orchestrator import cmd_run, _enforce_clean_worktree_or_exit"` exit 0
  - 检查项：grep 确认 idle 块位于 `if reset and not single_round:` 之前、`_enforce_clean_worktree_or_exit` 调用之前
- **验收标准**:
  - ✅ 签名含 `daemon_mode: bool = False`（keyword-only）
  - ✅ 三处修改位置符合上述锚点（顺序: idle 检测 → reset/sync → dirty check）
- **潜在风险**: idle 检测误放 dirty check 之后 → 时序约束违反。检查项 3 强制验证
- **预留歧义标注**: 无歧义

#### Task 1.3: `main()` 计算并传入 daemon_mode

- **目标**: CLI 层接线——无 task 参数时以 daemon 模式运行
- **依赖**: T1.2
- **frontier**: 否
- **执行者**: Task Executor
- **修改内容**:
  - 文件 `src/loop_kit/_core.py`:
    1. `main()` 的 run 分支（锚点: `raw_ref = args.task if args.task is not None else args.task_ref`，当前 13207 行附近）之后新增一行：
       ```python
           daemon_mode = raw_ref is None
       ```
    2. `cmd_run(` 调用（锚点当前 13313-13320 行）追加关键字参数：
       ```python
               daemon_mode=daemon_mode,
       ```
- **修改边界**: 不修改 `_cfg_val`、`RunConfig` 构造、`_validate_run_config`；RunConfig 不新增字段
- **质量检查方式**:
  - `uv run python -m py_compile src/loop_kit/_core.py` exit 0
  - 检查项：grep 确认 `daemon_mode=daemon_mode` 出现在 main 的 cmd_run 调用中
- **验收标准**:
  - ✅ `raw_ref is None` 为唯一判定条件（不比较路径值）
- **潜在风险**: 误把 daemon_mode 传入其他子命令分支 → grep 复核
- **预留歧义标注**: 无歧义

### Phase 2: 单元测试

#### Task 2.1: 追加 TestDaemonIdle 测试类

- **目标**: 覆盖 idle exit 0、时序优先、dirty 降级、显式模式回归
- **依赖**: T1.3
- **frontier**: 否
- **执行者**: Task Executor
- **修改内容**:
  - 文件 `tests/test_orchestrator.py`（在文件末尾追加，复用现有 `_configure_loop_paths`(:3841) 与 `_run_config`(:3868)）：
    ```python
    class TestDaemonIdle:
        """PM #2747: daemon idle crash-restart fix."""

        def test_daemon_idle_no_card_exits_cleanly(self, tmp_path: Path, monkeypatch, capsys) -> None:
            _configure_loop_paths(monkeypatch, tmp_path)
            card = tmp_path / ".loop" / "task_card.json"
            assert not card.exists()
            orchestrator.cmd_run(
                _run_config(str(card)),
                single_round=False,
                round_num=None,
                daemon_mode=True,
            )  # must return normally, no SystemExit
            captured = capsys.readouterr()
            assert "Idle: no task card" in captured.err

        def test_daemon_idle_precedes_dirty_check(self, tmp_path: Path, monkeypatch) -> None:
            _configure_loop_paths(monkeypatch, tmp_path)
            card = tmp_path / ".loop" / "task_card.json"
            monkeypatch.setattr(orchestrator, "_dirty_tracked_paths", lambda: ["src/foo.py"])
            # idle 检测在 dirty check 之前 → 脏树不应触发 exit 4
            orchestrator.cmd_run(
                _run_config(str(card)),
                single_round=False,
                round_num=None,
                daemon_mode=True,
            )

        def test_daemon_with_card_dirty_tree_warns_and_proceeds(self, tmp_path: Path, monkeypatch, capsys) -> None:
            _configure_loop_paths(monkeypatch, tmp_path)
            card = tmp_path / ".loop" / "task_card.json"
            card.write_text(json.dumps({"task_id": "T-1", "goal": "g"}), encoding="utf-8")
            monkeypatch.setattr(orchestrator, "_dirty_tracked_paths", lambda: ["src/foo.py"])
            called: dict[str, object] = {}
            monkeypatch.setattr(
                orchestrator,
                "_main_loop",
                lambda **kwargs: called.update(kwargs),
            )
            orchestrator.cmd_run(
                _run_config(str(card)),
                single_round=False,
                round_num=None,
                daemon_mode=True,
            )
            assert "config" in called
            captured = capsys.readouterr()
            assert "proceeding" in captured.err.lower()

        def test_explicit_mode_missing_card_still_exits_1(self, tmp_path: Path, monkeypatch) -> None:
            _configure_loop_paths(monkeypatch, tmp_path)
            card = tmp_path / "missing.json"
            monkeypatch.setattr(orchestrator, "_dirty_tracked_paths", lambda: [])
            with pytest.raises(SystemExit) as exc:
                orchestrator.cmd_run(
                    _run_config(str(card)),
                    single_round=False,
                    round_num=None,
                    daemon_mode=False,
                )
            assert exc.value.code == orchestrator.EXIT_GENERAL_ERROR

        def test_explicit_mode_dirty_tree_still_exits_4(self, tmp_path: Path, monkeypatch) -> None:
            _configure_loop_paths(monkeypatch, tmp_path)
            card = tmp_path / ".loop" / "task_card.json"
            card.write_text(json.dumps({"task_id": "T-1", "goal": "g"}), encoding="utf-8")
            monkeypatch.setattr(orchestrator, "_dirty_tracked_paths", lambda: ["src/foo.py"])
            with pytest.raises(SystemExit) as exc:
                orchestrator.cmd_run(
                    _run_config(str(card)),
                    single_round=False,
                    round_num=None,
                    daemon_mode=False,
                )
            assert exc.value.code == orchestrator.EXIT_DIRTY_WORKTREE

        def test_enforce_clean_worktree_warn_only(self, monkeypatch, capsys) -> None:
            monkeypatch.setattr(orchestrator, "_dirty_tracked_paths", lambda: ["src/foo.py"])
            orchestrator._enforce_clean_worktree_or_exit(allow_dirty=False, warn_only=True)
            captured = capsys.readouterr()
            assert "proceeding" in captured.err.lower()
    ```
- **修改边界**: 不修改现有测试类与 helper；不新增 conftest；测试写入 tmp_path 内，不触碰仓库真实 .loop
- **质量检查方式**:
  - `uv run --group dev pytest tests/test_orchestrator.py::TestDaemonIdle -q` 全部通过
  - 检查项：确认测试类名与用例名与计划一致
- **验收标准**:
  - ✅ 6 个用例全绿（对应验收条件 A1-A4）
- **潜在风险**:
  - `test_daemon_idle_no_card_exits_cleanly` 依赖 cmd_run 内 lock 获取成功（tmp_path 独立锁路径，无冲突）
  - `_log` 在无 logs 目录时是否安全 → `_configure_loop_paths` 已建 logs 目录（已核实 helper 内容）
  - 若 `Path`/`json` 未在 test_orchestrator.py 顶部导入 → 已核实第 1-14 行已导入 `json`、`from pathlib import Path`、`pytest` ✓
- **预留歧义标注**: 无歧义

### Phase 3: systemd unit 调整与部署

#### Task 3.1: unit 备份 + Restart 修改 + 重载部署

- **目标**: exit 0 不再触发重启；保留真实失败重试
- **依赖**: T2.1（测试全绿后才动 systemd）
- **frontier**: 否
- **执行者**: Task Executor
- **修改内容**:
  - 文件 `~/.config/systemd/user/agent-task-runner.service`（git 外）：
    1. 备份：
       ```bash
       mkdir -p /home/gw/opt/agent-task-runner/.github/plans/backup
       cp ~/.config/systemd/user/agent-task-runner.service /home/gw/opt/agent-task-runner/.github/plans/backup/agent-task-runner.service.orig-2026-08-17
       ```
    2. 修改唯一一行：`Restart=always` → `Restart=on-failure`（sed 或 edit 工具；文件其余内容一字不改）
    3. 部署：
       ```bash
       systemctl --user daemon-reload
       systemctl --user start agent-task-runner.service
       systemctl --user start agent-task-runner.timer
       ```
- **修改边界**: 不修改 ExecStart / Environment / RestartSec / WorkingDirectory；不改 timer 文件
- **质量检查方式**:
  - 检查项 1：`diff ~/.config/systemd/user/agent-task-runner.service /home/gw/opt/agent-task-runner/.github/plans/backup/agent-task-runner.service.orig-2026-08-17` 输出仅一行差异且为 `Restart=`
  - 检查项 2：`systemctl --user cat agent-task-runner.service | grep Restart` 输出 `Restart=on-failure`
- **验收标准**:
  - ✅ 备份文件存在且 diff 仅一行
  - ✅ daemon-reload exit 0，service 与 timer 启动成功
- **潜在风险**: systemctl --user 不可用 → fallback 记录 `⚠️ PENDING MANUAL: 请用户执行上述命令`
- **预留歧义标注**: 无歧义

#### Task 3.2: 运行验证（观察窗口 + journal 核对）

- **目标**: 证实 crash-restart 循环终止（验收条件 A1/A2）
- **依赖**: T3.1
- **frontier**: 否
- **执行者**: Task Executor
- **修改内容**: 无文件修改（观察验证）
- **命令**:
  ```bash
  # 启动后立即快照
  systemctl --user show agent-task-runner.service -p NRestarts -p ActiveState -p ExecMainStatus
  sleep 90
  # 观察窗口后快照：NRestarts 应不增长（原循环周期 30s，90s 窗口覆盖 3 个原循环周期）
  systemctl --user show agent-task-runner.service -p NRestarts -p ActiveState -p ExecMainStatus
  # 无新错误退出痕迹
  journalctl --user -u agent-task-runner.service --since "-3min" | grep -cE "task card not found|Refusing to start" || true
  ```
- **修改边界**: 不新增/删除 .loop/task_card.json（观察期保持无卡状态）
- **验收标准**:
  - ✅ 90s 窗口内 NRestarts 零增长（相对启动后首快照）
  - ✅ journal grep 计数 = 0（无 "task card not found" / "Refusing to start"）
  - ✅ journal 可见 "Idle: no task card" 记录（证明 idle 路径生效）
- **潜在风险**: timer 每 5 分钟拉起 service 属于正常轮询（ActiveState 会周期性 active/inactive 摆动），**NRestarts 不增长即通过**——不要误判 timer 拉起为重启
- **预留歧义标注**: 无歧义

### Phase 4: 全量回归与收尾

#### Task 4.1: 全量测试回归

- **目标**: 确认无回归（基线 2 失败保持，其余全绿）
- **依赖**: T2.1（可与 T3.x 并行，互不冲突）
- **frontier**: 是（与 T3.1/T3.2 并行，测试与 systemd 文件域不重叠）
- **执行者**: Task Executor
- **修改内容**: 无文件修改
- **命令**:
  ```bash
  uv run --group dev pytest -m "not e2e" -q
  ```
- **验收标准**:
  - ✅ 结果 = `2 failed, 604+6 passed`（2 failed 必须恰为基线同名用例：`test_shows_context_file_stats`、`test_task_card_in_resettable_files`；新增 TestDaemonIdle 6 用例全过）
  - ✅ 失败数未从 2 增长
- **潜在风险**: 若出现新失败 → 回查变更 diff，修复或回滚
- **预留歧义标注**: 无歧义

#### Task 4.2: commit + changelog + PM 回写

- **目标**: 提交修复并记录
- **依赖**: T4.1、T3.2
- **frontier**: 否
- **执行者**: Task Executor
- **修改内容**:
  - `CHANGELOG.md`（repo-root）：追加条目（风格对齐现有条目，如 "fix(loop): daemon idle clean exit + dirty warn_only in daemon mode (PM #2747)"）
  - commit 范围**仅限**：`src/loop_kit/_core.py`、`tests/test_orchestrator.py`、`CHANGELOG.md`（commit 前 `git diff --stat` 负向验证，禁止夹带 #2622 的 M .github/plans/pm2622-doc-pipeline.md 或 traces/）
  - PM 回写：委派 `pm-coordinator` 子代理更新 #2747（status→review 或按实际结果）
- **修改边界**: 不 commit 计划文件与备份文件（均 untracked/非本次范围）
- **验收标准**:
  - ✅ commit message 含 `PM #2747` 且仅含 3 个文件
  - ✅ PM #2747 notes 追加执行结果摘要
- **潜在风险**: commit 夹带 → `git status --short` 与 `git diff --stat` 双重核对
- **预留歧义标注**: 无歧义

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | Frontier | 依赖已完成 |
|------|------------|----------|------------|
| W1 | T0.1 | T0.1 | — |
| W2 | T1.1 | T1.1 | W1 |
| W3 | T1.2 | T1.2 | T1.1 |
| W4 | T1.3 | T1.3 | T1.2 |
| W5 | T2.1 | T2.1 | T1.3 |
| W6 | T3.1, T4.1 | T3.1, T4.1（并行：文件域不重叠） | T2.1 |
| W7 | T3.2 | T3.2 | T3.1 |
| W8 | T4.2 | T4.2 | T4.1 + T3.2 |

依赖链理由（CoT Stage 4）: T0.1 阻断 daemon 是代码安全前提；T1.1→T1.2→T1.3 同文件三处修改串行避免编辑冲突；T2.1 需全部代码就位；T3.1 必须等测试绿（systemd 变更不可回退于测试失败之前）；T4.1 与 T3.x 文件域不重叠故并行；T4.2 汇总所有结果最后执行。各 task 失败回滚策略见风险节 R1-R3。

## Post-Execution Verification

### Automated Verification（Task Executor 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | 全量测试（非 e2e） | `uv run --group dev pytest -m "not e2e" -q` | 2 failed（恰为基线 2 个）+ 610 passed |
| V2 | 语法编译 | `uv run python -m py_compile src/loop_kit/_core.py` | exit 0 |
| V3 | 导入冒烟 | `uv run python -c "from loop_kit.orchestrator import *"` | exit 0 |

### Deferred (needs restart / deployment)

- [ ] D1: 已在 T3.1 中执行 `systemctl --user daemon-reload` + start（本计划自身含部署步骤，D1 视为已满足）

### Probe (best-effort, run if available)

- [ ] P1: `systemctl --user show agent-task-runner.service -p NRestarts` — 启动后 90s 窗口零增长（T3.2 执行）
- [ ] P2: `journalctl --user -u agent-task-runner.service --since "-3min" | grep -cE "task card not found|Refusing to start"` — 计数 0（T3.2 执行）
- [ ] P3: journal 可见 "Idle: no task card" 记录（T3.2 执行）

### Manual（真正需要人工判断）

- [ ] M1: 长期观察（可选，非阻塞）——下个工作日确认 NRestarts 未继续增长；#2622 会话结束、脏树清除后确认 daemon 行为仍正确

## 风险与回滚

| # | 风险 | 缓解 | 回滚 |
|---|------|------|------|
| R1 | 代码修改引入回归 | V1 全量测试 + 基线对照 | `git revert <commit>`（仅 3 文件 commit，干净可逆） |
| R2 | systemd unit 改动直接生效（git 外） | T3.1 先备份 + diff 单行核对 | `cp .github/plans/backup/agent-task-runner.service.orig-2026-08-17 ~/.config/systemd/user/agent-task-runner.service && systemctl --user daemon-reload && systemctl --user restart agent-task-runner.service` |
| R3 | systemctl/journalctl 不可用（环境） | T0.1/T3.1/T3.2 均有 fallback 记录 | 用户手动执行记录的命令 |
| R4 | daemon 有卡+脏树时继续执行，任务提交可能含非任务文件 | worker commit scope 负向验证（AGENTS.md 规则 8）已存在；显式模式语义不变 | 无（接受风险，notes 已定调） |
| R5 | #2622 会话文件被误动 | 所有 task 修改边界显式排除 M .github/plans/pm2622-doc-pipeline.md + traces/；commit 前 git diff --stat 核对 | git 恢复 |
| R6 | 计划文件/备份文件（untracked）影响 daemon dirty 检测 | `_dirty_tracked_paths` 仅统计 tracked 修改（?? 忽略）——已核实无影响 | 无 |

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性（任务字段、依赖链、Wave 表） | 2（缺失基线测试说明；缺 Phase 0 冻结时序） | 2 | 0 |
| R1.5 | 外部引用事实核查（行号 8666/12021/12365/12387/12398/13207/13313、unit 路径、测试命令、退出码常量、9719 lambda 兼容性、facade 命名空间） | 1（初稿误将 idle 放 _run_multi_round_via_subprocess 层） | 1 | 0 |
| R2 | 可执行性（锚点唯一性、命令可跑、导入依赖） | 1（测试文件 import 需核实 Path/json/pytest——已核实均有） | 1 | 0 |
| R2.8 | LLM 可执行性（逐字段消歧：插入位置锚点代码、命令原文、验收二元化） | 0 | 0 | 0 |
| R3 | 风险与边缘（#2622 并发、timer 误判、观察窗口、系统级 fallback） | 2（timer 拉起误判为重启；TE 环境 systemctl 可用性未假设） | 2 | 0 |
| **终止** | **[T2 — 全部审查轮 issue 清零]** | | | **0** |

---

**附: systemd unit 原始内容（回滚参考）**

```ini
[Unit]
Description=Agent Task Runner — PM-driven review loop (auto-execute)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/gw/opt/agent-task-runner
ExecStart=/home/gw/opt/agent-task-runner/.venv/bin/python -m loop_kit run
Environment=PM_DB_PATH=/home/gw/opt/project_management/data/pm.sqlite
Environment=HOME=%h
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

→ handoff: task-executor


## CT 审阅合入（2026-08-17，critical-thinking 裁定，执行前必须满足）

### 🔴 1. 新增 T1.4：14 处 fake_cmd_run 签名加参
main() 传 `daemon_mode=` 后，tests 中 14 处 fake_cmd_run monkeypatch（行 495/3632/3675/3699/3730/3765/3813/10011/10042/10070/10162/10194/10292/10320）签名不含该参数且无 **kwargs → 全部 TypeError → ~14 个新失败，D6 必炸。
改法：T1.4 机械加参 `daemon_mode: bool = False`（14 行），无断言变更。

### 🔴 2. R4 风险向量重写 + 执行前置检查
真实向量：lane merge 冲突 fail_fast → `_restore_merge_head_after_failure`(:7314) 在主仓工作树执行 `git reset --hard base_sha`（:7315）→ 可无痕抹掉 #2622 会话的未提交 M 文件（不可恢复）。
改法：(a) 重写 R4 引用 :7315 向量；(b) 执行前置检查：`_dirty_tracked_paths()` ∩ 任务修改范围 = ∅ 才放行 daemon 脏树执行；(c) 备选（交用户定夺）：daemon 脏树改 exit 0 不执行。

### 🟡 Cautions（执行时落实）
1. idle 条件加 `and not single_round`（防止 --single-round 无 task 误 idle）
2. `test_daemon_idle_precedes_dirty_check` 必须 spy 断言 `_dirty_tracked_paths` 未被调用（原版零断言，测试名不副实）
3. T3.2 journal 窗口以 daemon-reload 时刻为锚（勿用相对 -3min，避免计入停服前旧记录）
4. 任务拾取延迟从"崩溃循环 30s"变为"timer 5 min"——行为变化需在验收记录中书面化（RestartSec=30 保留，exit 1 仍 30s 自愈）
5. T4.1 前跑一次即时全量快照作基线（#2622 会话仍活跃，基线可能漂移）；基线断言 = 恰 2 个基线同名失败 + 14 个 fake 修复后不新增

### 执行窗口注意
E3：T0.1 停 daemon 期间 #2622 若投递新卡会被冻结至 T3.1——计划已接受此窗口。

## Execution Log

### [2026-08-17 12:10 UTC] Plan execution — COMPLETED (with concurrency deviation)

- **Status**: ✅ COMPLETED（全部 task 完成；T4.2 commit 因并发被代提交，见偏差）
- **Task 0.1**: ✅ daemon+timer 已停；基线快照 S0: NRestarts=1717, ExecMainStatus=4（脏树循环确认）
- **Task 1.1**: ✅ `_enforce_clean_worktree_or_exit` 增 `warn_only: bool = False` + `task_scope: Iterable[str] = ()`；warn_only 分支含 scope-overlap 拒行（CT 🔴2 落实）
- **Task 1.2**: ✅ `cmd_run` 增 keyword-only `daemon_mode`；idle 检测置于 dirty check 之前且含 `not single_round`（CT 🟡1）；dirty check 传 `warn_only=daemon_mode`
- **Task 1.3**: ✅ `main()` 计算 `daemon_mode = raw_ref is None` 并传入
- **Task 1.4**（CT 🔴1）: ✅ tests 中 14 处 fake_cmd_run 签名加 `daemon_mode: bool = False`
- **Task 2.1**: ✅ TestDaemonIdle 8 用例（含 CT 🟡2 spy 断言 + CT 🔴2 overlap 拒行 2 用例）全绿
- **Task 3.1**: ✅ unit 备份 `.github/plans/backup/agent-task-runner.service.orig-2026-08-17`；diff 仅 1 行 `Restart=always→on-failure`；daemon-reload+start OK
- **Task 3.2**: ✅ 90s 观察窗口（锚定 11:58:33 启动时刻）NRestarts 零增长；P2 窗口内错误记录 0；P3 "Idle: no task card" 记录 2 条
- **Task 4.1**: ✅ verify worktree（HEAD 7b8ff54 + 仅我的 patch）全量 = 2 failed（基线同名）+ 612 passed
- **Task 4.2**: ⚠️ DEVIATION — #2622 会话在我执行 verify 期间（12:09:09）commit 了 9b51310，把我的 3 文件 staged 修改代提交（message 为 #2622 的）。`git show 9b51310` 核对内容完整。无独立 PM #2747 commit。PM #2747 已回写（status=review, progress=95）

### 并发偏差记录

```json
{
  "error_id": "err-20260817-1210-concurrency-commit",
  "error_type": "env_error",
  "summary": "#2622 会话并发 git add+commit 将本计划的 staged 修改代提交为 9b51310（message 非 PM #2747）",
  "root_cause_guess": "#2622 opencode 会话与 TE 同工作区并发操作 git index；TE 选择性暂存后 #2622 执行 commit 时把 index 全部提交",
  "confidence": "HIGH",
  "retry_suggestion": "无需重试——内容已核对完整落入 HEAD；仅 commit message 归属偏差，已记录于 PM #2747 notes",
  "affected_files": ["src/loop_kit/_core.py", "tests/test_orchestrator.py", "CHANGELOG.md"],
  "blocked_downstream": [],
  "task_id": "T4.2",
  "attempted_fixes": ["git show 9b51310 内容核对（daemon_mode/warn_only/14 fake/TestDaemonIdle/CHANGELOG 全在）"],
  "timestamp": "2026-08-17T12:10:37Z"
}
```

### Post-Execution Verification 结果

| ID | Description | Result |
|----|-------------|--------|
| V1 | 全量测试（verify worktree 纯环境） | ✅ PASS — 2 failed（基线同名）+ 612 passed |
| V2 | py_compile | ✅ PASS — exit 0 |
| V3 | import 冒烟 | ✅ PASS — exit 0 |
| D1 | daemon-reload + start | ✅ 已执行（T3.1） |
| P1 | NRestarts 90s 零增长 | ✅ PASS — 1717→1717（观察后 systemd 计数器重置为 0，无新增重启） |
| P2 | journal 窗口错误记录 0 | ✅ PASS — 窗口内 grep 计数 0 |
| P3 | "Idle: no task card" 可见 | ✅ PASS — 2 条 |
| M1 | 长期观察 | ⚠️ PENDING MANUAL — 下个工作日确认；#2622 脏树清除后复核 |
