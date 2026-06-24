"""PM-driven review loop orchestrator (facade).

This module is a backward-compatible facade that re-exports all public
symbols from the focused sub-modules.  Existing ``from loop_kit.orchestrator
import X`` imports continue to work without changes.

Module structure (T-722):
    exceptions.py   — exception hierarchy
    paths.py        — constants, LoopPaths, path helpers
    state.py        — state machine, transitions, state I/O
    file_bus.py     — prepare/archive/wait bus files
    dispatch.py     — backend registration, agent commands, auto-dispatch
    session.py      — SessionManager, resume policy
    config.py       — RunConfig, load/validate config
    prompts.py      — render task packet, worker/reviewer prompts
    knowledge.py    — knowledge retrieval, FTS, patterns
    git_helpers.py  — git operations, diff, worktree management
    _core.py        — internal full implementation (do not import directly)

Implementation note: this module aliases ``loop_kit._core`` via
``sys.modules`` so that ``monkeypatch.setattr(orchestrator, X, val)``
mutates the same namespace that the implementation code resolves names
from.  This preserves full backward compatibility for test monkeypatching.
"""

import sys as _sys

from loop_kit import _core as _core_module

# ── updated ownership maps (T-722) ───────────────────────────────────────────
# Defined BEFORE the module alias so they land on _core_module.
_core_module._SECTION_OWNERSHIP_MAP = {
    "exceptions": ("LoopKitError", "StateError", "DispatchError", "ValidationError", "ConfigError"),
    "paths": ("LoopPaths", "_path", "_configure_loop_paths", "_resolve_paths"),
    "state": ("_default_state", "_load_state", "_save_state", "_apply_state_transition"),
    "file_bus": ("_prepare_bus_file", "_archive_bus_file", "_wait_for_file", "_sync_task_card_to_bus"),
    "lock": ("_lock_file", "_unlock_file", "_LoopLock", "_acquire_run_lock"),
    "dispatch": ("register_backend", "_agent_command", "_run_auto_dispatch", "_dispatch_with_artifact_fallback"),
    "session": ("SessionManager", "_session_resume_id", "_resolve_session_resume_policy", "_store_session"),
    "config": ("RunConfig", "_load_config", "_load_env_config", "_validate_run_config", "_warn_unknown_config_keys"),
    "prompts": ("_render_task_packet_section", "_worker_prompt", "_reviewer_prompt"),
}

_core_module._SECTION_MODULE_PATHS = {
    "exceptions": "src/loop_kit/exceptions.py",
    "paths": "src/loop_kit/paths.py",
    "state": "src/loop_kit/state.py",
    "file_bus": "src/loop_kit/file_bus.py",
    "lock": "src/loop_kit/file_bus.py",
    "dispatch": "src/loop_kit/dispatch.py",
    "session": "src/loop_kit/session.py",
    "config": "src/loop_kit/config.py",
    "prompts": "src/loop_kit/prompts.py",
    "knowledge": "src/loop_kit/knowledge.py",
    "git_helpers": "src/loop_kit/git_helpers.py",
}

# ── module alias: make 'orchestrator' and '_core' share one namespace ───────
# This ensures monkeypatch.setattr(orchestrator, X, val) affects the
# actual runtime namespace used by all implementation functions.
_sys.modules[__name__] = _core_module
