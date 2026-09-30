"""Shared helper for the stylometry tests (``tests/`` is on sys.path under pytest's rootdir)."""

from __future__ import annotations

import importlib
import json


def in_process(target, args, timeout):
    """Stand-in for ``isolate.call``: same JSON round trip, same target, no child process.

    The real worker is exercised by the tests that ask for the ``real_worker`` fixture (and by
    test_stylometry_isolate.py). Everything else runs the worker's code here so that it is fast
    and visible to coverage, which does not follow into a spawned process.
    """
    from stylometry import isolate  # after the tests put tools/ on sys.path

    module, _, name = target.partition(":")
    function = getattr(importlib.import_module(module), name)
    try:
        return json.loads(json.dumps(function(*json.loads(json.dumps(args)))))
    except Exception as exc:  # the real worker turns any exception into an "error" reply
        raise isolate.IsolatedError(f"{type(exc).__name__}: {exc}"[:200]) from exc
