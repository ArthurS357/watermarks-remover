"""Behaviour tests for start-watermarks-server.ps1, driven from Python.

Deliberately not Pester: the repo pins its dev tooling in requirements-dev.txt
and adding a PowerShell test framework would put an unpinned dependency in the
loop. `subprocess.run` against the real script exercises the same code paths.

Every test runs against a **free port**, never the default 8765. The script's
-Mode stop falls back to reading its pid file when no listener is found, so a
test bound to the default port could find, and kill, a developer's running
server. The port-scoped pid file (server.<port>.pid) is what keeps that
impossible; test_stop_on_custom_port_does_not_touch_the_default_pid_file
guards the guard.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "start-watermarks-server.ps1"

# pwsh (7+) where available, Windows PowerShell otherwise. CI's ubuntu/macos
# runners have neither unless pwsh is installed, hence the skip.
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")

pytestmark = [
    pytest.mark.skipif(POWERSHELL is None, reason="no pwsh/powershell on PATH"),
    pytest.mark.skipif(
        sys.platform != "win32",
        reason="the launcher uses Get-NetTCPConnection and Windows process APIs",
    ),
    pytest.mark.skipif(not SCRIPT.is_file(), reason="launcher script not present"),
]


def _free_port() -> int:
    """A port nothing is listening on, so the launcher reports it offline."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_launcher(*args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
        check=False,
    )


class _FakeServiceHandler(BaseHTTPRequestHandler):
    """Answers /health and /readyz the way the real service does."""

    readyz_status = "ok"

    def do_GET(self) -> None:
        if self.path == "/health":
            body = {"ok": True, "version": "test-1.2.3"}
        elif self.path == "/readyz":
            body = {
                "ok": True,
                "status": self.readyz_status,
                "service": {"name": "watermarks-remover", "version": "test-1.2.3"},
                "capabilities": ["unicode_invisible"],
                "tools": {
                    "c2patool": {"available": self.readyz_status == "ok"},
                    "exiftool": {"available": True},
                    "qpdf": {"available": True},
                },
            }
        else:
            self.send_error(404)
            return
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def fake_service():
    """Start a stand-in service on a free port; yields (port, set_status)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeServiceHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()

    def set_status(value: str) -> None:
        _FakeServiceHandler.readyz_status = value

    set_status("ok")
    try:
        yield srv.server_address[1], set_status
    finally:
        set_status("ok")
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


def test_status_reports_offline_and_exits_1_when_nothing_listens():
    r = run_launcher("-Mode", "status", "-Port", str(_free_port()))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "offline" in r.stdout
    # The message has to name the fix, not just the failure.
    assert "watermarks-server --wait" in r.stdout


def test_status_reports_online_against_a_healthy_service(fake_service):
    port, _ = fake_service
    r = run_launcher("-Mode", "status", "-Port", str(port))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "online" in r.stdout
    assert "degraded" not in r.stdout
    assert "test-1.2.3" in r.stdout, "the version from /health should be surfaced"


def test_status_reports_degraded_and_names_the_missing_tool(fake_service):
    """Degraded is reachable, so it must still exit 0 -- it is advisory."""
    port, set_status = fake_service
    set_status("degraded")
    r = run_launcher("-Mode", "status", "-Port", str(port))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "degraded" in r.stdout
    assert "c2patool" in r.stdout, "the operator needs to know which tool is missing"
    assert "exiftool" not in r.stdout, "an available tool must not be listed as missing"


# --------------------------------------------------------------------------
# stop
# --------------------------------------------------------------------------


def test_stop_is_idempotent_when_nothing_is_running():
    r = run_launcher("-Mode", "stop", "-Port", str(_free_port()))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Nada para encerrar" in r.stdout


def test_stop_on_custom_port_does_not_touch_the_default_pid_file():
    """The pid file is port-scoped precisely so this cannot kill a real server."""
    default_pid_file = ROOT / "server.pid"
    sentinel = "424242"
    existed = default_pid_file.exists()
    original = default_pid_file.read_text(encoding="utf-8") if existed else None
    default_pid_file.write_text(sentinel, encoding="utf-8")
    try:
        r = run_launcher("-Mode", "stop", "-Port", str(_free_port()))
        assert r.returncode == 0, r.stdout + r.stderr
        assert default_pid_file.exists(), "stop on another port deleted the default pid file"
        assert default_pid_file.read_text(encoding="utf-8").strip() == sentinel
    finally:
        if original is None:
            default_pid_file.unlink(missing_ok=True)
        else:
            default_pid_file.write_text(original, encoding="utf-8")
    assert existed or not default_pid_file.exists()


# --------------------------------------------------------------------------
# wait
# --------------------------------------------------------------------------


def test_wait_times_out_and_exits_1_when_nothing_ever_answers():
    r = run_launcher("-Mode", "wait", "-Port", str(_free_port()), "-TimeoutSeconds", "2")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "nao respondeu" in r.stdout


def test_wait_succeeds_immediately_against_a_healthy_service(fake_service):
    port, _ = fake_service
    r = run_launcher("-Mode", "wait", "-Port", str(port), "-TimeoutSeconds", "10")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no ar" in r.stdout
    assert "test-1.2.3" in r.stdout


def _dead_pid() -> int:
    """PID of a process that has certainly exited."""
    with subprocess.Popen(
        [str(POWERSHELL), "-NoProfile", "-Command", "exit 0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as proc:
        proc.wait(timeout=60)
        return proc.pid


def test_wait_fails_fast_when_the_watched_process_is_already_dead():
    """-WatchPid naming a PID that is already gone: fail now, not at the timeout."""
    port = _free_port()
    started = time.monotonic()
    r = run_launcher(
        "-Mode",
        "wait",
        "-Port",
        str(port),
        "-TimeoutSeconds",
        "60",
        "-WatchPid",
        str(_dead_pid()),
        timeout=45,  # under the 60s budget: reaching it at all means the guard failed
    )
    elapsed = time.monotonic() - started
    assert r.returncode == 1, r.stdout + r.stderr
    assert "encerrou antes de responder" in r.stdout
    assert "nao respondeu" not in r.stdout, "reported a timeout instead of the real cause"
    assert elapsed < 30, f"took {elapsed:.1f}s of a 60s budget - the guard did not fire"


def test_wait_fails_fast_when_the_watched_process_dies_during_the_wait():
    """The scenario the guard actually exists for.

    The window is alive when -Mode wait starts polling and dies a few seconds
    later -- exactly what happens when python is missing, server.py is absent,
    the port is taken, or the insecure-bind refusal exits 2. Without the
    HasExited check inside Wait-ForService this burns the whole 60s budget.
    """
    port = _free_port()
    with subprocess.Popen(
        [str(POWERSHELL), "-NoProfile", "-Command", "Start-Sleep -Seconds 4"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as doomed:
        assert doomed.poll() is None, "the watched process must still be alive at spawn time"
        started = time.monotonic()
        try:
            r = run_launcher(
                "-Mode",
                "wait",
                "-Port",
                str(port),
                "-TimeoutSeconds",
                "60",
                "-WatchPid",
                str(doomed.pid),
                timeout=45,
            )
        finally:
            doomed.kill()
    elapsed = time.monotonic() - started

    assert r.returncode == 1, r.stdout + r.stderr
    assert "encerrou antes de responder" in r.stdout
    assert "nao respondeu" not in r.stdout, "reported a timeout instead of the real cause"
    assert elapsed < 30, f"took {elapsed:.1f}s of a 60s budget - the guard did not fire"


def test_wait_ignores_a_dead_watched_process_if_the_service_did_come_up(fake_service):
    """Liveness of the window loses to an actually-answering service."""
    port, _ = fake_service
    r = run_launcher(
        "-Mode", "wait", "-Port", str(port), "-TimeoutSeconds", "10", "-WatchPid", str(_dead_pid())
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no ar" in r.stdout


# --------------------------------------------------------------------------
# parameter contract
# --------------------------------------------------------------------------


def test_unknown_mode_is_rejected():
    r = run_launcher("-Mode", "definitely-not-a-mode", "-Port", str(_free_port()))
    assert r.returncode != 0
    assert "definitely-not-a-mode" in (r.stdout + r.stderr)


def test_out_of_range_port_is_rejected():
    r = run_launcher("-Mode", "status", "-Port", "70000")
    assert r.returncode != 0
