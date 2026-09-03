# Revision Disposition — ATR Consumer Contract

> PM #3263 T3.2 — ATR-owned specification; copilot-agents is **OUT-OF-SCOPE**.

## Purpose

Define the ATR-side contract for session revision disposition: the structured
signal that a **task-executor** session can emit to declare whether its plan
patch was applied, rejected, or partially applied — and what the downstream
(ATR loop driver / PM coordinator / acceptance reviewer) should do with it.

## Contract Location

ATR-side only. The concept `revision_disposition` does **not** exist in the
copilot-agents repository (grep 0 hits as of 2026-09-03). The ATR loop is the
**producer** of this signal; the copilot-agents `pm-task-closed-loop` skill is
the **consumer** in the T1/T2 pipeline. The schema is defined here so that
both sides can evolve independently.

## Schema

```yaml
revision_disposition:
  verdict: applied | rejected | partial
  applied_commit: "<sha>"         # mandatory when verdict=applied
  blocked_anchors: [<anchor>]     # mandatory when verdict=partial
  skip_reason: "<text>"           # mandatory when verdict=rejected
  plan_patch_verified: true|false # whether the T2.3 hard gate passed
```

## Integration Points

| Layer | Mechanism | Status |
|-------|-----------|--------|
| ATR `_run_single_round` | `_verify_plan_patch_scope` (T2.3) produces `plan_patch_verified` | ✅ implemented |
| ATR `_run_multi_round_via_subprocess` | Reads child exit code; appends `plan_patch_review` info event | ✅ implemented |
| PM #3263 summary | Optional `budget` block includes `task_mode` | ✅ implemented in RunConfig |
| copilot-agents | **No** `revision_disposition` symbol exists | ⚠️ OUT-OF-SCOPE |

## Why ATR-Owned

- The copilot-agents repository is the **dev-repo** for agent definitions,
  skills, and instructions; it does not contain ATR runtime code.
- `revision_disposition` is a runtime contract between the ATR executor and
  the PM closed-loop pipeline. Defining it here keeps the ATR loop as the
  single source of truth for execution semantics.
- If copilot-agents adopts this concept in the future, this document serves
  as the canonical reference.

## Design Notes

- `verdict=partial` is the most common outcome for plan-patch tasks that hit
  heading-anchor or file-scope constraints.
- `plan_patch_verified` is the authoritative field; the textual verdict is
  derived from it.
- The `skip_reason` field is human-readable and intended for PM/acceptance
  triage, not for automated routing.
