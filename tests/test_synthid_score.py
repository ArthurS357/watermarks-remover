"""Tests for the optional reverse-SynthID scorer adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "service" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import image_meta
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
