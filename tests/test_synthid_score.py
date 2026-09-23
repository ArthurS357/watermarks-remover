"""Tests for the optional reverse-SynthID scorer adapter."""

from __future__ import annotations

import http.client
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "service" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import image_meta
import synthid_score_server
from image_meta import ImageInspectReport, run_synthid_score

SCORE_SCRIPT = SCRIPTS / "score_synthid.py"


def test_score_synthid_cli_unavailable_without_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("REVERSE_SYNTHID_DIR", raising=False)
    dummy = tmp_path / "img.png"
    dummy.write_bytes(b"not really an image")

    r = subprocess.run(
        [sys.executable, str(SCORE_SCRIPT), str(dummy)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert r.returncode == 3
    assert "REVERSE_SYNTHID_DIR" in (r.stderr or "")


def test_run_synthid_score_unconfigured_returns_none(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("REVERSE_SYNTHID_DIR", raising=False)
    assert run_synthid_score(Path("x.png")) is None


def test_run_synthid_score_unavailable_returns_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=3, stdout="", stderr="unavailable")

    monkeypatch.setattr(image_meta.subprocess, "run", fake_run)
    result = run_synthid_score(Path("x.png"), upstream_dir=str(tmp_path / "upstream"))

    assert result is not None
    assert result.get("available") is False
    assert "unavailable" in result.get("error", "")


def test_run_synthid_score_prefers_checkout_venv_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upstream = tmp_path / "upstream"
    venv_python = upstream / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n")
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(image_meta.subprocess, "run", fake_run)
    run_synthid_score(Path("img.png"), upstream_dir=str(upstream))

    assert captured["cmd"][0] == str(venv_python)


def test_run_synthid_score_falls_back_to_sys_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    upstream = tmp_path / "upstream"  # no .venv present
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(image_meta.subprocess, "run", fake_run)
    run_synthid_score(Path("img.png"), upstream_dir=str(upstream))

    assert captured["cmd"][0] == sys.executable


def test_run_synthid_score_parses_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    payload = {
        "available": True,
        "is_watermarked": True,
        "confidence": 0.91,
        "phase_match": 0.65,
    }
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(image_meta.subprocess, "run", fake_run)
    result = run_synthid_score(Path("img.png"), upstream_dir=str(tmp_path / "upstream"))

    assert result == payload
    assert "--json" in captured["cmd"]
    assert "--upstream-dir" in captured["cmd"]
    assert str(tmp_path / "upstream") in captured["cmd"]


def test_run_synthid_score_runtime_error_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(image_meta.subprocess, "run", fake_run)
    result = run_synthid_score(Path("img.png"), upstream_dir=str(tmp_path / "upstream"))

    assert result is not None
    assert result.get("available") is False
    assert "boom" in result.get("error", "")


def test_inspect_image_cli_prints_synthid_score(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "inspect_image_cli", str(SCRIPTS / "inspect_image.py")
    )
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    report = ImageInspectReport(
        path="shot.png",
        format="png",
        has_c2pa=False,
        has_ai_metadata=False,
        synthid={
            "available": True,
            "is_watermarked": True,
            "confidence": 0.91,
        },
    )
    img = tmp_path / "shot.png"
    img.write_bytes(b"not really an image")
    monkeypatch.setattr(cli, "inspect_image", lambda path, synthid_dir=None: report)
    monkeypatch.setattr(sys, "argv", ["inspect_image.py", str(img)])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "SynthID score: confidence 0.910 (watermarked: yes)" in out


def test_inspect_report_to_dict_includes_synthid():
    report = ImageInspectReport(
        path="x.png",
        format="png",
        has_c2pa=False,
        has_ai_metadata=False,
        synthid={"available": True, "confidence": 0.8},
    )
    assert report.to_dict()["synthid"]["confidence"] == 0.8

    empty = ImageInspectReport(
        path="x.png",
        format="png",
        has_c2pa=False,
        has_ai_metadata=False,
    )
    assert empty.to_dict()["synthid"] is None


def test_summarize_stderr_returns_only_first_line(capsys):
    # A multi-line traceback (e.g. containing a container-internal path)
    # must not reach the HTTP client wholesale; only the first line does,
    # and the full text still goes to the server's own log.
    stderr = 'RuntimeError: model load failed\n  File "/opt/reverse-synthid/score.py", line 42\n'
    result = image_meta._summarize_stderr(stderr)
    assert result == "RuntimeError: model load failed"
    assert "/opt/reverse-synthid/score.py" not in result
    assert "/opt/reverse-synthid/score.py" in capsys.readouterr().err


def test_summarize_stderr_caps_length():
    result = image_meta._summarize_stderr("x" * 5000)
    assert len(result) == 300


def test_summarize_stderr_uses_fallback_when_empty():
    assert image_meta._summarize_stderr("", fallback="no output") == "no output"
    assert image_meta._summarize_stderr(None, fallback="no output") == "no output"


def test_synthid_score_http_read_error_omits_full_path(tmp_path):
    missing = tmp_path / "deeply" / "nested" / "server-temp-dir" / "shot.png"
    result = image_meta._synthid_score_http(missing, "http://127.0.0.1:8766", "", 5.0)
    assert result["available"] is False
    assert "shot.png" in result["error"]
    assert str(tmp_path) not in result["error"]
    assert "server-temp-dir" not in result["error"]


def _serve(handler: type[http.server.BaseHTTPRequestHandler]) -> http.server.ThreadingHTTPServer:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_synthid_score_http_refuses_redirect_and_never_sends_key(tmp_path):
    """urllib re-sends Authorization on 301/302/303; the key must not follow."""
    captured: dict = {}

    class Collector(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            captured["auth"] = self.headers.get("Authorization")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"available": true}')

        def log_message(self, *_args):
            pass

    collector = _serve(Collector)

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{collector.server_address[1]}/x")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    redirector = _serve(Redirector)
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    try:
        result = image_meta._synthid_score_http(
            img, f"http://127.0.0.1:{redirector.server_address[1]}", "sekret", 5.0
        )
    finally:
        for srv in (collector, redirector):
            srv.shutdown()
            srv.server_close()
    assert captured == {}, "redirect target received the scorer request (key leak)"
    assert result["available"] is False


@pytest.fixture
def sidecar(monkeypatch):
    monkeypatch.setattr(synthid_score_server, "API_KEY", "")
    srv = _serve(synthid_score_server.Handler)
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    yield conn
    conn.close()
    srv.shutdown()
    srv.server_close()


def _status(conn: http.client.HTTPConnection, headers: dict[str, str]) -> int:
    conn.request("GET", "/health", headers=headers)
    resp = conn.getresponse()
    resp.read()
    return resp.status


def test_sidecar_auth_gate(sidecar, monkeypatch):
    monkeypatch.setattr(synthid_score_server, "API_KEY", "k")
    assert _status(sidecar, {}) == 401
    assert _status(sidecar, {"Authorization": "Bearer wrong"}) == 401
    # Non-ASCII used to raise TypeError in compare_digest and drop the connection.
    assert _status(sidecar, {"Authorization": "Bearer \xe9"}) == 401
    assert _status(sidecar, {"Authorization": "Bearer k"}) == 200


def test_sidecar_non_decimal_content_length_is_400(sidecar):
    sidecar.putrequest("POST", "/score")
    sidecar.putheader("Content-Length", "\xb2")
    sidecar.endheaders(b"{}")
    resp = sidecar.getresponse()
    resp.read()
    assert resp.status == 400


def test_sidecar_refuses_a_non_ascii_api_key(monkeypatch, capsys):
    monkeypatch.setattr(synthid_score_server, "API_KEY", "\xe9")
    monkeypatch.setattr(sys, "argv", ["synthid_score_server.py"])

    def _must_not_bind(*_args, **_kwargs):
        raise AssertionError("main() bound a socket despite a non-ASCII API key")

    monkeypatch.setattr(synthid_score_server, "ThreadingHTTPServer", _must_not_bind)
    assert synthid_score_server.main() == 2
    assert "ASCII" in capsys.readouterr().err


def test_sidecar_refuses_insecure_bind_with_no_api_key():
    assert synthid_score_server._refuses_insecure_bind("0.0.0.0", "", False) is True  # noqa: S104


def test_sidecar_allows_insecure_bind_with_explicit_opt_out():
    assert synthid_score_server._refuses_insecure_bind("0.0.0.0", "", True) is False  # noqa: S104


def test_sidecar_allows_non_loopback_bind_with_api_key():
    assert (
        synthid_score_server._refuses_insecure_bind("0.0.0.0", "sekret", False) is False  # noqa: S104
    )


def test_sidecar_allows_loopback_bind_with_no_api_key():
    assert synthid_score_server._refuses_insecure_bind("127.0.0.1", "", False) is False


def test_sidecar_main_refuses_insecure_bind_before_starting_server(monkeypatch, capsys):
    monkeypatch.setattr(synthid_score_server, "API_KEY", "")
    monkeypatch.delenv("WATERMARKS_SYNTHID_SERVER_ALLOW_INSECURE_BIND", raising=False)
    monkeypatch.setattr(sys, "argv", ["synthid_score_server.py", "--host", "0.0.0.0"])  # noqa: S104
    assert synthid_score_server.main() == 2
    assert "refusing to bind" in capsys.readouterr().err


def test_sidecar_main_allows_insecure_bind_via_env_var(monkeypatch):
    monkeypatch.setattr(synthid_score_server, "API_KEY", "")
    monkeypatch.setenv("WATERMARKS_SYNTHID_SERVER_ALLOW_INSECURE_BIND", "1")
    monkeypatch.setattr(sys, "argv", ["synthid_score_server.py", "--host", "0.0.0.0"])  # noqa: S104

    class _FakeServer:
        def __init__(self, *_args, **_kwargs):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

    monkeypatch.setattr(synthid_score_server, "ThreadingHTTPServer", _FakeServer)
    assert synthid_score_server.main() == 0


def test_sidecar_malformed_size_env_falls_back_instead_of_crashing_import():
    # The sidecar image ships without common.py, so it cannot use env_int.
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            "import synthid_score_server as s; print(s.MAX_INPUT_BYTES)",
        ],
        cwd=SCRIPTS,
        env={**os.environ, "WATERMARKS_MAX_INPUT_BYTES": "256MB"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(256 << 20)
    assert "WATERMARKS_MAX_INPUT_BYTES" in r.stderr
