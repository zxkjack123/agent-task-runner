"""Suite-wide isolation for loop-kit module-global path state.

The production function ``loop_kit.orchestrator._configure_loop_paths()``
mutates module-level globals (``_stored_paths``, ``_LOGS_DIR_ENSURED``,
``_LOGS_DIR_ENSURED_PATH``) and several test files call it directly without
restoring afterwards (tests/test_integration.py, tests/test_pm_integration.py).
Without a suite-level autouse fixture that state leaks across test files within
the same pytest session (files run in alphabetical order), so later files
observe polluted paths — the pre-existing failure tracked in PM #2748.

This fixture generalizes the file-scoped ``_isolate_orchestrator_path_globals``
fixture in tests/test_orchestrator.py to the whole suite: it snapshots the same
set of mutable module globals before every test and restores them afterwards.
Restoring is idempotent with the file-scoped fixture (both restore their own
snapshots, which are equal when the suite state is clean).
"""

from __future__ import annotations

import pytest

from loop_kit import orchestrator


@pytest.fixture(autouse=True)
def _isolate_orchestrator_module_globals() -> None:
    original_root = orchestrator.ROOT
    original_stored_paths = orchestrator._stored_paths
    original_feed_task_id = orchestrator._FEED_TASK_ID
    original_feed_round = orchestrator._FEED_ROUND
    original_feed_run_id = orchestrator._FEED_RUN_ID
    original_feed_route_policy = orchestrator._FEED_TASK_ROUTE_POLICY
    original_logs_ensured = orchestrator._LOGS_DIR_ENSURED
    original_logs_ensured_path = orchestrator._LOGS_DIR_ENSURED_PATH
    yield
    orchestrator.ROOT = original_root
    orchestrator._stored_paths = original_stored_paths
    orchestrator._set_feed_task_id(original_feed_task_id)
    orchestrator._set_feed_round(original_feed_round)
    orchestrator._set_feed_run_id(original_feed_run_id)
    orchestrator._set_feed_task_route_policy(original_feed_route_policy)
    orchestrator._LOGS_DIR_ENSURED = original_logs_ensured
    orchestrator._LOGS_DIR_ENSURED_PATH = original_logs_ensured_path
