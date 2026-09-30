"""Run a function of this package in a child process that can be killed.

Why a process: tree-sitter's TSX scanner can spin forever on some malformed input while holding the
GIL, and pypdf / python-docx can allocate gigabytes on a crafted file. A thread can stop neither; a
process can. One long-lived worker serves many calls (spawning per file would cost ~0.3 s on
Windows); it is killed on a timeout or when it dies and is respawned by the next call.

Arguments and results travel as JSON over a pipe, never as pickle: the child has just parsed
hostile data, so the parent must not unpickle whatever it sends back. ``target`` is a
``"module:function"`` string chosen by this package's own code, never derived from file content.
Not thread-safe: one call at a time, which is how the CLI uses it.
"""

from __future__ import annotations

import atexit
import importlib
import json
import multiprocessing
from typing import Any


class IsolatedError(RuntimeError):
    """The function raised in the worker, or the worker died."""


def _serve(conn: Any) -> None:
    """Worker loop: receive ``[target, args]``, reply ``["ok", result]`` or ``["error", text]``."""
    while True:
        try:
            target, args = json.loads(conn.recv_bytes())
        except (EOFError, OSError):
            return
        module, _, name = target.partition(":")
        try:
            function = getattr(importlib.import_module(module), name)
            reply = json.dumps(["ok", function(*args)])
        except Exception as exc:  # anything the function raises goes back as text
            reply = json.dumps(["error", f"{type(exc).__name__}: {exc}"[:200]])
        conn.send_bytes(reply.encode())


class Worker:
    def __init__(self) -> None:
        self._process: Any = None
        self._conn: Any = None

    def _connection(self) -> Any:
        if self._process is None or not self._process.is_alive():
            ctx = multiprocessing.get_context("spawn")
            parent, child = ctx.Pipe()
            self._process = ctx.Process(target=_serve, args=(child,), daemon=True)
            self._process.start()
            child.close()
            self._conn = parent
        return self._conn

    def close(self) -> None:
        if self._process is not None:
            self._process.kill()  # kill, not terminate: a GIL-holding loop ignores the gentler one
            self._process.join(2)
        if self._conn is not None:
            self._conn.close()
        self._process = self._conn = None

    def call(self, target: str, args: list[Any], timeout: float) -> Any:
        conn = self._connection()
        try:
            conn.send_bytes(json.dumps([target, args]).encode())
            reply = conn.recv_bytes() if conn.poll(timeout) else None
        except (EOFError, OSError) as exc:
            self.close()
            raise IsolatedError(f"o processo de análise morreu ({type(exc).__name__})") from exc
        if reply is None:  # raised outside the try: TimeoutError is an OSError
            self.close()
            raise TimeoutError(f"excedeu {timeout:g} s")
        kind, value = json.loads(reply)
        if kind == "error":
            raise IsolatedError(value)
        return value


_worker = Worker()
atexit.register(_worker.close)


def call(target: str, args: list[Any], timeout: float) -> Any:
    """``target(*args)`` in the shared worker. Raises ``TimeoutError`` (worker killed) or
    ``IsolatedError`` (the function raised, or the worker died)."""
    return _worker.call(target, args, timeout)
