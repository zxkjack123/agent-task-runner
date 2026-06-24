# Loop Kit — Let AI Write Code, Then Review Itself

[![ci](../../actions/workflows/loop-ci.yml/badge.svg)](../../actions/workflows/loop-ci.yml)

**You describe the task. AI writes the code. AI reviews the code. Repeat until it's right.**

Most AI coding tools stop after generating code. Loop Kit closes the loop — a PM agent coordinates a Worker AI that writes code and a Reviewer AI that validates it, iterating automatically until the code passes or you step in.

## The Problem

AI coding assistants are great at writing code, but someone still has to review the output, catch edge cases, and iterate on feedback. That "someone" is usually **you** — which defeats the point.

## The Solution

```
You describe the goal → PM agent creates the task card → Worker writes → Reviewer validates → ... → ✅ Approved
```

| What | Before | With Loop Kit |
|------|--------|---------------|
| Writing | Manual or AI-assisted | Worker AI, scoped to your task |
| Reviewing | You or a teammate | Reviewer AI, against your criteria |
| Iterating | Back-and-forth PR comments | Automatic, until approved or max rounds |
| Tracking | Scattered across PRs & chats | Structured state, full audit trail |

## ✨ Why Teams Use Loop Kit

- **Ship faster** — Eliminate the manual review bottleneck
- **Consistent quality** — Your standards enforced every time, no fatigue
- **Full audit trail** — Every round, every decision, every diff logged
- **Works with your tools** — Codex, Claude, or OpenCode. Git-native
- **Scales with complexity** — Multi-lane execution, dependency-aware task graphs
- **Zero lock-in** — Open source, extensible backend registry, your data stays in your repo

## Quick Start

```bash
# 1. Initialize
loop init

# 2. (optional) Pre-index for faster context
loop index

# 3. Create a task card, then run
loop run --task .loop/task_card.json --auto-dispatch --worker-backend codex --reviewer-backend codex
```

**Prerequisites:** Python >= 3.11, Git repo, at least one AI backend ([codex](https://github.com/openai/codex), [claude](https://docs.anthropic.com/en/docs/claude-code), or [opencode](https://opencode.ai)).

**Your only job is to define the goal — the PM agent generates the task card for you:**

```json
{
  "task_id": "T-001",
  "goal": "Add input validation to user registration endpoint",
  "in_scope": ["src/api/auth.py", "tests/test_auth.py"],
  "out_of_scope": ["UI changes"],
  "acceptance_criteria": [
    "Email format validated",
    "Password strength enforced",
    "Tests cover edge cases"
  ]
}
```

That's it. Loop Kit handles the rest. Run `loop status --tree` anytime to see where things stand.

## Deep Dive

<details>
<summary><strong>How It Works</strong></summary>

Each round:

1. **Worker AI** reads the task card and writes code
2. **Reviewer AI** checks the output against acceptance criteria
3. If changes are needed, the loop repeats (up to `--max-rounds`)
4. When approved, you get a clean diff and full audit trail

```
Round 1: Worker → Reviewer → changes_required
Round 2: Worker → Reviewer → approve ✅
```

All state is tracked in `.loop/`:

| File | What it tells you |
|------|-------------------|
| `state.json` | Current round, status, decisions, and active `run_id` |
| `logs/feed.jsonl` | Full event log |
| `archive/{task_id}/` | Artifacts from every round |

</details>

<details>
<summary><strong>Architecture</strong></summary>

### Components

```
                         ┌──────────────────────┐
                         │   orchestrator.py     │  facade (re-exports)
                         │   (public API)        │
                         └──────────┬───────────┘
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
     ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
     │ exceptions.py  │   │   paths.py     │   │   state.py     │
     │ (leaf)         │   │   (leaf)       │   │ → exceptions,  │
     │                │   │                │   │   paths        │
     └────────────────┘   └────────────────┘   └────────────────┘
     ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
     │ file_bus.py    │   │ dispatch.py    │   │ session.py     │
     │ → exceptions,  │   │ → exceptions,  │   │ → exceptions,  │
     │   paths        │   │   paths,       │   │   paths, state │
     │                │   │   session      │   │                │
     └────────────────┘   └────────────────┘   └────────────────┘
     ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
     │ config.py      │   │ prompts.py     │   │ knowledge.py   │
     │ → exceptions,  │   │ → paths,       │   │ → paths        │
     │   paths        │   │   config       │   │                │
     └────────────────┘   └────────────────┘   └────────────────┘
     ┌────────────────┐   ┌────────────────┐
     │ git_helpers.py │   │   _core.py     │
     │ → exceptions,  │   │ (full impl,    │
     │   paths        │   │  internal)     │
     └────────────────┘   └────────────────┘

                     ┌──────────┐
                     │   PM     │  orchestrator (facade)
                     │(outer)   │
                     └────┬─────┘
               ┌──────────┼──────────┐
               ▼          ▼          ▼
        ┌──────────┐ ┌──────────┐
        │  Worker  │ │ Reviewer │   (codex/claude/opencode subprocess)
        │(codex/   │ │(codex/   │
        │claude/   │ │claude/   │
        │opencode) │ │opencode) │
        └──────────┘ └──────────┘
```

**Module dependency DAG** (no circular imports):

```
exceptions (leaf) ──┐
paths (leaf) ───────┤
                    ├──→ state ──→ session ──→ dispatch
                    ├──→ file_bus
                    ├──→ config ──→ prompts
                    ├──→ git_helpers
                    └──→ knowledge ──→ prompts
```

`_core.py` contains the full implementation; each focused module re-exports its section's symbols from `_core`. The `orchestrator.py` facade re-exports from all modules and aliases `_core` via `sys.modules` to preserve test monkeypatching compatibility.

### File Bus Protocol

```
PM → Worker:   task_card.json / fix_list.json
Worker → PM:   work_report.json
PM → Reviewer: review_request.json
Reviewer → PM: review_report.json
```

`work_report.json` and `review_report.json` are identity-bound by `task_id` + `round` + `run_id`.  
`run_id` is generated once per loop run and persisted in `state.json`.

### State Machine

| State | Meaning |
|-------|---------|
| `idle` | No active contract |
| `awaiting_work` | Worker phase |
| `awaiting_review` | Reviewer phase |
| `done` | Terminal (approved, timeout, or blocked) |

Worker no-change (`head_sha == base_sha` after immutable OID resolution) is explicit:
- default: terminal `validation_failure` (`worker_noop_as_error=true`)
- optional: terminal `no_change_success` and reviewer is skipped (`--worker-noop-as-success`)

Transition stale-key policy is explicit and validated before `state.json` persistence:

| Transition | Stale keys cleared | Required carry-forward | Forbidden residue |
|-------|---------|---------|---------|
| `bootstrap` | `outcome`, `failed_at`, `error`, `head_sha`, `round_details` | none | none |
| `prepare_round` | `outcome`, `failed_at`, `error`, `head_sha`, `round_details` | `round_details` (and optional `head_sha` carry-forward when resuming an in-flight round) | `outcome`, `failed_at`, `error` |
| `reviewer_changes_required` (retry) | `outcome`, `failed_at`, `error`, `head_sha`, `round_details` | `round_details` (and explicit `head_sha` carry-forward for next-round contract continuity) | `outcome`, `failed_at`, `error` |

If a transition tries to persist forbidden residue (for example stale `error` on a retry), the transition is rejected with a state error before any write.

### Session Management

- **Quickstart**: Fresh context for cold starts (round 1)
- **Handoff**: Structured bridge every round for both roles
- **Warm resume**: Reuse backend sessions for low-latency continuation
- **Session rotation**: Set `--max-session-rounds` to intentionally rotate
- **Explicit invalidation contract**: both worker and reviewer sessions are cleared from one shared policy whenever task/round/run contracts drift or git base/head contract is no longer safe (including history rewrites/rewinds)
- **Strict rotation contract**: when `--max-session-rounds > 0`, only sessions with valid `started_round` are resumable; rotated/legacy entries are cleared before dispatch and persistence
- **Deterministic retry budget**: dispatch attempts are always bounded to `--dispatch-retries + 1` (invalid resume fallback consumes that same budget)

### Internal Dependency Diagnostics

`loop status --dependency-map` prints a lightweight internal dependency map for critical orchestrator sections:

- `dispatch` → `src/loop_kit/dispatch.py`
- `session` → `src/loop_kit/session.py`
- `file-bus` → `src/loop_kit/file_bus.py`
- `state` → `src/loop_kit/state.py`

The `_SECTION_OWNERSHIP_MAP` and `_SECTION_MODULE_PATHS` in `orchestrator.py` map section names to their owning module files. The diagnostic includes owner symbols, upstream dependencies, and core contracts, plus an integrity line that flags missing symbols after refactors.

### Integration Lane (Deterministic Merge V1)

When `lanes` run in parallel, Loop Kit adds an explicit internal integration lane before reviewer handoff:

- Lanes are merged in deterministic `lane_execution_order` (stage order, then task-card declaration order).
- Merge policy: ordered replay of each lane commit chain (`base..lane_head`) via `git cherry-pick` onto the integration head (rebase-style replay).
- Deterministic preflight runs before replay and reports likely lane conflicts (overlapping commit ancestry and touched paths) in `merge_provenance.preflight`.
- Configure conflict handling via task-card `lane_merge_conflict_policy`:
  - `fail_fast` (default): abort replay on first conflict, reset integration head back to base, fail the round.
  - `skip_lane`: abort the conflicting cherry-pick, mark that lane as `skipped_conflict`, continue replay for remaining lanes.
  - `defer_lane`: defer conflicting lanes, replay remaining lanes first, then retry deferred lanes once in deterministic defer order. If any deferred lane still conflicts on retry, integration fails (`lane_merge_failed`) instead of silently dropping lane commits.
- Configure worktree retention with task-card `lane_preserve_worktrees_on_failure` (default `true`): when enabled, failed lane rounds keep worktrees for debugging; when disabled, lane worktrees are cleaned up.
- Optional lane reviewer fan-out: set `lane_review_parallel: true` in the task card to dispatch a reviewer for each completed lane before integration.
- Lane reviewer gate is deterministic: every enabled lane review must return `approve` before integration can proceed.
- The merged `work_report.json` includes `merge_provenance` (`base_sha`, merged head, lane order, per-lane commit replay, and integration acceptance checks).
- Lane worker reports (`.loop/work_reports/{lane_id}.json`) include runtime telemetry: `lane_id`, `backend`, `status`, `duration_ms`, and optional token/cost fields (`input_tokens`, `output_tokens`, `total_tokens`, `cost_cents`).
- Lane reviewer reports are stored at `.loop/review_reports/{lane_id}.json` when `lane_review_parallel` is enabled.

### Knowledge System

Loop Kit retrieves **relevant context** rather than injecting raw code:

- **Facts** — Project conventions | **Pitfalls** — Known issues
- **Patterns** — Coding patterns | **Module Map** — Offline codebase index
- Optional local index: `.loop/context/knowledge.sqlite3` with SQLite FTS5 (`MATCH` + `bm25`) when available.
- Deterministic fallback stays file-based (`project_facts.md`, `pitfalls.md`, `patterns.jsonl`) when FTS5/SQLite is unavailable.
- If runtime `MATCH` fails (for example local sqlite build/runtime mismatch), retrieval automatically degrades to SQLite `LIKE` ranking without breaking prompt rendering.
- Latency diagnostics are built in via `loop knowledge benchmark --query "<text>"`.

</details>

<details>
<summary><strong>CLI Reference</strong></summary>

### Commands

```
loop init                  Create .loop/ directory and templates
loop index                 Build offline module map
loop run                   Run the full review loop
loop knowledge             Manage built-in knowledge
loop status                Show current state (--tree for DAG view, --dependency-map for internals)
loop health                Show worker/reviewer heartbeat
loop dispatch-metrics      Summarize latency metrics
loop diff                  Compare artifacts between rounds
loop report                Summarize task progress
```

### `loop run` flags

| Flag | Default | Description |
|------|---------|-------------|
| `--task PATH` | `.loop/task_card.json` | Task card path |
| `--max-rounds N` | 3 | Max review rounds |
| `--auto-dispatch` | off | Auto-invoke backends each round |
| `--worker-backend` | codex | `codex`, `claude`, or `opencode` |
| `--reviewer-backend` | codex | `codex`, `claude`, or `opencode` |
| `--dispatch-timeout N` | 0 | Per-dispatch timeout (0=unlimited) |
| `--dispatch-retries N` | 2 | Retries on non-zero exit |
| `--worker-noop-as-success` | off | Accept worker no-change (`head==base`) as terminal success |
| `--max-session-rounds N` | 0 | Session reuse before rotation |
| `--resume` | off | Resume from state.json |
| `--verbose` | off | Stream backend stdout |

Full flag list: `loop run --help`

### `loop knowledge` subcommands

- `list [--category <name>]`: list default knowledge rows.
- `add --pattern ... --category ... --confidence ... --source ...`: append a default pattern row.
- `prune --older-than <days>`: prune default rows by `source_version`.
- `dedupe`: deduplicate default knowledge rows.
- `benchmark --query "<text>" [--iterations N]`: run local retrieval benchmark and print `avg_ms`/`p50_ms`/`p95_ms`, corpus composition, and millisecond-class threshold verdict.

### Configuration

`loop run` reads from `.loop/config.yaml` (preferred) or `.loop/config.json`.

Env var overrides: `LOOP_MAX_ROUNDS`, `LOOP_DISPATCH_TIMEOUT`, `LOOP_BACKEND_PREFERENCE`, `LOOP_WORKER_NOOP_AS_ERROR`.

Resolution order: `CLI args > env vars > config file > built-in defaults`

</details>

<details>
<summary><strong>Performance & Optimization</strong></summary>

### Metrics

`loop dispatch-metrics` reports phase latencies (`startup_ms`, `context_to_work_ms`, `work_to_artifact_ms`, `total_ms`) and work subphases (`read/search/edit/test/unknown`).

`loop report` now includes `lane_runtime` summaries per round with lane statuses and timing/cost telemetry:

- `lane_id`: lane identifier (`__serial__` for serial worker runs)
- `backend`: backend that executed the lane (`codex`/`claude`/`opencode`)
- `status`: lane status from state/runtime (`completed`, `blocked`, `failed`, etc.)
- `duration_ms`: end-to-end lane execution latency
- Optional lane review fields: `review_decision`, `review_status`, `review_backend`, `review_duration_ms`, `review_blocking_issues`
- Optional usage/cost fields: `input_tokens`, `output_tokens`, `total_tokens`, `cost_cents`

Cost telemetry is deterministic and estimate-only:

- `codex` and `claude`: computed from token counts and fixed per-backend rates
- `opencode` (non-billed local backend): always `cost_cents=0`

### Optimization

| Symptom | Fix |
|---------|-----|
| Slow startup | `--max-session-rounds N`, pre-index with `loop index` |
| Slow work phase | Narrow `in_scope`, sharpen `acceptance_criteria`, split into lanes |
| High retry count | Improve criteria clarity, add project facts, tune templates |

### Backend Choice

| Backend | Best for |
|---------|----------|
| `codex` | Fast, good for boilerplate |
| `claude` | Strong reasoning, complex refactors |
| `opencode` | Local, no API costs |

</details>

<details>
<summary><strong>Troubleshooting</strong></summary>

| Problem | Fix |
|---------|-----|
| Backend not found | Ensure CLI is in PATH, or use `--dispatch-backend native` |
| Timeouts | Increase `--dispatch-timeout` or `--artifact-timeout` |
| Not responding | Use `loop health`, add `--require-heartbeat` |
| State stuck | Inspect `state.json`, use `--reset` |
| Permission errors | Ensure `.loop/` is writable |

</details>

<details>
<summary><strong>Development</strong></summary>

```bash
git clone <repo-url> && cd <repo-dir> && uv sync
uv run --group dev pytest
uv run python -m loop_kit init
```

CI runs on push/PR: tests, coverage, ruff, optional mypy.

</details>

## License

MIT
