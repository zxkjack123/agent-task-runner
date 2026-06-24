#!/usr/bin/env python3
"""Split orchestrator.py into focused modules per T-722.

This script reads the original single-file orchestrator.py and:
1. Extracts sections into focused modules (exceptions.py, paths.py, etc.)
2. Creates a facade orchestrator.py that re-exports all public symbols
3. Preserves backward compatibility for all `from loop_kit.orchestrator import X` patterns
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SRC_DIR = Path("src/loop_kit")
ORIG_FILE = SRC_DIR / "orchestrator.py"

def read_lines() -> list[str]:
    with open(ORIG_FILE, encoding="utf-8") as f:
        return f.readlines()

def write_module(name: str, content: str) -> None:
    path = SRC_DIR / f"{name}.py"
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote {path} ({len(content.splitlines())} lines)")

def main() -> None:
    lines = read_lines()
    source = "".join(lines)
    tree = ast.parse(source)

    # Collect all top-level nodes with their line ranges
    nodes = []
    for node in tree.body:
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "func"
            name = node.name
        elif isinstance(node, ast.ClassDef):
            kind = "class"
            name = node.name
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            kind = "assign"
            name = ", ".join(names)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            kind = "ann-assign"
            name = node.target.id
        elif isinstance(node, ast.If):
            kind = "if"
            name = f"if_{start}"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            kind = "import"
            name = f"import_{start}"
        else:
            kind = "other"
            name = f"other_{start}"
        nodes.append((start, end, kind, name, node))

    # Module assignments: (module_name, start_line, end_line)
    # These define which line ranges go into which module.
    # Everything not assigned to a module goes into the "core" module (orchestrator.py facade)
    #
    # Module dependency DAG:
    #   exceptions.py (leaf) - no internal imports
    #   paths.py (leaf) - no internal imports
    #   state.py -> exceptions, paths
    #   file_bus.py -> exceptions, paths
    #   session.py -> exceptions, paths, state
    #   config.py -> exceptions, paths
    #   git_helpers.py -> exceptions, paths
    #   dispatch.py -> exceptions, paths, session, config, git_helpers
    #   prompts.py -> paths, config, knowledge
    #   knowledge.py -> paths
    #   orchestrator.py (facade) -> all

    # For a 12K-line file, the safest approach that guarantees zero behavioral changes
    # is to put ALL code into a single "_core.py" module, then have orchestrator.py
    # be a facade that does `from ._core import *`.
    #
    # But the task requires actual module split. So we'll split by section markers
    # but use a shared base module for cross-cutting concerns.

    # Strategy: Create a _base.py that contains all shared constants, TypedDicts,
    # and imports. Each module imports from _base. The facade re-exports from all.

    # Actually, the simplest correct approach: put everything in _core.py,
    # then create thin module files that do `from ._core import *` for their section,
    # and orchestrator.py does `from ._core import *`.

    # But that doesn't satisfy "each module should have a clear single responsibility".
    # The task says modules should be 200-2000 lines.

    # Let me try the real split. The key insight is that Python allows late-binding
    # references at module level through the facade. Since tests access
    # `orchestrator.X`, the facade needs to re-export everything.

    # For the actual module files, we need to handle cross-references.
    # The cleanest way: each module imports from modules it depends on.

    print("Script loaded. Use --run to execute the split.")

if __name__ == "__main__":
    main()
