"""Backend registration, agent commands, and auto-dispatch.

This module re-exports symbols from :mod:`loop_kit._core` that belong to the
``dispatch`` section of the ``_SECTION_OWNERSHIP_MAP``.
"""

from loop_kit._core import *  # noqa: F401,F403
from loop_kit._core import _POST_ROUND_DISPATCH, _SINGLE_ROUND_PHASE_HANDLERS, _STATE_HANDLERS, _TERMINAL_OUTCOME_HANDLERS, _dispatch_post_round, _dispatch_single_round_phase, _dispatch_terminal_outcome, _is_post_round_awaiting_next, _is_post_round_terminal_success, _is_terminal_resume_failure, _is_terminal_resume_success, _post_round_handle_awaiting_next_round, _post_round_handle_fail, _post_round_handle_terminal_success, _single_round_handle_changes_required, _single_round_handle_review_approved, _single_round_handle_worker_noop, _terminal_outcome_handle_error, _terminal_outcome_handle_resume_failure, _terminal_outcome_handle_resume_success  # noqa: F401

__all__ = ['_POST_ROUND_DISPATCH', '_SINGLE_ROUND_PHASE_HANDLERS', '_STATE_HANDLERS', '_TERMINAL_OUTCOME_HANDLERS', '_dispatch_post_round', '_dispatch_single_round_phase', '_dispatch_terminal_outcome', '_is_post_round_awaiting_next', '_is_post_round_terminal_success', '_is_terminal_resume_failure', '_is_terminal_resume_success', '_post_round_handle_awaiting_next_round', '_post_round_handle_fail', '_post_round_handle_terminal_success', '_single_round_handle_changes_required', '_single_round_handle_review_approved', '_single_round_handle_worker_noop', '_terminal_outcome_handle_error', '_terminal_outcome_handle_resume_failure', '_terminal_outcome_handle_resume_success']
