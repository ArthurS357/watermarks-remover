# AI integration guide

Self-contained reference for driving `watermarks-remover` over HTTP — for any
agent (Claude, Antigravity, Codex, …) or human. You do not need to read the
[README](README.md) first.

The service strips AI provenance marks from text and files. It is stdlib-only
Python, binds loopback by default, and speaks JSON with files base64-encoded in
both directions.

---

## 1. Start the service

**Windows**, with the global command installed (see [`watermarks-server.cmd`](watermarks-server.cmd)):

```bash
watermarks-server --wait        # start + block until /health answers (30s budget)
watermarks-server --wait 60     # same, 60s budget
watermarks-server --status      # online | degraded | offline
watermarks-server --stop        # shut it down
```

`--wait` exits `0` once the service answers and `1` on timeout, so it is safe to
gate on. It also watches the process it started: if the server dies before
answering (python missing, port already taken, bind refused) it fails
immediately with that cause instead of waiting out the budget. `--status` exits `0` when the service answers (online *or* degraded) and
`1` when it is offline. With no arguments the command opens a log window and
returns immediately — use `--wait` for automation.

**Any platform:**

```bash
python3 service/scripts/server.py --host 127.0.0.1 --port 8765
# or
make serve
# or
docker compose up -d
```

Requires Python 3.12+ (stdlib only, no dependencies).

---

## 2. Recommended flow

```
/health   → is it up?          → if not, start it (§1) and retry
/readyz   → can it do the job? → if "degraded", downgrade what you promise
/inspect  → is there anything to remove?
/clean    → remove it
```

Both `/health` and `/readyz` are **unauthenticated**, so they work before you
hold a token. Everything else is gated when an API key is set.

Never skip `/inspect`. Cleaning a file with nothing to clean still rewrites its
bytes; the inspect result is what lets you tell the user whether anything was
actually found.

---

## 3. Endpoints

Set the base URL once:

```bash
WM="${WATERMARKS_SERVICE_URL:-http://127.0.0.1:8765}"
```

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | no | Liveness + version |
| GET | `/readyz` | no | Readiness: supported layers, optional-tool status |
| GET | `/capabilities` | yes | Full inventory incl. heavy backends and detectors |
| GET | `/openapi.json` | yes | Machine-readable OpenAPI 3.0.3 contract |
| POST | `/inspect` | yes | Find marks in one file |
| POST | `/detect` | yes | Run watermark detectors on one file |
| POST | `/clean` | yes | Strip marks from one file |
| POST | `/inspect/batch` | yes | Same as `/inspect`, many files |
| POST | `/detect/batch` | yes | Same as `/detect`, many files |
| POST | `/clean/batch` | yes | Same as `/clean`, many files |

### `/health`

```bash
curl -s "$WM/health"
```

```json
{ "ok": true, "version": "dev" }
```

### `/readyz`

```bash
curl -s "$WM/readyz"
```

```json
{
  "ok": true,
  "status": "degraded",
  "service": { "name": "watermarks-remover", "version": "dev" },
  "capabilities": ["unicode_invisible", "statistical_text", "metadata"],
  "tools": {
    "c2patool": { "available": false },
    "exiftool": { "available": true, "version": "12.76" },
    "qpdf": { "available": false }
  },
  "pixel_backends": {
    "verified": false,
    "note": "configured = env var set and its directory exists, ...",
    "ctrlregen": { "configured": true },
    "diffusion": { "configured": false, "reason": "not configured" }
  }
}
```

- `status` is `"ok"` when all three optional tools run, `"degraded"` otherwise.
- **`"degraded"` is advisory, not a failure.** Every listed layer still runs; it
  just runs less thoroughly. Adjust your claims about the result — do not refuse
  the job.
- `capabilities` lists the layers this build supports. The first three need no
  external tool. `pixel_removal` appears only when a pixel backend is configured.
- `tools[name].version` is present only when the tool is available.
- **`pixel_backends.verified` is always `false`.** `configured: true` means the
  env var is set *and* its directory exists — the same precondition the cleaning
  path itself checks — but the heavy dependencies (torch, model weights) are not
  imported here, so a configured backend can still fail at run time. Treat it as
  "worth attempting", never as "will work". `reason` distinguishes `"not
  configured"` from `"configured directory not found"` (a broken config); the
  path itself is never returned.

### `/capabilities`

Everything `/readyz` reports plus the heavy backends — pixel removal
(`ctrlregen`, `diffusion`), scorers (`synthid`, `synthid_http`, `stylometry`),
text detectors, and research harnesses.

```bash
curl -s "$WM/capabilities"
```

Only promise pixel removal, SynthID scoring, or vendor detection when this says
the backend is present.

### `/inspect`

```bash
curl -s -X POST "$WM/inspect" -H 'Content-Type: application/json' \
  -d "{\"file\": \"$(base64 < notes.md | tr -d '\n')\", \"name\": \"notes.md\"}"
```

Returns `{"ok", "kind", "suspicious", "report"}`. Pass `"detect": true` to append
watermark-detector results to the report.

### `/detect`

```bash
curl -s -X POST "$WM/detect" -H 'Content-Type: application/json' \
  -d "{\"file\": \"$(base64 < notes.txt | tr -d '\n')\", \"name\": \"notes.txt\"}"
```

Returns `{"ok", "kind", "detections": [...]}`. Detection is fail-soft:
unconfigured or errored detectors report `{"available": false, "error": ...}`
rather than failing the request.

### `/clean`

```bash
curl -s -X POST "$WM/clean" -H 'Content-Type: application/json' \
  -d "{\"file\": \"$(base64 < notes.md | tr -d '\n')\", \"name\": \"notes.md\"}"
```

Returns `{"ok", "kind", "cleaned": "<base64>", "report"}`. **You** decode
`cleaned` and write the output file — prefer `*.cleaned.*` unless the user asked
for in-place.

`options` (all optional):

| Option | Type | Applies to |
| --- | --- | --- |
| `nfkc` | bool | text |
| `aggressive_homoglyphs` | bool | text |
| `keep_non_ai_metadata` | bool | images, containers |
| `strip_all_metadata` | bool | images, containers |
| `remove_pixel` | `"ctrlregen"` \| `"diffusion"` | images |
| `also_layer_a_text` | bool | containers |
| `detect_before` / `detect_after` | bool | text, images |

If `report.warnings` is present, a tool was missing and the strip was degraded —
surface that to the user verbatim.

### Batch endpoints

**Cleaning 2+ files? Use the batch variant, not N single calls.**

```bash
curl -s -X POST "$WM/clean/batch" -H 'Content-Type: application/json' -d '{
  "files": [
    { "file": "SGVsbG8=", "name": "a.md" },
    { "file": "V29ybGQ=", "name": "b.png", "options": { "strip_all_metadata": true } }
  ]
}'
```

```json
{
  "ok": true,
  "results": [
    { "name": "a.md", "ok": true,  "kind": "text",  "cleaned": "...", "report": {} },
    { "name": "b.png", "ok": false, "error": "'file' is not valid base64" }
  ]
}
```

- `options` is **per file**, so one batch can mix a text file's `nfkc` with an
  image's `remove_pixel`.
- Capped at `WATERMARKS_MAX_BATCH_FILES` entries (default 50). Split larger sets.
- A bad entry becomes that entry's `"ok": false` and **never aborts the rest**.
  Always check each result's own `ok`, not only the top-level one.

---

## 4. Authentication

No key is required by default on loopback. Set one when the service is reachable
beyond `127.0.0.1`:

```bash
WATERMARKS_SERVER_API_KEY=... python3 service/scripts/server.py
```

Then every request except `/health` and `/readyz` needs:

```bash
curl -s "$WM/capabilities" -H "Authorization: Bearer $WATERMARKS_SERVER_API_KEY"
```

The server **refuses to bind a non-loopback host with no key set** — pass
`--allow-insecure-bind` only when the real access boundary is elsewhere (e.g. a
container port published as `127.0.0.1:<port>:<port>`).

---

## 5. Errors

| Status | Meaning |
| --- | --- |
| `400` | Bad request body — not JSON, missing `file`, invalid base64, unknown option, unrecognized format on `/clean` |
| `401` | Missing or wrong bearer token |
| `404` | Unknown path |
| `413` | Body over the size cap |
| `500` | Internal error (details are logged server-side, not returned) |
| `503` | Too many concurrent POSTs — back off and retry, do not hammer |

Every error body is `{"ok": false, "error": "..."}`.

---

## 6. Known limitations

Be honest about these. Do not let a clean result imply more than it proves.

- **Source code.** Layer A (invisible Unicode) is safe on code, but rewriting
  code to defeat statistical marks changes identifiers and comments — treat it
  as behavior-adjacent and get explicit consent.
- **Statistical / token-sampling watermarks.** Not removed by any deterministic
  endpoint. They need a rewrite pass by a model, which this service does not
  host. Best-effort, and never verifiable as "undetectable".
- **Binary metadata.** PDF strip is best-effort without `exiftool` and
  incomplete without `qpdf` — check `/readyz` before promising a clean PDF.
- **Advanced steganography.** Pixel-domain, audio, and video watermarks are out
  of scope unless a pixel backend is configured, and even then the result drifts
  the image. C2PA **soft binding** (re-links to a remote manifest after the
  metadata strip) is not cleared by stripping hard-bound C2PA.
- **Secret-key detectors and training backdoors** are out of scope entirely.

Never state that cleaned output "proves human authorship" or is
"undetectable". Report what was verifiably removed (counts, actions from
`report`) separately from what was best-effort.

---

## 7. Intended use

Content **you own** — privacy, hygiene, research. See
[`skills/remove-ai-marks/references/ethics.md`](skills/remove-ai-marks/references/ethics.md).
