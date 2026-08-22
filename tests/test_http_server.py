"""Tests for the HTTP service entrypoint (server.py)."""

from __future__ import annotations

import base64
import http.client
import io
import json
import socket
import struct
import sys
import threading
import time
import zipfile
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "service" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import container_meta
import server


def _png_chunk(ctype: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(ctype)
    crc = zlib.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(">I", crc)


def _watermarked_png() -> bytes:
    """1x1 PNG whose tEXt chunk carries C2PA markers (structure only)."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00")
    text = b"Comment\x00c2pa test contentcredentials"
    return (
        sig
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"tEXt", text)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _post(conn: http.client.HTTPConnection, path: str, payload: dict) -> tuple[int, dict]:
    conn.request(
        "POST",
        path,
        body=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, json.loads(data) if data else {}


def _get(conn: http.client.HTTPConnection, path: str) -> tuple[int, dict]:
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, json.loads(data) if data else {}


@pytest.fixture(scope="module")
def conn() -> http.client.HTTPConnection:
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    yield c
    c.close()
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def test_health(conn):
    status, body = _get(conn, "/health")
    assert status == 200
    assert body["ok"] is True
    assert "version" in body


def test_capabilities(conn):
    status, body = _get(conn, "/capabilities")
    assert status == 200
    assert set(body["tools"]) == {"c2patool", "exiftool", "qpdf"}
    assert "pixel_backends" in body
    assert "scorers" in body
    assert "harnesses" in body


def test_openapi_spec_covers_all_endpoints(conn):
    status, body = _get(conn, "/openapi.json")
    assert status == 200
    assert body["openapi"] == "3.0.3"
    assert body["info"]["title"] == "watermarks-remover service"
    expected = {
        "/health": {"get"},
        "/capabilities": {"get"},
        "/openapi.json": {"get"},
        "/inspect": {"post"},
        "/clean": {"post"},
    }
    for path, methods in expected.items():
        assert path in body["paths"]
        for method in methods:
            assert method in body["paths"][path]
            assert "responses" in body["paths"][path][method]


def test_openapi_spec_describes_request_bodies(conn):
    status, body = _get(conn, "/openapi.json")
    assert status == 200
    clean = body["paths"]["/clean"]["post"]
    assert clean["requestBody"]["required"] is True
    schema = clean["requestBody"]["content"]["application/json"]["schema"]
    assert "file" in schema["properties"]
    assert "options" in schema["properties"]
    inspect = body["paths"]["/inspect"]["post"]
    assert "file" in inspect["requestBody"]["content"]["application/json"]["schema"]["properties"]


def test_openapi_spec_reflects_auth(conn, monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "sekret")
    conn.request("GET", "/openapi.json", headers={"Authorization": "Bearer sekret"})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    assert resp.status == 200
    assert "bearerAuth" in body["components"]["securitySchemes"]
    assert body["security"] == [{"bearerAuth": []}]


def test_inspect_text_finds_watermark(conn):
    data = "Hello\u200bWorld\u00ad!".encode("utf-8")
    status, body = _post(conn, "/inspect", {"file": _b64(data), "name": "note.txt"})
    assert status == 200
    assert body["kind"] == "text"
    assert body["suspicious"] is True
    assert body["report"]["suspicious_total"] == 2


def test_clean_text_roundtrip(conn):
    data = "Hello\u200bWorld\u00ad!".encode("utf-8")
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "note.txt"})
    assert status == 200
    assert body["kind"] == "text"
    cleaned = base64.b64decode(body["cleaned"]).decode("utf-8")
    assert cleaned == "HelloWorld!"
    assert body["report"]["stats"]["removed_count"] == 2


def test_clean_png_strips_metadata(conn):
    data = _watermarked_png()
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "shot.png"})
    assert status == 200
    assert body["kind"] == "image"
    cleaned = base64.b64decode(body["cleaned"])
    assert b"c2pa" not in cleaned.lower()
    assert body["report"]["format"] == "png"
    assert any("tEXt" in a for a in body["report"]["actions"]) or "actions" in body["report"]


def test_clean_image_reports_missing_tool_warnings(conn, monkeypatch):
    monkeypatch.setattr(server, "_tool_usable", lambda cmd: False)
    data = _watermarked_png()
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "shot.png"})
    assert status == 200
    warnings = body["report"]["warnings"]
    assert any("exiftool" in w for w in warnings)
    assert any("c2patool" in w for w in warnings)


def test_clean_pdf_reports_missing_qpdf_warning(conn, monkeypatch):
    monkeypatch.setattr(server, "_tool_usable", lambda cmd: False)
    data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "doc.pdf"})
    assert status == 200
    assert body["report"]["format"] == "pdf"
    warnings = body["report"]["warnings"]
    assert any("qpdf" in w for w in warnings)
    assert any("exiftool" in w for w in warnings)
    assert any("c2patool" in w for w in warnings)


def test_clean_reports_no_warnings_when_tools_available(conn, monkeypatch):
    monkeypatch.setattr(server, "_tool_usable", lambda cmd: True)
    data = _watermarked_png()
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "shot.png"})
    assert status == 200
    assert "warnings" not in body["report"]


def test_clean_text_has_no_warnings_key(conn):
    status, body = _post(conn, "/clean", {"file": _b64(b"hello"), "name": "note.txt"})
    assert status == 200
    assert "warnings" not in body["report"]


def test_clean_markdown_container(conn):
    data = (ROOT / "tests" / "fixtures" / "sample_ai.md").read_bytes()
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "note.md"})
    assert status == 200
    assert body["kind"] == "container"
    cleaned = base64.b64decode(body["cleaned"]).decode("utf-8")
    assert "generator: Claude" not in cleaned
    assert body["report"]["format"] == "markdown"


def test_clean_docx_with_failed_embedded_media_marks_audit_incomplete(conn, monkeypatch):
    def _raise(*_args, **_kwargs):
        raise ValueError("simulated malformed PNG")

    monkeypatch.setattr(container_meta, "strip_png", _raise)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/media/image1.png", _watermarked_png())
    data = buf.getvalue()

    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "doc.docx"})
    assert status == 200
    assert body["report"]["audit_incomplete"] is True
    assert any(a.startswith("embedded media clean failed:") for a in body["report"]["actions"])


def test_unknown_option_rejected(conn):
    status, body = _post(
        conn, "/clean", {"file": _b64(b"x"), "name": "x.txt", "options": {"nope": 1}}
    )
    assert status == 400
    assert "unknown option" in body["error"]


@pytest.mark.parametrize(
    ("key", "value", "type_name"),
    [
        ("nfkc", "false", "boolean"),
        ("aggressive_homoglyphs", 1, "boolean"),
        ("keep_non_ai_metadata", None, "boolean"),
        ("also_layer_a_text", {}, "boolean"),
        ("strip_all_metadata", [], "boolean"),
        ("remove_pixel", False, "string"),
    ],
)
def test_option_wrong_type_rejected(conn, key, value, type_name):
    status, body = _post(
        conn, "/clean", {"file": _b64(b"x"), "name": "x.txt", "options": {key: value}}
    )
    assert status == 400
    assert body["error"] == f"option '{key}' must be a {type_name}"


def test_bad_base64_rejected(conn):
    status, _body = _post(conn, "/inspect", {"file": "!!!not-base64!!!"})
    assert status == 400


def test_binary_named_as_text_rejected(conn):
    status, _body = _post(conn, "/clean", {"file": _b64(_watermarked_png()), "name": "x.txt"})
    assert status == 400


def test_clean_unknown_format_rejected(conn):
    data = b"no magic, no extension"
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "input"})
    assert status == 400
    assert "unrecognized file format" in body["error"]


def test_inspect_unknown_format_reports_kind(conn):
    data = b"no magic, no extension"
    status, body = _post(conn, "/inspect", {"file": _b64(data), "name": "input"})
    assert status == 200
    assert body["kind"] == "unknown"
    assert body["suspicious"] is False
    assert "note" in body["report"]


def test_missing_file_field_rejected(conn):
    status, _body = _post(conn, "/inspect", {"name": "x.txt"})
    assert status == 400


def test_safe_name_sanitizes_traversal():
    assert server._safe_name("../../etc/passwd") == "passwd"
    assert server._safe_name("a/b/c/notes.md") == "notes.md"
    assert server._safe_name("..\\..\\win.txt") == "win.txt"
    assert server._safe_name("..") == "input"
    assert server._safe_name(".") == "input"
    assert server._safe_name("") == "input"
    assert server._safe_name("report.docx") == "report.docx"


def test_traversal_name_does_not_escape(conn, tmp_path):
    data = "Hello\u200bWorld!".encode("utf-8")
    status, body = _post(conn, "/clean", {"file": _b64(data), "name": "../../escape.txt"})
    assert status == 200
    assert body["kind"] == "text"
    cleaned = base64.b64decode(body["cleaned"]).decode("utf-8")
    assert cleaned == "HelloWorld!"
    assert not (tmp_path / "escape.txt").exists()


def test_oversized_body_413(conn, monkeypatch):
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 64)
    data = "x" * 200
    status, _body = _post(conn, "/inspect", {"file": _b64(data.encode())})
    assert status == 413


def test_auth_required(conn, monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "sekret")
    status, _ = _post(conn, "/inspect", {"file": _b64(b"hi")})
    assert status == 401
    conn.request("GET", "/capabilities", headers={"Authorization": "Bearer sekret"})
    resp = conn.getresponse()
    assert resp.status == 200
    resp.read()


def test_health_is_never_authenticated(conn, monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "sekret")
    status, body = _get(conn, "/health")
    assert status == 200
    assert body["ok"] is True


def test_openapi_spec_marks_health_as_public(conn, monkeypatch):
    monkeypatch.setattr(server, "API_KEY", "sekret")
    conn.request("GET", "/openapi.json", headers={"Authorization": "Bearer sekret"})
    resp = conn.getresponse()
    body = json.loads(resp.read())
    assert resp.status == 200
    assert body["paths"]["/health"]["get"]["security"] == []
    assert body["security"] == [{"bearerAuth": []}]


def test_refuses_insecure_bind_with_no_api_key():
    assert server._refuses_insecure_bind("0.0.0.0", "", False) is True  # noqa: S104


def test_allows_insecure_bind_with_explicit_opt_out():
    assert server._refuses_insecure_bind("0.0.0.0", "", True) is False  # noqa: S104


def test_allows_non_loopback_bind_with_api_key():
    assert server._refuses_insecure_bind("0.0.0.0", "sekret", False) is False  # noqa: S104


def test_allows_loopback_bind_with_no_api_key():
    assert server._refuses_insecure_bind("127.0.0.1", "", False) is False


def test_main_refuses_insecure_bind_before_starting_server(monkeypatch, capsys):
    monkeypatch.setattr(server, "API_KEY", "")
    monkeypatch.delenv("WATERMARKS_SERVER_ALLOW_INSECURE_BIND", raising=False)
    monkeypatch.setattr(sys, "argv", ["server.py", "--host", "0.0.0.0"])  # noqa: S104
    assert server.main() == 2
    assert "refusing to bind" in capsys.readouterr().err


def test_main_allows_insecure_bind_via_env_var(monkeypatch):
    # compose.yaml's wr-core service sets this by default -- its actual
    # access boundary is the host port mapping, not the in-container bind.
    monkeypatch.setattr(server, "API_KEY", "")
    monkeypatch.setenv("WATERMARKS_SERVER_ALLOW_INSECURE_BIND", "1")
    monkeypatch.setattr(sys, "argv", ["server.py", "--host", "0.0.0.0"])  # noqa: S104

    class _FakeServer:
        def __init__(self, *_args, **_kwargs):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

        def shutdown(self):
            pass

    monkeypatch.setattr(server, "ThreadingHTTPServer", _FakeServer)
    assert server.main() == 0


@pytest.mark.parametrize("value", ["1", "true", "True", "YES", "on", "On"])
def test_flag_env_true_values(monkeypatch, value):
    monkeypatch.setenv("WATERMARKS_TEST_FLAG", value)
    assert server._flag_env("WATERMARKS_TEST_FLAG") is True


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "", "anything-else"])
def test_flag_env_false_values(monkeypatch, value):
    monkeypatch.setenv("WATERMARKS_TEST_FLAG", value)
    assert server._flag_env("WATERMARKS_TEST_FLAG") is False


def test_flag_env_unset_is_false(monkeypatch):
    monkeypatch.delenv("WATERMARKS_TEST_FLAG", raising=False)
    assert server._flag_env("WATERMARKS_TEST_FLAG") is False


def test_concurrency_limit_returns_503(conn, monkeypatch):
    full = threading.BoundedSemaphore(1)
    full.acquire()  # the only slot is already taken before the request arrives
    monkeypatch.setattr(server, "_REQUEST_SLOTS", full)

    status, body = _post(conn, "/inspect", {"file": _b64(b"hello")})
    assert status == 503
    assert body["ok"] is False

    full.release()
    status, _body = _post(conn, "/inspect", {"file": _b64(b"hello")})
    assert status == 200


def test_slow_client_is_dropped_after_timeout(monkeypatch):
    monkeypatch.setattr(server.Handler, "timeout", 0.2)
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        sock = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=5)
        try:
            start = time.monotonic()
            # Send nothing: a slowloris-style client that opens a connection
            # and never sends a request line should be dropped once the
            # (patched, short) per-connection timeout elapses.
            data = sock.recv(1024)
            elapsed = time.monotonic() - start
            assert data == b""
            assert elapsed < 5
        finally:
            sock.close()
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def test_404(conn):
    status, _body = _get(conn, "/nope")
    assert status == 404
    status, _body = _post(conn, "/nope", {"file": _b64(b"x")})
    assert status == 404


def test_openapi_spec_covers_batch_endpoints(conn):
    status, body = _get(conn, "/openapi.json")
    assert status == 200
    assert "/inspect/batch" in body["paths"]
    assert "post" in body["paths"]["/inspect/batch"]
    assert "/clean/batch" in body["paths"]
    assert "post" in body["paths"]["/clean/batch"]


def test_inspect_batch_mixed_results(conn):
    watermarked = ("Hello" + chr(0x200B) + "World!").encode("utf-8")
    clean = b"nothing to see here"
    status, body = _post(
        conn,
        "/inspect/batch",
        {
            "files": [
                {"file": _b64(watermarked), "name": "a.txt"},
                {"file": _b64(clean), "name": "b.txt"},
            ]
        },
    )
    assert status == 200
    assert body["ok"] is True
    results = {r["name"]: r for r in body["results"]}
    assert results["a.txt"]["ok"] is True
    assert results["a.txt"]["suspicious"] is True
    assert results["b.txt"]["ok"] is True
    assert results["b.txt"]["suspicious"] is False


def test_clean_batch_mixed_results(conn):
    watermarked = ("Hello" + chr(0x200B) + "World!").encode("utf-8")
    status, body = _post(
        conn,
        "/clean/batch",
        {
            "files": [
                {"file": _b64(watermarked), "name": "a.txt"},
                {"file": _b64(b"x"), "name": "b.unknownext"},
            ]
        },
    )
    assert status == 200
    assert body["ok"] is True
    results = {r["name"]: r for r in body["results"]}
    assert results["a.txt"]["ok"] is True
    cleaned = base64.b64decode(results["a.txt"]["cleaned"]).decode("utf-8")
    assert cleaned == "HelloWorld!"
    assert results["b.unknownext"]["ok"] is False
    assert "unrecognized file format" in results["b.unknownext"]["error"]


def test_batch_one_bad_option_does_not_abort_others(conn):
    status, body = _post(
        conn,
        "/clean/batch",
        {
            "files": [
                {"file": _b64(b"hello"), "name": "a.txt", "options": {"nope": 1}},
                {"file": _b64(b"hello"), "name": "b.txt"},
            ]
        },
    )
    assert status == 200
    results = {r["name"]: r for r in body["results"]}
    assert results["a.txt"]["ok"] is False
    assert "unknown option" in results["a.txt"]["error"]
    assert results["b.txt"]["ok"] is True


def test_batch_empty_files_rejected(conn):
    status, body = _post(conn, "/inspect/batch", {"files": []})
    assert status == 400
    assert "must not be empty" in body["error"]


def test_batch_missing_files_field_rejected(conn):
    status, body = _post(conn, "/clean/batch", {})
    assert status == 400
    assert "files" in body["error"]


def test_batch_over_limit_rejected(conn, monkeypatch):
    monkeypatch.setattr(server, "MAX_BATCH_FILES", 2)
    status, body = _post(
        conn,
        "/inspect/batch",
        {"files": [{"file": _b64(b"x"), "name": "a.txt"}] * 3},
    )
    assert status == 400
    assert "batch limit" in body["error"]


def test_clean_jpeg_preserves_format_extension(conn):
    # Minimal valid JPEG bytes (SOI + APP0 + EOI)
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    status, body = _post(
        conn,
        "/clean",
        {"file": _b64(jpeg_bytes), "name": "photo.jpg"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["kind"] == "image"
    assert body["report"]["format"] == "jpeg"
    cleaned = base64.b64decode(body["cleaned"])
    assert cleaned[:2] == b"\xff\xd8"


def test_clean_extensionless_svg_container_post_inspection(conn):
    svg_bytes = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><metadata>c2pa test</metadata><rect/></svg>'
    )
    status, body = _post(
        conn,
        "/clean",
        {"file": _b64(svg_bytes)},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["kind"] == "container"
    assert body["report"]["format"] == "svg"
    assert body["report"]["still_has_c2pa"] is False
