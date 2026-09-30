"""Tests for tools/stylometry/isolate.py (a killable worker process, JSON over a pipe)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stylometry import isolate


@pytest.fixture(autouse=True)
def fresh_worker():
    isolate._worker.close()
    yield
    isolate._worker.close()


def test_calls_a_function_in_another_process():
    assert isolate.call("math:sqrt", [16], 30) == 4.0
    assert isolate.call("os:getpid", [], 30) != os.getpid()


def test_one_worker_serves_many_calls():
    first = isolate.call("os:getpid", [], 30)
    assert isolate.call("os:getpid", [], 30) == first


def test_a_raising_function_comes_back_as_isolated_error_and_the_worker_survives():
    pid = isolate.call("os:getpid", [], 30)
    with pytest.raises(isolate.IsolatedError, match="ValueError"):
        isolate.call("math:sqrt", [-1], 30)
    assert isolate.call("os:getpid", [], 30) == pid


@pytest.mark.parametrize(
    ("target", "args", "expected"),
    [
        ("no_such_module_xyz:f", [], "ModuleNotFoundError"),
        ("math:no_such_function", [], "AttributeError"),
        ("builtins:object", [], "TypeError"),  # the result is not JSON-serializable
    ],
    ids=["module", "function", "result-not-json"],
)
def test_bad_targets_and_unserializable_results_are_errors_not_crashes(target, args, expected):
    with pytest.raises(isolate.IsolatedError, match=expected):
        isolate.call(target, args, 30)
    assert isolate.call("math:sqrt", [9], 30) == 3.0


def test_a_timeout_kills_the_worker_and_the_next_call_gets_a_fresh_one():
    pid = isolate.call("os:getpid", [], 30)
    start = time.perf_counter()
    with pytest.raises(TimeoutError, match="excedeu"):
        isolate.call("time:sleep", [60], 0.5)
    assert time.perf_counter() - start < 10
    assert isolate._worker._process is None  # killed and forgotten
    assert isolate.call("os:getpid", [], 30) != pid


def test_a_worker_that_dies_is_reported_and_replaced():
    with pytest.raises(isolate.IsolatedError, match="morreu"):
        isolate.call("os:_exit", [3], 30)
    assert isolate.call("math:sqrt", [25], 30) == 5.0


def test_close_is_idempotent():
    isolate._worker.close()
    isolate._worker.close()
    assert isolate.call("math:sqrt", [4], 30) == 2.0


class FakeConnection:
    """Feeds ``_serve`` a scripted list of requests, then EOF, and records the replies."""

    def __init__(self, requests):
        self.requests = [r.encode() if isinstance(r, str) else r for r in requests]
        self.replies = []

    def recv_bytes(self):
        if not self.requests:
            raise EOFError
        return self.requests.pop(0)

    def send_bytes(self, data):
        self.replies.append(json.loads(data))


def test_serve_loop_replies_per_request_and_stops_at_eof():
    # _serve runs in the child, where coverage cannot see it: drive it in-process.
    conn = FakeConnection(
        [
            json.dumps(["math:sqrt", [49]]),
            json.dumps(["math:sqrt", [-1]]),
            json.dumps(["builtins:object", []]),
        ]
    )
    isolate._serve(conn)
    assert conn.replies[0] == ["ok", 7.0]
    assert conn.replies[1][0] == "error"
    assert "ValueError" in conn.replies[1][1]
    assert conn.replies[2][0] == "error"
    assert len(conn.replies) == 3


def test_serve_loop_ends_when_the_pipe_breaks():
    class Broken:
        def recv_bytes(self):
            raise OSError("pipe closed")

    isolate._serve(Broken())  # returns instead of raising


def test_results_are_json_not_pickle():
    # A tuple comes back as a list: proof that the reply was decoded from JSON.
    assert isolate.call("posixpath:split", ["a/b"], 30) == ["a", "b"]
