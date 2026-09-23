"""Starts coverage.py in subprocesses spawned during `make test-cov-subprocess`.

Tests exercise several CLI entry points (clean_text.py, inspect_file.py,
score_synthid.py, ...) via `subprocess.run([sys.executable, ...])`, which
coverage.py cannot see without this hook -- see .coveragerc and the Makefile
target. Since `python <script in this dir>` puts this directory first on
sys.path, Python's site module imports this module automatically.

No-op unless COVERAGE_PROCESS_START is set (opt-in only) and the coverage
package is installed -- neither is true in production or in a plain `make test`.
"""

from __future__ import annotations

import os

if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage
    except ImportError:
        pass
    else:
        coverage.process_startup()
