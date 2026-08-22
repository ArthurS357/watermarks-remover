#!/usr/bin/env python3
"""HTTP service exposing the watermarks-remover cleaning pipeline.

Stdlib-only. The agent skill and any web app can call it over HTTP instead of
running the CLI scripts locally.

Endpoints:
    GET  /health         -> {"ok": true, "version": ...}
    GET  /capabilities   -> which optional tools / pixel backends are present
    GET  /openapi.json   -> dynamically generated OpenAPI 3.0.3 spec
    POST /inspect        -> {"file": <base64>, "name": "x.png"} -> findings JSON
    POST /detect         -> {"file": <base64>, "name": "x.txt"} -> watermark detector reports
    POST /clean          -> {"file": <base64>, "name": "x.png", "options": {...}}
                         -> {"cleaned": <base64>, "report": {...}}
    POST /inspect/batch  -> {"files": [{"file": <base64>, "name": "x.png"}, ...]}
                         -> {"results": [{"name", "ok", "kind", "report", "suspicious"}, ...]}
    POST /detect/batch   -> {"files": [{"file": <base64>, "name": "x.txt"}, ...]}
                         -> {"results": [{"name", "ok", "kind", "detections", "report"}, ...]}
    POST /clean/batch    -> {"files": [{"file": <base64>, "name": "x.png", "options": {...}}, ...]}
                         -> {"results": [{"name", "ok", "kind", "cleaned", "report"}, ...]}

Batch endpoints loop the same single-file pipeline as /inspect, /detect, and /clean; a
per-file failure (unknown format, oversized name, bad option) shows up as
that entry's "ok": false with an "error" string and never aborts the rest of
the batch. Capped at WATERMARKS_MAX_BATCH_FILES entries per request (default
50) — the existing MAX_BODY_BYTES envelope cap still bounds total payload
size the same as a single-file request.

Hardening mirrors the CLIs: input size caps, binary-as-text guard, atomic
writes, loopback-only bind by default, optional bearer API key. Run it as an
unprivileged user (the Docker image does). Intended for a trusted network;
expose through a reverse proxy if reachable from untrusted clients.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import os
import subprocess
import sys
import tempfile
import threading
from functools import cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NotRequired, TypedDict
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from av_meta import clean_av, inspect_av
from common import (
    MAX_INPUT_BYTES,
    eprint,
    looks_binary,
    subprocess_preexec_fn,
    which,
)
from container_meta import clean_container, inspect_container
from format_dispatch import classify_bytes
from image_meta import clean_image, inspect_image, run_synthid_score
from score_stylometry import score_text_stylometry
from text_detectors import detector_status, run_all_text_detectors, run_text_detectors
from text_unicode import clean_text, inspect_text

VERSION = os.environ.get("WATERMARKS_SERVER_VERSION", "dev")

# Optional bearer token: when set, every request must send
# `Authorization: Bearer <key>`. Empty means no auth (default).
API_KEY = os.environ.get("WATERMARKS_SERVER_API_KEY", "").strip()

# Body cap for the JSON envelope. Base64 inflates by 4/3, so the decoded file
# stays well under MAX_INPUT_BYTES for the same cap.
MAX_BODY_BYTES = MAX_INPUT_BYTES + (MAX_INPUT_BYTES >> 1)

# Per-request file count cap for /inspect/batch and /clean/batch. MAX_BODY_BYTES
# already bounds total payload size; this bounds worst-case CPU/thread time from
# a request packing many tiny files into one call.
MAX_BATCH_FILES = int(os.environ.get("WATERMARKS_MAX_BATCH_FILES", "50"))

# ThreadingHTTPServer spawns one thread per connection with no cap of its own.
# Each in-flight POST can briefly hold several copies of its payload in
# memory at once -- the raw JSON body (up to MAX_BODY_BYTES, ~1.5x
# MAX_INPUT_BYTES), the base64-decoded file, and a cleaned/output copy during
# processing -- so worst case is well over MAX_BODY_BYTES per request, not
# just MAX_BODY_BYTES itself. Bounded to a fixed number of concurrently
# *processed* POST requests -- a request that cannot acquire a slot gets 503
# immediately rather than piling up. GET (/health, /capabilities,
# /openapi.json) never decodes a body, so it is not gated.
#
# Default of 4 (not the request/thread-level default a naive "one slot per
# CPU-ish" guess would pick) is sized against MAX_INPUT_BYTES's own default
# (256 MiB): 4 concurrent requests keeps the worst case in the low single-
# digit GB, which fits compose.yaml's wr-core mem_limit. Raise both
# WATERMARKS_MAX_CONCURRENT_REQUESTS and the container's mem_limit together
# if higher throughput is needed on a host with the memory to back it.
MAX_CONCURRENT_REQUESTS = int(os.environ.get("WATERMARKS_MAX_CONCURRENT_REQUESTS", "4"))
_REQUEST_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

# Seconds a connection may sit idle (no request line/headers/body sent) before
# the handler drops it. Mitigates a slowloris-style client that opens a
# connection and then trickles bytes to hold a thread open indefinitely.
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("WATERMARKS_SERVER_REQUEST_TIMEOUT", "30"))

ALLOWED_CLEAN_OPTIONS = {
    "nfkc": bool,
    "aggressive_homoglyphs": bool,
    "keep_non_ai_metadata": bool,
    "also_layer_a_text": bool,
    "remove_pixel": str,
    "strip_all_metadata": bool,
    "detect_before": bool,
    "detect_after": bool,
}


def _json_ok(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


# Flag that makes each tool print its version and exit 0. They disagree:
# exiftool treats `--version` as an unknown option and prints usage instead.
_VERSION_FLAG = {"c2patool": "--version", "exiftool": "-ver", "qpdf": "--version"}


@cache
def _tool_usable(cmd: str) -> bool:
    """True only when the tool is on PATH *and* can actually execute.

    `which` alone answers the wrong question. A binary built for another
    architecture sits on PATH and still dies before main() -- the published
    image pins a multi-arch base digest, so an arm64 host gets an arm64 image
    carrying the x86_64-only c2patool release. Advertising that as available
    is what lets a probe which never ran read as a clean verdict downstream.

    Cached: a container's tool set cannot change while the process lives.
    """
    path = which(cmd)
    if not path:
        return False
    try:
        r = subprocess.run(
            [path, _VERSION_FLAG.get(cmd, "--version")],
            capture_output=True,
            text=True,
            timeout=10,
            preexec_fn=subprocess_preexec_fn,
            check=False,
        )
    except Exception:
        return False
    return r.returncode == 0


def _degradation_warnings(kind: str, fmt: str | None) -> list[str]:
    """Explicit, structured warnings for a /clean result cleaned without a tool it needed.

    The cleaning pipeline already degrades gracefully when exiftool/qpdf/
    c2patool are missing (see clean_pdf, run_optional_tools) -- but that
    degradation is prose buried in the free-text `actions` list, discoverable
    only by a caller that greps for "warning:"/"skipped". A client is
    expected to check /capabilities before recommending a cleaning path, but
    nothing forces it to; this makes the same signal a structured, always
    machine-checkable field on the one response that matters most: the
    result of the clean the user actually asked for.
    """
    warnings: list[str] = []
    if kind == "image":
        if not _tool_usable("exiftool"):
            warnings.append(
                "exiftool not available; image metadata strip may leave residual EXIF/XMP"
            )
        if not _tool_usable("c2patool"):
            warnings.append("c2patool not available; C2PA manifests are not fully inspected")
    elif kind == "container" and fmt == "pdf":
        if not _tool_usable("qpdf"):
            warnings.append(
                "qpdf not available; pdf strip incomplete "
                "(original metadata bytes may remain recoverable)"
            )
        if not _tool_usable("exiftool"):
            warnings.append("exiftool not available; pdf strip is best-effort only")
        if not _tool_usable("c2patool"):
            warnings.append("c2patool not available; C2PA manifests are not fully inspected")
    return warnings


def capabilities() -> dict[str, Any]:
    return {
        "version": VERSION,
        "tools": {
            "c2patool": _tool_usable("c2patool"),
            "exiftool": _tool_usable("exiftool"),
            "qpdf": _tool_usable("qpdf"),
        },
        "pixel_backends": {
            "ctrlregen": bool(os.environ.get("NOAI_WATERMARK_DIR")),
            "diffusion": bool(os.environ.get("MARKDIFFUSION_DIR")),
        },
        "scorers": {
            "synthid": bool(os.environ.get("REVERSE_SYNTHID_DIR")),
            "synthid_http": bool(os.environ.get("WATERMARKS_SYNTHID_SCORER_URL")),
            "stylometry": True,
        },
        "text_detectors": detector_status(),
        "harnesses": {
            "markllm": bool(os.environ.get("MARKLLM_DIR")),
        },
    }


# OpenAPI generation. The spec is built from this single declarative table
# plus live runtime values (version, auth, allowed options), so it can never
# drift from the endpoints the handler actually serves. Served at /openapi.json.


def _schema(**props: Any) -> dict[str, Any]:
    return props


def _file_request(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["file"],
        "properties": {
            "file": {
                "type": "string",
                "description": "Base64-encoded file bytes",
                "example": "SGVsbG8gd29ybGQ=",
            },
            "name": {
                "type": "string",
                "description": "Original filename (extension drives format routing)",
                "example": "notes.md",
            },
        },
    }
    if extra:
        schema["properties"].update(extra["properties"])
        schema["required"] = schema["required"] + extra.get("required", [])
    return schema


def _clean_request_schema() -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key, kind in ALLOWED_CLEAN_OPTIONS.items():
        if kind is bool:
            options[key] = _schema(type="boolean")
        else:
            options[key] = _schema(type="string")
    return _file_request(
        {
            "properties": {
                "options": _schema(type="object", properties=options, additionalProperties=False)
            },
        }
    )


_OPENAPI_PATHS: dict[str, dict[str, Any]] = {
    "/health": {
        "get": {
            "summary": "Liveness and version",
            "responses": {
                "200": _schema(
                    type="object",
                    properties={"ok": _schema(type="boolean"), "version": _schema(type="string")},
                )
            },
        }
    },
    "/capabilities": {
        "get": {
            "summary": "Which optional tools and heavy backends are available",
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "version": _schema(type="string"),
                        "tools": _schema(
                            type="object",
                            properties={
                                k: _schema(type="boolean") for k in ("c2patool", "exiftool", "qpdf")
                            },
                        ),
                        "pixel_backends": _schema(
                            type="object",
                            properties={
                                k: _schema(type="boolean") for k in ("ctrlregen", "diffusion")
                            },
                        ),
                        "scorers": _schema(
                            type="object",
                            properties={
                                "synthid": _schema(type="boolean"),
                                "synthid_http": _schema(type="boolean"),
                                "stylometry": _schema(type="boolean"),
                            },
                        ),
                        "harnesses": _schema(
                            type="object", properties={"markllm": _schema(type="boolean")}
                        ),
                        "text_detectors": _schema(
                            type="object",
                            additionalProperties=_schema(type="boolean"),
                        ),
                    },
                )
            },
        }
    },
    "/openapi.json": {
        "get": {
            "summary": "This OpenAPI 3.0.3 document, generated dynamically",
            "responses": {
                "200": _schema(type="object", description="An OpenAPI 3.0.3 document"),
            },
        }
    },
    "/inspect": {
        "post": {
            "summary": "Inspect a file for AI provenance marks (text / image / container auto-routed)",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_file_request(
                            {
                                "properties": {
                                    "detect": _schema(
                                        type="boolean",
                                        description=(
                                            "Also run configured text watermark detectors "
                                            "(opt-in; may call vendor APIs and send text "
                                            "to them)"
                                        ),
                                    )
                                },
                                "required": [],
                            }
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "kind": _schema(type="string", enum=["text", "image", "container", "av"]),
                        "suspicious": _schema(type="boolean"),
                        "report": _schema(type="object"),
                    },
                )
            },
        }
    },
    "/clean": {
        "post": {
            "summary": "Clean a file; returns the cleaned bytes and an actions/stats report",
            "requestBody": _schema(
                required=True,
                content={"application/json": _schema(schema=_clean_request_schema())},
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "kind": _schema(type="string", enum=["text", "image", "container", "av"]),
                        "cleaned": _schema(
                            type="string", description="Base64-encoded cleaned file bytes"
                        ),
                        "report": _schema(type="object"),
                    },
                )
            },
        }
    },
    "/detect": {
        "post": {
            "summary": "Run watermark detectors on a file (text: vendor/statistical; image: SynthID score)",
            "requestBody": _schema(
                required=True,
                content={"application/json": _schema(schema=_file_request())},
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "kind": _schema(type="string", enum=["text", "image", "container", "av"]),
                        "detections": _schema(type="array", items=_schema(type="object")),
                    },
                )
            },
        }
    },
    "/inspect/batch": {
        "post": {
            "summary": f"Inspect up to {MAX_BATCH_FILES} files in one request",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={"files": _schema(type="array", items=_file_request())},
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "results": _schema(
                            type="array",
                            items=_schema(
                                type="object",
                                properties={
                                    "name": _schema(type="string"),
                                    "ok": _schema(type="boolean"),
                                    "kind": _schema(
                                        type="string",
                                        enum=["text", "image", "container", "av", "unknown"],
                                    ),
                                    "suspicious": _schema(type="boolean"),
                                    "report": _schema(type="object"),
                                    "error": _schema(type="string"),
                                },
                            ),
                        ),
                    },
                )
            },
        }
    },
    "/detect/batch": {
        "post": {
            "summary": f"Run watermark detectors on up to {MAX_BATCH_FILES} files in one request",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={"files": _schema(type="array", items=_file_request())},
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "results": _schema(
                            type="array",
                            items=_schema(
                                type="object",
                                properties={
                                    "name": _schema(type="string"),
                                    "ok": _schema(type="boolean"),
                                    "kind": _schema(
                                        type="string",
                                        enum=["text", "image", "container", "av"],
                                    ),
                                    "detections": _schema(
                                        type="array", items=_schema(type="object")
                                    ),
                                    "report": _schema(type="object"),
                                    "error": _schema(type="string"),
                                },
                            ),
                        ),
                    },
                )
            },
        }
    },
    "/clean/batch": {
        "post": {
            "summary": f"Clean up to {MAX_BATCH_FILES} files in one request",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={
                                "files": _schema(type="array", items=_clean_request_schema())
                            },
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "results": _schema(
                            type="array",
                            items=_schema(
                                type="object",
                                properties={
                                    "name": _schema(type="string"),
                                    "ok": _schema(type="boolean"),
                                    "kind": _schema(
                                        type="string", enum=["text", "image", "container", "av"]
                                    ),
                                    "cleaned": _schema(type="string"),
                                    "report": _schema(type="object"),
                                    "error": _schema(type="string"),
                                },
                            ),
                        ),
                    },
                )
            },
        }
    },
}

_ERROR_SCHEMA = _schema(
    type="object",
    properties={"ok": _schema(type="boolean", enum=[False]), "error": _schema(type="string")},
)
_COMMON_ERRORS = {
    "400": {
        "description": "Bad request",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
    "401": {
        "description": "Missing/invalid bearer token",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
    "404": {"description": "Not found", "content": {"application/json": {"schema": _ERROR_SCHEMA}}},
    "413": {
        "description": "Request body too large",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
    "500": {
        "description": "Internal error",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
}


def openapi_spec() -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for path, ops in _OPENAPI_PATHS.items():
        for method, op in ops.items():
            responses = dict(_COMMON_ERRORS)
            for status, body in op["responses"].items():
                responses[status] = {
                    "description": "Success",
                    "content": {"application/json": {"schema": body}},
                }
            paths.setdefault(path, {})[method] = {
                "summary": op["summary"],
                "responses": responses,
                **((op.get("requestBody") and {"requestBody": op["requestBody"]}) or {}),
                # /health never requires auth (see Handler.do_GET); override the
                # global security requirement set below so the spec matches.
                **({"security": []} if path == "/health" else {}),
            }

    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": "watermarks-remover service",
            "version": VERSION,
            "description": "Strip multi-vendor AI provenance marks (Unicode, C2PA/EXIF/XMP, containers). "
            "Files are passed base64-encoded in JSON; cleaned bytes come back base64-encoded.",
        },
        "paths": paths,
    }
    if API_KEY:
        spec["components"] = {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            }
        }
        spec["security"] = [{"bearerAuth": []}]
    return spec


def _safe_name(name: str) -> str:
    """Reduce a client-supplied filename to a bare basename safe for temp use.

    CodeQL (uncontrolled data in path expression): a name like '../../x'
    would otherwise let the write below escape the request temp dir. Fold
    Windows separators too, and fall back to a neutral name for '.', '..' or
    empty results.
    """
    base = Path(name.replace("\\", "/")).name
    if base in ("", ".", ".."):
        return "input"
    return base


def _tmp_path(tmpdir: Path, *parts: str) -> Path:
    """Join *parts* under *tmpdir* and refuse anything that escapes it.

    Defense-in-depth for the CodeQL "uncontrolled data in path expression"
    findings: even if a caller slips a separator through, the write can never
    land outside the request temp dir.
    """
    path = tmpdir.joinpath(*parts)
    if path.parent != tmpdir:
        raise ValueError("unsafe filename")
    return path


def _decode_input(body: dict[str, Any]) -> tuple[bytes, str]:
    raw = body.get("file")
    if not isinstance(raw, str):
        raise ValueError("missing string field 'file' (base64-encoded bytes)")
    name = body.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("'name' must be a string")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("'file' is not valid base64") from None
    return data, _safe_name(name or "")


def _parse_clean_options(options: Any) -> dict[str, Any]:
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise ValueError("'options' must be an object")
    for key, value in options.items():
        if key not in ALLOWED_CLEAN_OPTIONS:
            raise ValueError(f"unknown option: {key}")
        expected_type = ALLOWED_CLEAN_OPTIONS[key]
        if not isinstance(value, expected_type):
            type_name = "boolean" if expected_type is bool else "string"
            raise ValueError(f"option {key!r} must be a {type_name}")
    return options


def _batch_items(
    body: dict[str, Any],
) -> list[tuple[str, bytes, dict[str, Any], str | None]]:
    """Decode a batch request's 'files' array into (name, data, options, error) tuples.

    A malformed individual entry (bad base64, unknown option) becomes an error
    string paired with that entry rather than raising, so one bad file never
    aborts the rest of the batch. Only 'files' itself being missing, empty, or
    over MAX_BATCH_FILES raises — that is a malformed request, not a per-file
    problem.
    """
    files = body.get("files")
    if not isinstance(files, list):
        raise ValueError("missing array field 'files'")
    if not files:
        raise ValueError("'files' must not be empty")
    if len(files) > MAX_BATCH_FILES:
        raise ValueError(f"'files' exceeds the {MAX_BATCH_FILES}-file batch limit")

    items: list[tuple[str, bytes, dict[str, Any], str | None]] = []
    for entry in files:
        if not isinstance(entry, dict):
            items.append(("", b"", {}, "each entry in 'files' must be an object"))
            continue
        try:
            data, name = _decode_input(entry)
        except ValueError as e:
            fallback_name = entry.get("name") if isinstance(entry.get("name"), str) else ""
            items.append((fallback_name, b"", {}, str(e)))
            continue
        try:
            options = _parse_clean_options(entry.get("options"))
        except ValueError as e:
            items.append((name, b"", {}, str(e)))
            continue
        items.append((name, data, options, None))
    return items


# TypedDicts document the stable outer envelope of each HTTP response --
# the shape the OpenAPI spec above and SKILL.md's endpoint table already
# promise callers. `report`/`detections` stay dict[str, Any]/
# list[dict[str, Any]] rather than being typed further: their actual shape
# varies by `kind` (text/image/container/av each have a different report
# schema, see inspect_image/inspect_container/etc.'s own dataclasses), and a
# faithful static type for that would need a discriminated union keyed on
# `kind` -- a much larger effort than this envelope-level contract needs.
# Not enforced by CI (no mypy step exists yet); read as documentation.
class InspectPayload(TypedDict):
    ok: bool
    kind: str
    report: dict[str, Any]
    suspicious: bool


class DetectPayload(TypedDict):
    ok: bool
    kind: str
    detections: list[dict[str, Any]]
    report: NotRequired[dict[str, Any]]  # only present for av/container kinds


class CleanPayload(TypedDict):
    ok: bool
    kind: str
    cleaned: str
    report: dict[str, Any]


def _inspect_payload(data: bytes, name: str, run_detect: bool) -> InspectPayload:
    kind = classify_bytes(data, Path(name).suffix)
    if kind == "unknown":
        return {
            "ok": True,
            "kind": "unknown",
            "report": {"note": "unrecognized format; use a filename with a known extension"},
            "suspicious": False,
        }
    with tempfile.TemporaryDirectory(prefix="wm-inspect-") as tmp:
        path = _tmp_path(Path(tmp), name or "input")
        path.write_bytes(data)
        if kind == "text":
            if looks_binary(data):
                raise ValueError(
                    "refusing to inspect bytes that look like a binary container as text"
                )
            raw_text = data.decode("utf-8", errors="surrogateescape")
            report = inspect_text(raw_text).to_dict()
            s_rep = score_text_stylometry(raw_text, path=name or "<text>")
            report["stylometry"] = s_rep.to_dict()
            if run_detect:
                report["text_detectors"] = run_all_text_detectors(raw_text)
        elif kind == "image":
            report = inspect_image(path).to_dict()
        elif kind == "av":
            report = inspect_av(path).to_dict()
        else:
            report = inspect_container(path).to_dict()
    detected_wm = any(
        entry.get("available") and entry.get("is_watermarked")
        for entry in report.get("text_detectors") or []
    )
    suspicious = (
        bool(report.get("suspicious_total"))
        or bool(report.get("has_c2pa") or report.get("has_ai_metadata"))
        or bool(report.get("stylometry", {}).get("score", 0.0) >= 0.65)
        or detected_wm
    )
    return {"ok": True, "kind": kind, "report": report, "suspicious": suspicious}


def _detect_payload(data: bytes, name: str) -> DetectPayload:
    kind = classify_bytes(data, Path(name).suffix)
    with tempfile.TemporaryDirectory(prefix="wm-detect-") as tmp:
        path = _tmp_path(Path(tmp), name or "input")
        path.write_bytes(data)
        if kind == "text":
            if looks_binary(data):
                raise ValueError(
                    "refusing to detect bytes that look like a binary container as text"
                )
            raw_text = data.decode("utf-8", errors="surrogateescape")
            detections: list[dict[str, Any]] = run_all_text_detectors(raw_text)
            s_rep = score_text_stylometry(raw_text, path=name or "<text>")
            detections.append({"detector": "stylometry", "available": True, **s_rep.to_dict()})
            return {"ok": True, "kind": kind, "detections": detections}
        elif kind == "image":
            score = run_synthid_score(path)
            if score is None:
                score = {
                    "detector": "synthid",
                    "available": False,
                    "error": (
                        "no SynthID scorer configured (set "
                        "WATERMARKS_SYNTHID_SCORER_URL or REVERSE_SYNTHID_DIR)"
                    ),
                }
            else:
                score.setdefault("detector", "synthid")
            detections = [score]
            return {"ok": True, "kind": kind, "detections": detections}
        elif kind == "av":
            return {
                "ok": True,
                "kind": kind,
                "detections": [],
                "report": inspect_av(path).to_dict(),
            }
        else:
            detections = []
            report = inspect_container(path).to_dict()
            return {
                "ok": True,
                "kind": kind,
                "detections": detections,
                "report": report,
            }


def _clean_payload(data: bytes, name: str, options: dict[str, Any]) -> CleanPayload:
    kind = classify_bytes(data, Path(name).suffix)
    if kind == "unknown":
        raise ValueError(
            "unrecognized file format; use a filename with a known extension "
            "(e.g. notes.txt) or a supported image/container name"
        )

    with tempfile.TemporaryDirectory(prefix="wm-clean-") as tmp:
        tmpdir = Path(tmp)
        src = _tmp_path(tmpdir, name or "input")
        src.write_bytes(data)
        if kind == "text":
            if looks_binary(data):
                raise ValueError(
                    "refusing to clean bytes that look like a binary container as text"
                )
            text = data.decode("utf-8", errors="surrogateescape")
            detect_before = bool(options.get("detect_before"))
            detect_after = bool(options.get("detect_after"))
            detector_reports: dict[str, Any] = {}
            if detect_before:
                detector_reports["before"] = run_text_detectors(text)
            cleaned, stats = clean_text(
                text,
                nfkc=bool(options.get("nfkc")),
                aggressive_homoglyphs=bool(options.get("aggressive_homoglyphs")),
            )
            if detect_after:
                detector_reports["after"] = run_text_detectors(cleaned)
            cleaned_bytes = cleaned.encode("utf-8", errors="surrogateescape")
            report: dict[str, Any] = {"kind": "text", "stats": stats, "length": len(cleaned)}
            if detector_reports:
                report["text_detectors"] = detector_reports
        elif kind == "image":
            ext = Path(name).suffix
            if not ext:
                from image_meta import detect_format

                fmt_name = detect_format(data)
                ext = f".{fmt_name}" if fmt_name != "unknown" else ".png"
            dest = _tmp_path(tmpdir, f"out{ext}")
            strip_all = not bool(options.get("keep_non_ai_metadata"))
            if "strip_all_metadata" in options:
                strip_all = bool(options["strip_all_metadata"])
            remove_pixel = options.get("remove_pixel")
            if remove_pixel not in (None, "ctrlregen", "diffusion"):
                raise ValueError("remove_pixel must be one of: ctrlregen, diffusion")
            result = clean_image(
                src,
                dest,
                strip_all_metadata=strip_all,
                remove_pixel=remove_pixel,
            )
            if bool(options.get("detect_before")) and result.get("synthid_before") is None:
                result["synthid_before"] = run_synthid_score(src)
            if bool(options.get("detect_after")) and result.get("synthid_after") is None:
                result["synthid_after"] = run_synthid_score(dest)
            cleaned_bytes = dest.read_bytes()
            report = {"kind": "image", **result}
        elif kind == "av":
            dest = _tmp_path(tmpdir, f"out{Path(name).suffix or '.bin'}")
            strip_all = not bool(options.get("keep_non_ai_metadata"))
            if "strip_all_metadata" in options:
                strip_all = bool(options["strip_all_metadata"])
            result = clean_av(src, dest, strip_all_metadata=strip_all)
            cleaned_bytes = dest.read_bytes()
            report = {"kind": "av", **result}
        else:
            ext = Path(name).suffix
            container_fmt = None
            if not ext:
                from container_meta import detect_container_format

                container_fmt = detect_container_format(Path("input"), data)
                ext_map = {
                    "svg": ".svg",
                    "pdf": ".pdf",
                    "docx": ".docx",
                    "xlsx": ".xlsx",
                    "pptx": ".pptx",
                    "odt": ".odt",
                    "epub": ".epub",
                    "html": ".html",
                    "markdown": ".md",
                }
                ext = ext_map.get(container_fmt, "")
            dest = _tmp_path(tmpdir, f"out{ext}")
            result = clean_container(
                src,
                dest,
                fmt=container_fmt,
                also_layer_a_text=bool(options.get("also_layer_a_text", True)),
            )
            cleaned_bytes = dest.read_bytes()
            report = {"kind": "container", **result}
        report.pop("input", None)
        report.pop("output", None)

    warnings = _degradation_warnings(kind, report.get("format"))
    if warnings:
        report["warnings"] = warnings

    return {
        "ok": True,
        "kind": kind,
        "cleaned": base64.b64encode(cleaned_bytes).decode("ascii"),
        "report": report,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = f"watermarks-remover/{VERSION}"
    # StreamRequestHandler.setup() applies this to the connection socket, so
    # a client that opens a connection and then stalls (slowloris) gets
    # dropped instead of holding a thread open indefinitely.
    timeout = REQUEST_TIMEOUT_SECONDS

    def log_message(self, fmt: str, *args: object) -> None:
        eprint(f"{self.address_string()} - {fmt % args}")

    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        header = self.headers.get("Authorization", "")
        return hmac.compare_digest(header, f"Bearer {API_KEY}")

    def _read_json(self) -> dict[str, Any] | None:
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isdigit():
            return None
        length = int(raw)
        if length > MAX_BODY_BYTES:
            return None
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(body, dict):
            return None
        return body

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        data = _json_ok(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        # /health is a public liveness probe: it leaks no data beyond the
        # version string, and the skill/orchestration tooling calls it
        # unauthenticated to decide whether the service is even reachable.
        if path == "/health":
            self._respond(HTTPStatus.OK, {"ok": True, "version": VERSION})
            return
        if not self._authorized():
            self._respond(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if path == "/capabilities":
            self._respond(HTTPStatus.OK, {"ok": True, **capabilities()})
        elif path == "/openapi.json":
            self._respond(HTTPStatus.OK, openapi_spec())
        else:
            self._respond(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        # Every POST body decodes into memory (up to MAX_BODY_BYTES); cap how
        # many are processed at once rather than let concurrency multiply
        # that unboundedly. A full slot table answers fast (503) instead of
        # queuing, so a caller sees backpressure instead of a stall.
        if not _REQUEST_SLOTS.acquire(blocking=False):
            self._respond(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "server busy, too many concurrent requests"},
            )
            return
        try:
            self._do_POST()
        finally:
            _REQUEST_SLOTS.release()

    def _do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self._authorized():
            self._respond(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if path not in (
            "/inspect",
            "/clean",
            "/detect",
            "/inspect/batch",
            "/detect/batch",
            "/clean/batch",
        ):
            self._respond(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        body = self._read_json()
        if body is None:
            raw_len = self.headers.get("Content-Length")
            oversized = raw_len is not None and raw_len.isdigit() and int(raw_len) > MAX_BODY_BYTES
            self._respond(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE if oversized else HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid request body"},
            )
            return
        try:
            if path == "/inspect/batch":
                self._handle_inspect_batch(body)
            elif path == "/detect/batch":
                self._handle_detect_batch(body)
            elif path == "/clean/batch":
                self._handle_clean_batch(body)
            else:
                data, name = _decode_input(body)
                if path == "/inspect":
                    self._handle_inspect(data, name, body)
                elif path == "/detect":
                    self._handle_detect(data, name)
                else:
                    self._handle_clean(data, name, body)
        except ValueError as e:
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(e)})
        except Exception as e:
            eprint(f"error handling {path}: {e!r}")
            self._respond(
                HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal error"}
            )

    def _handle_inspect(self, data: bytes, name: str, body: dict[str, Any]) -> None:
        run_detect = body.get("detect") is True
        self._respond(HTTPStatus.OK, _inspect_payload(data, name, run_detect))

    def _handle_inspect_batch(self, body: dict[str, Any]) -> None:
        items = _batch_items(body)
        run_detect = body.get("detect") is True
        results = []
        for name, data, _options, error in items:
            if error is not None:
                results.append({"name": name, "ok": False, "error": error})
                continue
            try:
                payload = _inspect_payload(data, name, run_detect)
            except ValueError as e:
                results.append({"name": name, "ok": False, "error": str(e)})
                continue
            results.append({"name": name, **payload})
        self._respond(HTTPStatus.OK, {"ok": True, "results": results})

    def _handle_detect(self, data: bytes, name: str) -> None:
        self._respond(HTTPStatus.OK, _detect_payload(data, name))

    def _handle_detect_batch(self, body: dict[str, Any]) -> None:
        items = _batch_items(body)
        results = []
        for name, data, _options, error in items:
            if error is not None:
                results.append({"name": name, "ok": False, "error": error})
                continue
            try:
                payload = _detect_payload(data, name)
            except ValueError as e:
                results.append({"name": name, "ok": False, "error": str(e)})
                continue
            results.append({"name": name, **payload})
        self._respond(HTTPStatus.OK, {"ok": True, "results": results})

    def _handle_clean(self, data: bytes, name: str, body: dict[str, Any]) -> None:
        options = _parse_clean_options(body.get("options"))
        self._respond(HTTPStatus.OK, _clean_payload(data, name, options))

    def _handle_clean_batch(self, body: dict[str, Any]) -> None:
        items = _batch_items(body)
        results = []
        for name, data, options, error in items:
            if error is not None:
                results.append({"name": name, "ok": False, "error": error})
                continue
            try:
                payload = _clean_payload(data, name, options)
            except ValueError as e:
                results.append({"name": name, "ok": False, "error": str(e)})
                continue
            results.append({"name": name, **payload})
        self._respond(HTTPStatus.OK, {"ok": True, "results": results})


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _flag_env(name: str) -> bool:
    """Parse a boolean env var the same way rewrite_text.py does.

    bool(os.environ.get(name)) treats *any* non-empty string as true, so
    WATERMARKS_SERVER_ALLOW_INSECURE_BIND=0 -- someone's explicit attempt to
    disable it -- would otherwise enable it.
    """
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _refuses_insecure_bind(host: str, api_key: str, allow_insecure_bind: bool) -> bool:
    """True when *host* is non-loopback, no API key is set, and no opt-out was given.

    A non-loopback bind with no auth exposes the cleaning API (arbitrary file
    upload/processing) to anyone who can reach the host. Split out from
    main() so the decision is unit-testable without touching argparse or a
    real socket.
    """
    return host not in _LOOPBACK_HOSTS and not api_key and not allow_insecure_bind


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=os.environ.get("WATERMARKS_SERVER_HOST", "127.0.0.1"))
    p.add_argument(
        "--port", type=int, default=int(os.environ.get("WATERMARKS_SERVER_PORT", "8765"))
    )
    p.add_argument(
        "--allow-insecure-bind",
        action="store_true",
        default=_flag_env("WATERMARKS_SERVER_ALLOW_INSECURE_BIND"),
        help=(
            "allow binding a non-loopback host with no API key set (default: refuse). "
            "Only pass this when the real access boundary is elsewhere, e.g. a container "
            "port published as 127.0.0.1:<port>:<port>."
        ),
    )
    p.add_argument("-V", "--version", action="store_true", help="print version and exit")
    args = p.parse_args()

    if args.version:
        print(VERSION)
        return 0

    if _refuses_insecure_bind(args.host, API_KEY, args.allow_insecure_bind):
        eprint(
            f"error: refusing to bind {args.host} with no API key set — this would expose "
            "the cleaning API (arbitrary file upload/processing) to anyone who can reach "
            "this host. Set WATERMARKS_SERVER_API_KEY, or pass --allow-insecure-bind / set "
            "WATERMARKS_SERVER_ALLOW_INSECURE_BIND=1 if the real access boundary is "
            "elsewhere (e.g. a container port published as 127.0.0.1:<port>:<port>)."
        )
        return 2

    if args.host not in _LOOPBACK_HOSTS:
        eprint(f"warning: binding {args.host} — intended for a trusted network only")
    if API_KEY:
        eprint("API key required for requests")
    else:
        eprint("warning: no API key set — only bind to loopback or a trusted network")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    eprint(f"watermarks-remover service {VERSION} on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        eprint("shutting down")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
