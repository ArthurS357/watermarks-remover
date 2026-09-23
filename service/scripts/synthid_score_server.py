#!/usr/bin/env python3
"""Tiny stdlib HTTP sidecar exposing the reverse-SynthID pixel scorer.

Runs inside the local-only wr-synthid heavy image so the published core
image never bundles the non-commercial reverse-SynthID code. The core
service calls this sidecar for SynthID image scoring when
WATERMARKS_SYNTHID_SCORER_URL is set (see compose.yaml / .env.example).

Endpoints:
    GET  /health  -> {"ok": true, "version": ...}
    POST /score   -> {"file": <base64>} -> score_synthid payload

Hardening mirrors server.py: optional bearer key, input size caps,
unprivileged user, read-only rootfs with a /tmp tmpfs. Intended for the
compose network or a trusted network only.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import os
import sys
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from score_synthid import score_file

VERSION = os.environ.get("WATERMARKS_SYNTHID_SERVER_VERSION", "dev")


def _env_int(name: str, default: int) -> int:
    """common.env_int's fallback, repeated: the sidecar image does not copy common.py."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        print(f"warning: {name}={raw!r} is not an integer; using {default}", file=sys.stderr)
        return default


# Mirror common.MAX_INPUT_BYTES (env-overridable) with the base64 envelope
# headroom. Read at import, so a typo must warn instead of aborting.
MAX_INPUT_BYTES = _env_int("WATERMARKS_MAX_INPUT_BYTES", 256 << 20)
MAX_BODY_BYTES = MAX_INPUT_BYTES + (MAX_INPUT_BYTES >> 1)

API_KEY = os.environ.get("WATERMARKS_SYNTHID_SCORER_API_KEY", "").strip()
MODEL = os.environ.get("WATERMARKS_SYNTHID_MODEL", "").strip() or None

# Mirrors server.py's LOOPBACK_HOSTS: the sidecar image does not copy common.py.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _env_flag(name: str) -> bool:
    """common.env_flag's fallback, repeated for the same reason as _env_int."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _refuses_insecure_bind(host: str, api_key: str, allow_insecure_bind: bool) -> bool:
    """True when *host* is non-loopback, no API key is set, and no opt-out was given.

    A non-loopback bind with no auth exposes image scoring (arbitrary base64
    payload accepted and written to disk) to anyone who can reach the host.
    """
    return host not in _LOOPBACK_HOSTS and not api_key and not allow_insecure_bind


def _json_ok(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = f"watermarks-remover-synthid/{VERSION}"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", file=sys.stderr)

    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        # Bytes and isdecimal below: same edge cases as server.py's Handler.
        header = self.headers.get("Authorization", "")
        return hmac.compare_digest(header.encode(), f"Bearer {API_KEY}".encode())

    def _read_json(self) -> dict[str, Any] | None:
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isdecimal():
            return None
        length = int(raw)
        if length > MAX_BODY_BYTES:
            return None
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            return None
        return body if isinstance(body, dict) else None

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        data = _json_ok(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if not self._authorized():
            self._respond(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if urlparse(self.path).path == "/health":
            self._respond(HTTPStatus.OK, {"ok": True, "version": VERSION})
        else:
            self._respond(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._respond(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if urlparse(self.path).path != "/score":
            self._respond(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        body = self._read_json()
        if body is None:
            raw_len = self.headers.get("Content-Length")
            oversized = (
                raw_len is not None and raw_len.isdecimal() and int(raw_len) > MAX_BODY_BYTES
            )
            self._respond(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE if oversized else HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid request body"},
            )
            return

        raw = body.get("file")
        if not isinstance(raw, str):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing 'file' field"})
            return
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            self._respond(
                HTTPStatus.BAD_REQUEST, {"ok": False, "error": "'file' is not valid base64"}
            )
            return
        if len(data) > MAX_INPUT_BYTES:
            self._respond(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "file too large"}
            )
            return

        with tempfile.TemporaryDirectory(prefix="wm-synthid-") as tmp:
            path = Path(tmp) / "input.png"
            try:
                path.write_bytes(data)
            except OSError as e:
                self._respond(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(e)})
                return
            code, payload = score_file(path, model=MODEL)

        if code == 0 and payload is not None:
            self._respond(HTTPStatus.OK, payload)
        elif code == 2:
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "could not load image"})
        else:
            # exit 1 (runtime error) or 3 (unavailable) -> fail-soft payload,
            # matching the shape image_meta.run_synthid_score expects.
            self._respond(
                HTTPStatus.OK,
                {"available": False, "error": "scorer unavailable (see sidecar stderr)"},
            )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=os.environ.get("WATERMARKS_SYNTHID_SERVER_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=_env_int("WATERMARKS_SYNTHID_SERVER_PORT", 8766))
    p.add_argument(
        "--allow-insecure-bind",
        action="store_true",
        default=_env_flag("WATERMARKS_SYNTHID_SERVER_ALLOW_INSECURE_BIND"),
        help=(
            "allow binding a non-loopback host with no API key set (default: refuse). "
            "Only pass this when the real access boundary is elsewhere, e.g. a container "
            "port published as 127.0.0.1:<port>:<port>."
        ),
    )
    args = p.parse_args()

    if not API_KEY.isascii():
        print("error: WATERMARKS_SYNTHID_SCORER_API_KEY must be ASCII", file=sys.stderr)
        return 2

    if _refuses_insecure_bind(args.host, API_KEY, args.allow_insecure_bind):
        print(
            f"error: refusing to bind {args.host} with no API key set — this would expose "
            "image scoring to anyone who can reach this host. Set "
            "WATERMARKS_SYNTHID_SCORER_API_KEY, or pass --allow-insecure-bind / set "
            "WATERMARKS_SYNTHID_SERVER_ALLOW_INSECURE_BIND=1 if the real access boundary is "
            "elsewhere (e.g. a container port published as 127.0.0.1:<port>:<port>).",
            file=sys.stderr,
        )
        return 2

    if args.host not in _LOOPBACK_HOSTS:
        print(
            f"warning: binding {args.host} — intended for a trusted network only", file=sys.stderr
        )
    print(f"synthid scorer sidecar {VERSION} on http://{args.host}:{args.port}", file=sys.stderr)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
