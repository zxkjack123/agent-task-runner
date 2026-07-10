# 全链路端到端集成测试计划 v2

## 现实情况

当前 591 个测试全部在自己的 repo 内。**没有跨 repo 的全链路测试。**
有 8 个关键代码路径未被覆盖，需要 ~16 个新测试。

---

## Phase 1: PM→ATR→PM 全链路 (项目 management repo, 1.5h)

### 文件: `project_management/tests/test_full_chain.py`

### 共享 fixture

```python
@pytest.fixture
def db_conn():
    """In-memory SQLite with auto_task_queue + tasks + projects tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(TABLE_SQL)
    conn.execute("INSERT INTO tasks (id, title, project_id, status) VALUES (1,'Test',1,'doing')")
    conn.execute("INSERT INTO projects (id, name) VALUES (1,'test-project')")
    return conn

def simulate_atr_completion(loop_dir: Path, outcome: str = "approved"):
    """Write ATR output files as if a real ATR run completed."""
    loop_dir.mkdir(parents=True, exist_ok=True)
    (loop_dir / "summary.json").write_text(json.dumps({
        "task_id": "1", "outcome": outcome, "rounds": 1, "exit_code": 0,
        "decision": "approve", "files_changed": ["a.py"], "worker_notes": "done",
        "review_blocking": [], "review_non_blocking": [], "duration_ms": 1000,
    }))
    (loop_dir / "events.jsonl").write_text(
        json.dumps({"event":"state_change","state":"awaiting_review","round":1}) + "\n" +
        json.dumps({"event":"terminal","outcome":outcome,"rounds":1}) + "\n"
    )
```

### 测试列表 (8 tests)

| # | 测试 | 验证 |
|---|------|------|
| 1 | `test_approved → task done` | approve → PM task status=review, progress=100, queue.status=done |
| 2 | `test_no_change_success → task done` | no_change_success 同 approved 行为 |
| 3 | `test_timeout → task failed` | timeout → PM task notes 含错误信息, queue.status=failed |
| 4 | `test_validation_failure → task failed` | validation_failure → PM task 标记 needs_attention |
| 5 | `test_corrupted_summary → no crash` | 损坏 summary → 不崩溃, 降级到运行中 |
| 6 | `test_events_update_progress` | running task + events → progress 字段从 events.jsonl 更新 |
| 7 | `test_highest_priority_picked` | 3 queued tasks → pick_queued 返回 deadline 最近的高优先级 |
| 8 | `test_concurrent_limit` | MAX_CONCURRENT=1 + running task → pick_queued=None |

### 关键 mock

```python
# mock dispatch_atr: 不启动 ATR，改为模拟 ATR 完成
with patch("bridge.dispatch_atr") as mock_dispatch:
    mock_dispatch.side_effect = lambda entry, project_dir: simulate_atr_completion(
        Path(entry["loop_dir"]), "approved"
    )
```

---

## Phase 2: AOM→ATR→PM 全链路 (project_management repo, 1h)

### 文件: 追加到 `project_management/tests/test_full_chain.py`

### 共享 fixture (复用 Phase 1)

### 测试列表 (6 tests)

| # | 测试 | 验证 |
|---|------|------|
| 9 | `test_handler_approved` | pm_outcome_handler approved → PM task status=review, progress=100 |
| 10 | `test_handler_timeout` | pm_outcome_handler timeout → PM task notes 含 timeout |
| 11 | `test_handler_all_outcomes` | 循环全部 11 个 outcome → 验证映射表不丢词 |
| 12 | `test_handler_missing_file` | 不存在 outcome.json → 正常退出 |
| 13 | `test_handler_no_running_task` | queue 中无 running task → 不崩溃 |
| 14 | `test_handler_already_done` | queue 已 done 状态 → 不重复更新 |

测试 11 的核心：
```python
for outcome, expected_pm_status in OUTCOME_TO_PM_STATUS.items():
    reset_db()
    simulate_atr_completion(loop_dir, outcome)
    pm_outcome_handler_main(loop_dir, "1")
    row = conn.execute("SELECT status FROM auto_task_queue WHERE task_id=1").fetchone()
    assert row["status"] == expected_pm_status_to_queue_status(expected_pm_status)
```

---

## Phase 3: ATR mock 全链路 (agent-task-runner repo, 0.5h)

### 文件: 追加到 `agent-task-runner/tests/test_pm_integration.py`

### 测试列表 (2 tests)

| # | 测试 | 验证 |
|---|------|------|
| 15 | `test_full_cycle_approved` | mock ATR loop → summary.json 字段正确 |
| 16 | `test_full_cycle_events_stream` | mock ATR loop → events.jsonl 包含 state_change + terminal |

使用 `_write_round_summary` 和 `_emit_event` 直接测试，不需要 subprocess。

---

## Phase 4: Go 侧验证 (AOM repo, 0.5h)

### 文件: 追加到 `AOM/pipeline_loop_test.go`

### 测试列表 (1 test)

| # | 测试 | 验证 |
|---|------|------|
| 17 | `testSyncPMOutcomeCalledAfterOutcome` | syncPMOutcome 在 readOutcomeJSON 后被调用 |

---

## 不做的测试

| 不做 | 原因 |
|------|------|
| 真实 opencode 调用 | E2E 不稳定（API 超时），用 mock 替代 |
| AOM dispatch_atr → ATR subprocess | Go→Python subprocess 验证已在 Phase 1 mock 覆盖 |
| 多 lane 并行 | 当前 max-parallel-workers=1 是生产默认 |
| pm_outcome_handler 飞书通知 | 飞书 API 不可靠，跳过 |

---

## 执行顺序

```
Phase 1 (8 tests, 1.5h) → Phase 2 (6 tests, 1h) → Phase 3 (2 tests, 0.5h) → Phase 4 (1 test, 0.5h)
```

## 最终验收

```
cd project_management && pytest tests/test_full_chain.py -v   # 14 passed
cd agent-task-runner && pytest tests/test_pm_integration.py -v  # 21 passed (+2)
cd agent-orchestrator-management && go test ./internal/cli/...  # pipeline_loop tests pass

Total: 591 + 16 = 607 tests across 3 repos
```
