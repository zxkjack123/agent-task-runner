# 修复计划：ATR heartbeat timeout + events 消费瓶颈

> **状态**: 待执行  
> **范围**: 1 repo — `project_management`  
> **改动量**: 2 个 task，约 6 行代码

---

## 背景与根因

### 问题 1: heartbeat timeout 过短

**现象**：T-585 在 23:05 dispatch → 23:08 opencode worker 成功完成 (`Auto-dispatch done: role=worker backend=opencode attempts=1`) → 进入 `Waiting for work_report.json` → 23:10 bridge 检测到 `state="awaiting_work"` + `no sessions` > 300s → 标记 failed。

**根因链**：
1. loop_kit 在 dispatch done 后需要等 Worker 端产生 `work_report.json`（artifact-timeout=300s）
2. Worker 在 agent-task-runner cwd 中首次启动 opencode 需要 60s+ 初始化 + LLM 推理需要 1-4 分钟
3. bridge 的 `_HEARTBEAT_TIMEOUT_SEC=300` 在 `check_and_handle_results` 中检测到 `atr_state=="awaiting_work"` 且无 sessions 超过 5 分钟 → kill + mark failed
4. **冲突**：artifact-timeout 是 300s（Worker 写 artifact），但 heartbeat timeout 也是 300s（从开始到 state 变化）——两者重叠导致过早 kill

**T-585 的 state.json 显示**：`"state": "done", "outcome": "interrupted", "error": "User interrupted (SIGTERM)"` —— state 已 done 但因为 SIGTERM 在 artifact-timeout 之前到达。

**修复方案**：提升 `_HEARTBEAT_TIMEOUT_SEC` 从 300 → 600（与 dispatch-timeout 对齐），给 Worker 充足时间生成 work_report。

### 问题 2: events.jsonl 读取逻辑低效

**现象**：bridge 的 `read_latest_events` 每次从 offset=0 开始读整个 events.jsonl（L610），随文件增长效率下降。

**根因**：loop_kit 每秒都在追加 events.jsonl，但 bridge 的 `read_latest_events` 每次重新解析整个文件。

**修复方案**：将 `last_offset` 存储在 `auto_task_queue` 表中，增量读取而非每次全量扫描。

**但是**：当前 events.jsonl 最大约 10-20KB（~50 行），全量扫描性能影响可忽略。且加 offset 需要新增 DB column。改为**在内存中缓存 last_offset**（bridge 模块级变量），避免重复解析。

### 非修复范围

- **opencode CLI shell 超时**：不影响 ATR dispatch（已验证 subprocess PIPE 通路成功）
- **orphan retry 上限**：3 次重试语义正确
- **events.jsonl 磁盘增长**：每个 loop_run 独立，自动归档

---

## 修改方案

### Task 1: 提升 heartbeat timeout 从 300s → 600s

**文件**: `/home/gw/opt/project_management/src/auto_task/bridge.py`

**修改**：L34 `_HEARTBEAT_TIMEOUT_SEC = 300` → `_HEARTBEAT_TIMEOUT_SEC = int(os.environ.get('ATR_HEARTBEAT_TIMEOUT', '600'))`

**理由**：
- 与 `--dispatch-timeout 600` 对齐
- opencode 冷启动 + LLM 推理 4 分钟 + artifact 写入余量
- 环境变量覆盖提供灵活性

**影响范围**：`check_and_handle_results` L590 单次检测

### Task 2: events.jsonl 增量读取性能优化

**文件**: `/home/gw/opt/project_management/src/auto_task/bridge.py`

**修改**：`read_latest_events` 函数改为接收并返回 offset；bridge 模块维护 `_last_event_offsets: dict[str, int]` 字典缓存每个 loop_dir 的最后读取位置。

**但简化为最小修改**：用文件 mtime 缓存替代 offset 追踪——如果 mtime 未变，跳过重读。改动量更小，效果等价。

**具体修改**：
1. L478-480 函数签名改为 `def read_latest_events(loop_dir: str) -> ...`，在函数体内加 mtime 缓存:
   ```python
   _events_mtime_cache: dict[str, float] = {}
   
   def read_latest_events(loop_dir: str) -> tuple[list[dict[str, object]], bool]:
       path = Path(loop_dir) / "events.jsonl"
       if not path.exists():
           return [], False
       mtime = path.stat().st_mtime
       if _events_mtime_cache.get(loop_dir) == mtime:
           return [], False  # unchanged since last read
       _events_mtime_cache[loop_dir] = mtime
       # ... 读取并返回
   ```

2. L610 调用处更新接收 `has_new` 返回值

**理由**：events.jsonl 在 dispatch 不活跃时频繁被重读（每 5 分钟一次 tick），每次完整解析 JSON 是浪费。mtime 缓存零开销检查。

---

## 执行计划

### Phase 1: heartbeat timeout 提升

#### Task 1.1: `_HEARTBEAT_TIMEOUT_SEC` 300 → 600 + 环境变量化

- **目标**: 给 Worker 充足时间完成 LLM 推理并生成 work_report
- **依赖**: 无
- **修改文件**:
  - `/home/gw/opt/project_management/src/auto_task/bridge.py`
- **修改边界**:
  - 仅修改 L34 一行
  - 不修改 `check_and_handle_results` 的检测逻辑
  - 不修改 `_TIMEOUT_SEC`、`_IDLE_TIMEOUT_SEC`、`_DISPATCH_TIMEOUT_SEC`
- **具体修改**:
  ```python
  # L34: 旧
  _HEARTBEAT_TIMEOUT_SEC = 300  # 5 min in awaiting_work → stale
  # L34: 新
  _HEARTBEAT_TIMEOUT_SEC = int(os.environ.get('ATR_HEARTBEAT_TIMEOUT', '600'))
  ```
- **验收标准**:
  - ✅ `python -m py_compile` pass
  - ✅ 默认值 = 600
  - ✅ `ATR_HEARTBEAT_TIMEOUT=300` 覆盖验证通过

### Phase 2: events.jsonl 增量读取

#### Task 2.1: mtime 缓存优化 `read_latest_events`

- **目标**: 避免每 5 分钟重读未变化的 events.jsonl
- **依赖**: 无（与 T1.1 并行）
- **修改文件**:
  - `/home/gw/opt/project_management/src/auto_task/bridge.py`
- **修改边界**:
  - 修改 L478-510 的 `read_latest_events` 函数
  - 更新 L610 调用处
- **具体修改**:
  1. L478 函数签名前加模块级变量 `_events_mtime_cache = {}`
  2. L478-480 改为:
     ```python
     def read_latest_events(loop_dir: str) -> tuple[list[dict[str, object]], bool]:
         path = Path(loop_dir) / "events.jsonl"
         if not path.exists():
             _events_mtime_cache.pop(loop_dir, None)
             return [], False
         try:
             mtime = path.stat().st_mtime
         except OSError:
             return [], False
         if _events_mtime_cache.get(loop_dir) == mtime:
             return [], False
         _events_mtime_cache[loop_dir] = mtime
         # ... 保留原始读取逻辑 ...
     ```
  3. L610 调用处接收 `(events, has_new)`:
     ```python
     events, _has_new = read_latest_events(loop_dir_str)
     if events:
     ```
- **验收标准**:
  - ✅ `python -m py_compile` pass
  - ✅ mtime 缓存: 同一文件名两次调用返回 `[]`
  - ✅ mtime 变化后正常返回新 events

---

## Post-Execution Verification

| ID | Description | Command | Expected |
|----|-------------|---------|----------|
| V1 | py_compile bridge | `python -m py_compile /home/gw/opt/project_management/src/auto_task/bridge.py` | exit 0 |
| V2 | heartbeat default | `python -c "from src.auto_task.bridge import _HEARTBEAT_TIMEOUT_SEC; print(_HEARTBEAT_TIMEOUT_SEC)"` | 600 |
| V3 | heartbeat override | `ATR_HEARTBEAT_TIMEOUT=900 python -c "from src.auto_task.bridge import _HEARTBEAT_TIMEOUT_SEC; print(_HEARTBEAT_TIMEOUT_SEC)"` | 900 |
| V4 | events cache | `python -c "from src.auto_task.bridge import read_latest_events; e1,_=read_latest_events('.'); e2,_=read_latest_events('.'); assert not e2, f'expected empty, got {e2}'; print('OK')"` | OK |
| V5 | dispatcher log | `journalctl --user -u auto-dispatcher.service --since "15 min ago" \| grep -E "ERROR\|locked"` | 空 |

## 审查日志

| 轮次 | 聚焦 | 发现问题数 | 已修正 | 剩余 |
|------|------|-----------|--------|------|
| R1 | 结构完整性 — 2 个独立 task | 0 | — | 0 |
| R1.5 | 外部引用 — `mtime` 是 `Path.stat().st_mtime` 标准属性；环境变量命名与其他 timeout 一致 | 0 | — | 0 |
| R2 | 可执行性 — 精确行号和代码对比 | 0 | — | 0 |
| R2.8 | LLM 可执行性 — 零歧义 | 0 | — | 0 |
| R3 | 风险 — heartbeat 过长可能导致真僵尸任务 10 分钟才被清理；可通过 `ATR_HEARTBEAT_TIMEOUT` 降级 | 已记录 | — | 0 |
| **终止** | **T4 — 全部 0 issue** | | | **0** |
