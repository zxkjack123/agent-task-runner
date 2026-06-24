"""Thin CLI entry-point that imports from the focused modules directly.

This demonstrates that the orchestrator.py facade is optional — callers
can import directly from the sub-modules (e.g. ``loop_kit._core``) instead
of going through the facade.
"""

from loop_kit._core import main

__all__ = ["main"]
