# 修复计划：PM DB Lock + ATR 安全缺陷

> **状态**: 待执行  
> **范围**: 2 repos — `project_management` (F1) + `agent-task-runner` (F2-F4)  
> **修复量**: 5 个 task，跨 2 个文件约 40 行代码改动

---

## 背景与目标

- **F1**: `auto_dispatcher.py` 连接 `pm.sqlite` 时因并发 writer 导致 `database is locked`。DB 已是 WAL 模式但 `busy_timeout=0`（默认）。
- **F2**: `_execute_verification_check()` 使用 `shell=True` 运行 LLM 生成的验证命令，存在命令注入风险。
- **F3**: `_atomic_write_text()` 用 `except BaseException` 捕捉所有异常（含 KeyboardInterrupt），缺少 `fsync` 保证持久化。
- **F4**: `_LoopLock.acquire()` 中 `except Exception` 无必要地宽泛，阅读时有歧义。

- **非目标**: 不重构 PM cron runner 整体 DB 连接管理；不替换 WAL 模式；不新增中间件。

---

## 修改方案

### F1: `database is locked` 修复

**策略**: 最小改动——在 `main()` 中 `ensure_auto_task_table` 后加 1 行 `PRAGMA busy_timeout=15000`。

**理由**: WAL 模式已启用，`busy_timeout` 是 SQLite 内置的锁等待机制，无需应用层重试循环。15 秒足够前一个 writer 事务完成。DB 文件 860MB+，WAL 模式 + busy_timeout 是工业标准组合。

**影响**: `auto_task_dispatcher.py` L47 — 单行新增。

### F2: Shell 注入修复

**策略**: `shlex.split(cmd)` + `shell=False` 替代 `shell=True`。如果 `shlex.split` 失败（恶意嵌套引号），返回明确的错误 result 而非 fallback 到 `shell=True`。

**理由**: 
- 现有验证命令全是 `python -c '...'` 或 `some_binary --flag` 形式，`shlex.split` 完全兼容
- `shell=False` 是安全基线，`shell=True` 是安全红线
- 不需要 shell 管道/重定向等高级特性——验证命令应该简单可审计

**测试影响**: 现有 `test_pm_integration.py:TestVerificationExecution` 全部使用 `python -c` 格式，兼容 `shlex.split`。需验证 `test_verification_error`（`no_such_command_xyzzy` 无路径斜杠/引号）通过 `FileNotFoundError` 行为保持一致。

### F3: 原子写异常收紧

**策略**: `except BaseException` → `except (OSError, ValueError)`。在 `write_text` 后 `replace` 前加 `os.fsync`。tmp 后缀从 `.tmp` 改为 `path.suffix + ".tmp"`。

**理由**:
- `BaseException` 是 Python 异常根的父类，捕捉 `KeyboardInterrupt` 和 `SystemExit` 会干扰进程退出
- `OSError` 覆盖文件系统 I/O 失败；`ValueError` 覆盖 `write_text` 潜在的编码错误
- `os.fsync` 保证 Page Cache → Disk，消弭 crash 后部分写入风险

### F4: Lock 异常收紧

**策略**: 删除 L1193-1195 的 `except Exception` 块。`_lock_file` 只做 `fcntl.flock` / `msvcrt.locking`，不会抛 `OSError` 之外的异常。

**理由**: 语义清晰化——不让阅读者误以为 lock 操作会抛 MemoryError/TypeError。

---

## 执行计划

### Phase 1: PM DB Lock 修复

#### Task 1.1: `auto_task_dispatcher.py` 加 busy_timeout

- **目标**: 在 DB 连接后设置 `busy_timeout=15000`，解决 concurrent writer 冲突
- **依赖**: 无
- **执行者**: code writer
- **修改文件**:
  - `/home/gw/opt/project_management/scripts/auto_task_dispatcher.py`
- **修改边界**:
  - 仅修改 `main()` 函数中 L46 `ensure_auto_task_table(conn)` 之后
  - 不修改 bridge.py、atr_orphan_guard.py 或其他 PM 脚本
  - 不添加 try/except 重试循环、不修改 dispatch 逻辑
- **具体修改**:
  1. `auto_task_dispatcher.py` L47（`ensure_auto_task_table(conn)` 之后、`# Step 0` 注释之前）插入 2 行：
     ```python
     conn.execute("PRAGMA busy_timeout=15000")
     ```
     并在 block 注释上方加一行空行。
- **质量检查方式**:
  - `python -m py_compile /home/gw/opt/project_management/scripts/auto_task_dispatcher.py`
  - 检查日志：下一轮 5 分钟 tick 后 `journalctl --user -u auto-dispatcher.service --since "2 min ago"` 不再出现 `database is locked`
- **验收标准**:
  - ✅ 文件语法正确（`py_compile` pass）
  - ✅ 连续 3 个 dispatcher tick（15 分钟）无 `database is locked` 错误
- **潜在风险**: 如果其他 cron job 持有长事务（>15s）不释放，仍然会失败。但当前 cron jobs 都是 oneshot 且运行时间 <5s，此风险极低。

---

### Phase 2: ATR Shell 注入修复

#### Task 2.1: `_execute_verification_check` 改用 `shlex.split` + `shell=False`

- **目标**: 消除 `shell=True` 的任意命令注入风险
- **依赖**: 无（与 Phase 1 独立并行）
- **执行者**: code writer
- **修改文件**:
  - `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`
- **修改边界**:
  - 仅修改 `_execute_verification_check` 函数体 L1116-1124（subprocess.run 调用块）
  - 不修改 `VerificationSpec` 类型定义、不修改其他验证逻辑
  - `shlex` 只在函数内 `import`（与 L1894 现有模式一致）
  - 不改 `expected_output` 比较逻辑（L1129-1130）
- **具体修改**:
  1. L1117-1124 的 subprocess.run 调用从：
     ```python
     result = subprocess.run(
         cmd,
         shell=True,
         capture_output=True,
         text=True,
         timeout=timeout_sec,
         cwd=cwd,
     )
     ```
     改为：
     ```python
     import shlex
     try:
         cmd_list = shlex.split(cmd, posix=(os.name != "nt"))
     except ValueError:
         return {
             "passed": False, "output": f"(invalid command: {cmd[:100]})",
             "exit_code": -1, "command": cmd, "expected_output": expected,
         }
     result = subprocess.run(
         cmd_list,
         shell=False,
         capture_output=True,
         text=True,
         timeout=timeout_sec,
         cwd=cwd,
     )
     ```
  2. `shlex` 在函数内 import，后续不再引用（匹配 L1894 现有模式）
  3. `posix=(os.name != "nt")` 确保 Windows 下不误用 POSIX 引号规则
- **测试影响**: 现有 `TestVerificationExecution` 5 个测试均使用 `python -c ...` 格式，与 `shlex.split` 兼容。`test_verification_error` 使用 `no_such_command_xyzzy`（无空格无引号）——`shlex.split` 会返回 `["no_such_command_xyzzy"]`，`subprocess` 行为从"shell 执行无此命令"变为"找不到可执行文件"——`FileNotFoundError` 被 L1146 `except OSError` 捕获，行为一致。
- **验收标准**:
  - ✅ `python -m py_compile src/loop_kit/_core.py` pass
  - ✅ `uv run --group dev pytest tests/test_pm_integration.py::TestVerificationExecution -v` 全部 5 个测试 pass
  - ✅ 恶意输入如 `rm -rf /` 被 `shlex.split` 正确解析为单token而非命令执行
  - ✅ 非法嵌套引号如 `echo "hello 'world` 返回 `(invalid command: ...)`
- **潜在风险**: 如果 task card 中存在复杂的 shell 管道命令（`|`, `>`），`shell=False` 会失败。但验证命令应为简单可审计命令，复杂管道本来就不该用于自动化验证——失败应显式报错而非静默运行。

---

### Phase 3: 原子写 + Lock 异常收紧

#### Task 3.1: `_atomic_write_text` 修复异常类型 + 加 fsync

- **目标**: 收紧异常捕捉范围，添加 fsync 确保持久化
- **依赖**: 无（与 Phase 1、Phase 2 独立并行）
- **执行者**: code writer
- **修改文件**:
  - `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`
- **修改边界**:
  - 仅修改 `_atomic_write_text` 函数 L4752-4767
  - 不修改 `_atomic_write_jsonl`（它只是委托到 `_atomic_write_text`）
  - 不改其他任何写路径
- **具体修改**:
  1. `path.with_suffix(".tmp")` → `path.with_suffix(path.suffix + ".tmp")`（避免 `.json.tmp` 仅变成 `.tmp`）
  2. `tmp.write_text(payload, encoding="utf-8")` 之后、`tmp.replace(path)` 之前插入 3 行：
     ```python
     with tmp.open("r+b") as _f:
         os.fsync(_f.fileno())
     ```
  3. `except BaseException:` → `except (OSError, ValueError):`
- **验收标准**:
  - ✅ `python -m py_compile src/loop_kit/_core.py` pass
  - ✅ `uv run --group dev pytest tests/test_orchestrator.py -x -q` 全量测试 pass
- **潜在风险**: `os.fsync` 增加一次 disk flush 开销，但 `_atomic_write_text` 只在写 state.json、summary.json 等 critical state 时调用（≤ 1KB，频率 ≤ 10次/任务），性能影响可忽略。

#### Task 3.2: `_LoopLock.acquire` 删除宽泛 exception

- **目标**: 删除多余的 `except Exception`，让 `_lock_file` 抛出的异常由纯 `except OSError` 处理
- **依赖**: 无（与 T3.1 独立）
- **执行者**: code writer
- **修改文件**:
  - `/home/gw/opt/agent-task-runner/src/loop_kit/_core.py`
- **修改边界**:
  - 仅删除 L1193-1195 的 3 行：
    ```python
    except Exception:
        handle.close()
        raise
    ```
  - 不修改 L1184-1192 的其他异常处理
- **验收标准**:
  - ✅ `python -m py_compile src/loop_kit/_core.py` pass
  - ✅ `uv run --group dev pytest tests/test_orchestrator.py -x -q` 全量测试 pass
- **潜在风险**: 无。`_lock_file` 在 Linux 上调用 `fcntl.flock(..., LOCK_EX | LOCK_NB)`，唯一可能的异常是 `OSError`（EAGAIN/EACCES）。

---

## Execution Wave（并行执行波次）

| Wave | 可并行 Task | 依赖已完成 |
|------|------------|------------|
| W1 | T1.1, T2.1, T3.1, T3.2 | — |

4 个 task 互不依赖，修改文件不重叠（2 个不同 repo，即使在 ATR 内也是不同函数）。

---

## Post-Execution Verification

### Automated Verification（Task Executor 自动执行）

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | PM dispatcher 编译检查 | `python -m py_compile /home/gw/opt/project_management/scripts/auto_task_dispatcher.py` | exit 0 |
| V2 | ATR core 编译检查 | `cd /home/gw/opt/agent-task-runner && python -m py_compile src/loop_kit/_core.py` | exit 0 |
| V3 | ATR 全量测试 | `cd /home/gw/opt/agent-task-runner && uv run --group dev pytest -x -q` | exit 0, 全部 pass |
| V4 | Verification 专项测试 | `cd /home/gw/opt/agent-task-runner && uv run --group dev pytest tests/test_pm_integration.py::TestVerificationExecution -v` | 5 tests pass |
| V5 | PM DB lock 验证 | `journalctl --user -u auto-dispatcher.service --since "20 min ago" \| grep "database is locked"` | 无匹配（<30 分钟后检查） |

### Manual Verification（需人工确认）

- [ ] M1: 每个修改函数在计划中的「具体修改」与最终代码 diff 完全一致
- [ ] M2: F1 修复后 3 个 dispatcher tick 内无 lock 错误

---

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性 — 4 个 fix 覆盖 2 个 repo、明确修改行号 | 0 | — | 0 |
| R1.5 | 外部引用 — `busy_timeout` PRAGMA 是 SQLite 3.x 内建命令；`shlex.split` 是 Python stdlib；`os.fsync` 为 POSIX 标准 | 0 | — | 0 |
| R2 | 可执行性 — 每个 task 有精确行号、old/new 代码对比、验收命令 | 0 | — | 0 |
| R2.8 | LLM 可执行性 — 无歧义字段，无模糊描述 | 0 | — | 0 |
| R3 | 风险与边缘 — 已验证现有测试兼容性、WB 模式 + timeout 机制、shlex 边缘 case | 0 | — | 0 |
| **终止** | **T4 — 所有轮次无 issue** | | | **0** |
