# AGENTS.md

## Workflow

- **Trivial tasks** (typos, one-line fixes): do them directly
- **Non-trivial tasks**: act as the **PM/orchestrator**. Create a task card and run `loop run --auto-dispatch` to delegate to the worker backend. **Do not write the code yourself.**

## Source Structure

- `orchestrator.py` is a thin facade that re-exports all public symbols from focused sub-modules (T-722 modularization).
- Follow the `_SECTION_OWNERSHIP_MAP` module boundaries when adding new code.
- Module layout:
  - `_core.py` — internal full implementation (do not import directly outside the package)
  - `exceptions.py` — exception hierarchy (leaf module, no internal imports)
  - `paths.py` — constants, `LoopPaths`, path helpers (leaf module)
  - `state.py` — state machine, transitions, state I/O (imports from `exceptions`, `paths`)
  - `file_bus.py` — prepare/archive/wait bus files, file locking
  - `dispatch.py` — backend registration, agent commands, auto-dispatch, dispatch handler tables
  - `session.py` — `SessionManager`, resume policy
  - `config.py` — `RunConfig`, config loading and validation
  - `prompts.py` — task packet rendering, worker/reviewer prompt templates
  - `knowledge.py` — knowledge retrieval, FTS, patterns
  - `git_helpers.py` — git operations, diff, worktree management
- `_SECTION_OWNERSHIP_MAP` and `_SECTION_MODULE_PATHS` in `orchestrator.py` map section names to module file paths.
- Wrappers: `cli.py` (imports `main` from `_core` directly), `__main__.py` (`python -m loop_kit`), `__init__.py` (version).
- Tests in `tests/test_orchestrator.py`.

## Coding Constraints

- Python 3.11+ (use `X | Y` union syntax, not `Union`).
- Internal functions are `_`-prefixed — do not rename them.
- All file I/O: `Path` objects, UTF-8 encoding.
- JSON output: `ensure_ascii=False, indent=2`.
- State contract: `state.json` is the single source of truth between outer and inner processes.
- Backend registry: use `register_backend()` to add backends, do not modify dispatch directly.
- Windows: prompts piped via stdin (8191 char CLI limit), use `os.name == "nt"` for platform checks.
- File locking: `_LoopLock` uses `msvcrt` (Windows) or `fcntl` (Unix).

## Testing

- `uv run --group dev pytest` to run all tests.
- Use `tmp_path` fixture for filesystem tests.
- Mock `subprocess.run`/`subprocess.Popen` for dispatch tests.
- `_configure_loop_paths` mutates module globals — always pair with `monkeypatch.setattr`.

## Validation Commands

```bash
uv run python -m py_compile src/loop_kit/orchestrator.py
uv run python -c "from loop_kit.orchestrator import *"
uv run --group dev pytest
```
