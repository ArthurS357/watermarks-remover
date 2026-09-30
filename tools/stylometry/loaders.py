"""Format loaders: turn a file into prose or source for the detectors.

Plain text, markdown, HTML and code need only the standard library. ``.docx`` and ``.pdf`` need
the optional ``formats`` dependency group; without it ``load`` returns an ``UnsupportedFormat``
(a value, not an exception) so a directory scan can warn and move on.

Files are untrusted input. Reads are capped at the byte level, a DOCX is checked against what it
really decompresses to (the sizes in a zip directory are attacker-controlled), and DOCX/PDF text
is extracted in the killable worker process of ``isolate`` with a timeout.
"""

from __future__ import annotations

import codecs
import functools
import importlib
import lzma
import re
import tomllib
import zipfile
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from . import isolate

# extension -> (kind, language). ``language`` is what ``code.analyze`` expects for code.
FORMATS: dict[str, tuple[str, str]] = {
    ".md": ("text", "markdown"),
    ".txt": ("text", "text"),
    ".html": ("text", "html"),
    ".docx": ("text", "docx"),
    ".pdf": ("text", "pdf"),
    ".py": ("code", "python"),
    ".ts": ("code", "typescript"),
    ".tsx": ("code", "tsx"),
    ".js": ("code", "javascript"),
    ".jsx": ("code", "jsx"),
}

MAX_TEXT_BYTES = 1_000_000
MAX_BINARY_BYTES = 25_000_000
MAX_UNCOMPRESSED = 20_000_000  # what a DOCX may really decompress to
MAX_TEXT_CHARS = 1_000_000  # cap on text extracted from DOCX/PDF
MAX_PDF_PAGES = 200
MAX_PDF_STREAM = 5_000_000  # pypdf's own ceiling per decompressed stream is 75 MB
MAX_TOML_BYTES = 1_000_000
DOCX_TIMEOUT = 30.0
PDF_TIMEOUT = 30.0

INSTALL_HINT = "instale o grupo opcional: uv pip install --group formats"
PDF_NOTE = (
    "PDF: títulos, negrito e tabelas não sobrevivem à extração; sinais de markup não disparam"
)


@dataclass(frozen=True)
class Loaded:
    path: Path
    kind: str  # "text" | "code"
    language: str
    text: str
    confidence_cap: str = "high"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnsupportedFormat:
    path: Path
    reason: str


def format_of(path: Path) -> tuple[str, str] | None:
    return FORMATS.get(path.suffix.lower())


def load(path: Path) -> Loaded | UnsupportedFormat:
    """Read ``path`` for analysis. Never raises for a bad file: it returns ``UnsupportedFormat``."""
    try:
        return _load(path)
    except OSError as exc:
        return UnsupportedFormat(path, f"erro de leitura: {exc.strerror or type(exc).__name__}")


def _load(path: Path) -> Loaded | UnsupportedFormat:
    fmt = format_of(path)
    if fmt is None:
        return UnsupportedFormat(path, f"extensão não suportada: {path.suffix or '(nenhuma)'}")
    if not path.is_file():
        return UnsupportedFormat(path, "não é um arquivo")
    kind, language = fmt
    limit = MAX_BINARY_BYTES if language in ("docx", "pdf") else MAX_TEXT_BYTES
    too_big = UnsupportedFormat(path, f"arquivo maior que o limite ({limit} bytes)")
    if path.stat().st_size > limit:
        return too_big
    if language == "docx":
        return _load_docx(path)
    if language == "pdf":
        return _load_pdf(path)
    with path.open("rb") as handle:  # the real cap: the size can change after stat()
        data = handle.read(limit + 1)
    if len(data) > limit:
        return too_big
    utf16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    if not utf16 and b"\x00" in data[:8192]:
        return UnsupportedFormat(path, "conteúdo binário")
    text, notes = _decode(data, utf16)
    if language == "html":
        text = _html_to_text(text)
    return Loaded(path, kind, language, text, notes=notes)


def _decode(data: bytes, utf16: bool) -> tuple[str, tuple[str, ...]]:
    """UTF-8 (BOM dropped), UTF-16 with a BOM, or Windows-1252 as a last resort.

    A few bad bytes in otherwise valid UTF-8 are replaced in place: decoding the whole file as
    cp1252 would turn every em dash into three garbage characters and hide the very signals
    this tool looks for.
    """
    if utf16:
        return data.decode("utf-16", errors="replace"), ("decodificado como UTF-16 (BOM)",)
    text = data.decode("utf-8-sig", errors="replace")
    bad = text.count("�")
    if bad == 0:
        return text, ()
    if bad * 50 <= len(text):  # at most 2% damaged
        return text, (f"{bad} byte(s) inválido(s) em UTF-8 substituído(s)",)
    return data.decode("cp1252", errors="replace"), (
        "decodificado como cp1252 (não era UTF-8 válido)",
    )


def _missing(path: Path, module: str, package: str) -> UnsupportedFormat:
    return UnsupportedFormat(path, f"{package} ausente (import '{module}'); {INSTALL_HINT}")


def _require(module: str) -> Any | None:
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


def _cap(text: str) -> tuple[str, list[str]]:
    if len(text) <= MAX_TEXT_CHARS:
        return text, []
    return text[:MAX_TEXT_CHARS], [f"texto extraído truncado em {MAX_TEXT_CHARS} caracteres"]


# --- HTML --------------------------------------------------------------------------------------

_HEADINGS = {f"h{n}" for n in range(1, 7)}
_BLOCKS = {"p", "div", "section", "article", "header", "footer", "ul", "ol", "table", "blockquote"}
_SKIPPED = {"script", "style", "noscript", "template"}


class _TextExtractor(HTMLParser):
    """HTML to markdown-ish text, so headings, lists and tables reach the prose detectors."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skipping += 1
        elif tag in _HEADINGS:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "tr":
            self.parts.append("\n| ")
        elif tag in _BLOCKS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _HEADINGS or tag in _BLOCKS:
            self.parts.append("\n\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


# --- DOCX --------------------------------------------------------------------------------------


def _docx_paragraph(paragraph: Any) -> str:
    text: str = paragraph.text.strip()
    if not text:
        return ""
    style = paragraph.style  # read once, and only for paragraphs that have text
    name: str = (style.name if style is not None else "") or ""  # a style may have no name
    if name.startswith("Heading ") and name[8:].isdigit():
        return "#" * min(int(name[8:]), 6) + " " + text
    if name == "Title":
        return "# " + text
    return "- " + text if name.startswith("List") else text


def _docx_text(document: Any) -> str:
    paragraph_type = importlib.import_module("docx.text.paragraph").Paragraph
    table_type = importlib.import_module("docx.table").Table
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        if not isinstance(child.tag, str):  # an XML comment or processing instruction
            continue
        tag = child.tag.rpartition("}")[2]
        if tag == "p":
            blocks.append(_docx_paragraph(paragraph_type(child, document)))
        elif tag == "tbl":
            rows = table_type(child, document).rows
            blocks.append(
                "\n".join("| " + " | ".join(c.text.strip() for c in r.cells) + " |" for r in rows)
            )
    return "\n\n".join(b for b in blocks if b.strip()) + "\n"


def _docx_extract(path: str) -> list[Any]:
    """Worker entry point: ``[text, notes]``."""
    text, notes = _cap(_docx_text(importlib.import_module("docx").Document(path)))
    return [text, notes]


def _zip_refusal(path: Path) -> str | None:
    """Why a DOCX must not be opened, or ``None``. The sizes declared in a zip directory are
    attacker-controlled, so this counts what really decompresses, a megabyte at a time."""
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                with archive.open(info) as member:
                    while chunk := member.read(1 << 20):
                        total += len(chunk)
                        if total > MAX_UNCOMPRESSED:
                            return f"docx descomprime para mais de {MAX_UNCOMPRESSED} bytes"
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        return f"docx ilegível ({type(exc).__name__})"
    except (EOFError, zlib.error, lzma.LZMAError):  # a member's compressed data is damaged
        return "docx ilegível (dados comprimidos corrompidos)"
    return None


def _load_docx(path: Path) -> Loaded | UnsupportedFormat:
    if _require("docx") is None:
        return _missing(path, "docx", "python-docx")
    refusal = _zip_refusal(path)
    if refusal:
        return UnsupportedFormat(path, refusal)
    try:
        text, notes = isolate.call("stylometry.loaders:_docx_extract", [str(path)], DOCX_TIMEOUT)
    except TimeoutError:
        return UnsupportedFormat(path, f"docx excedeu {DOCX_TIMEOUT:g} s de extração")
    except (RuntimeError, OSError) as exc:  # IsolatedError is a RuntimeError
        return UnsupportedFormat(path, f"docx ilegível ({exc})")
    return Loaded(path, "text", "docx", text, notes=tuple(notes))


# --- PDF ---------------------------------------------------------------------------------------


_PDF_STREAM_LIMITS = (
    "zlib_maximum_output_length",
    "lzw_maximum_output_length",
    "run_length_maximum_output_length",
)


def _limit_pdf_streams(pypdf: Any) -> None:
    """Lower pypdf's ceiling on one decompressed stream (75 MB by default): a crafted stream
    must not fill the worker's RAM. ``pypdf.Configuration`` is the current API; the module-level
    constant it replaces is deprecated and is only used when ``Configuration`` does not exist."""
    config = getattr(pypdf, "Configuration", None)
    if config is not None:
        for name in _PDF_STREAM_LIMITS:
            if hasattr(config, name):
                setattr(config, name, MAX_PDF_STREAM)
        return
    filters = getattr(pypdf, "filters", None)
    if filters is not None and hasattr(filters, "ZLIB_MAX_OUTPUT_LENGTH"):
        filters.ZLIB_MAX_OUTPUT_LENGTH = MAX_PDF_STREAM


def _pdf_extract(path: str, max_pages: int) -> list[Any]:
    """Worker entry point: ``["ok", text, notes]`` or ``["skip", reason]``."""
    pypdf = importlib.import_module("pypdf")
    _limit_pdf_streams(pypdf)
    reader = pypdf.PdfReader(path)
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:  # pypdf raises DependencyError for AES without cryptography
            if type(exc).__name__ == "DependencyError":
                return ["skip", "PDF criptografado com AES; requer o pacote 'cryptography'"]
            return ["skip", f"PDF criptografado ({type(exc).__name__})"]
        if not unlocked:
            return ["skip", "PDF criptografado"]
    total = len(reader.pages)
    take = min(total, max_pages)
    text, notes = _cap("\n\n".join(reader.pages[i].extract_text() or "" for i in range(take)))
    if take < total:
        notes.append(f"PDF truncado: {take} de {total} páginas")
    return ["ok", text, notes]


def _load_pdf(path: Path) -> Loaded | UnsupportedFormat:
    if _require("pypdf") is None:
        return _missing(path, "pypdf", "pypdf")
    try:
        result = isolate.call(
            "stylometry.loaders:_pdf_extract", [str(path), MAX_PDF_PAGES], PDF_TIMEOUT
        )
    except TimeoutError:
        return UnsupportedFormat(path, f"PDF excedeu {PDF_TIMEOUT:g} s de extração")
    except (RuntimeError, OSError) as exc:  # IsolatedError is a RuntimeError
        return UnsupportedFormat(path, f"PDF ilegível ({exc})")
    if result[0] == "skip":
        return UnsupportedFormat(path, result[1])
    return Loaded(path, "text", "pdf", result[1], "medium", (PDF_NOTE, *result[2]))


# --- project context ---------------------------------------------------------------------------

_REQUIRES = re.compile(r"(?:>=|~=|==)\s*(\d+)\.(\d+)")


@functools.cache
def find_requires_python(start: Path) -> tuple[int, int] | None:
    """Lower bound of ``requires-python`` in the nearest ``pyproject.toml`` at or above ``start``
    (a directory). ``None`` when there is none, it has no bound, or it cannot be read: a
    ``pyproject.toml`` in the scanned tree is input like any other file."""
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if not candidate.is_file():
            continue
        try:
            with candidate.open("rb") as handle:
                raw = handle.read(MAX_TOML_BYTES + 1)
            if len(raw) > MAX_TOML_BYTES:
                return None
            data = tomllib.loads(raw.decode("utf-8"))
            project = data.get("project")
            spec = project.get("requires-python") if isinstance(project, dict) else None
            found = _REQUIRES.search(spec) if isinstance(spec, str) else None
            return (int(found[1]), int(found[2])) if found else None
        except (OSError, ValueError, RecursionError):  # ValueError: bad UTF-8, TOML, huge int
            return None
    return None
