"""Tests for tools/stylometry/loaders.py (format loaders and project context)."""

from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stylometry import isolate, loaders
from stylometry import text as st
from stylometry.loaders import Loaded, UnsupportedFormat
from stylometry_support import in_process


@pytest.fixture
def real_worker():
    """Ask for this fixture to keep the real worker process instead of the in-process stand-in."""
    return None


@pytest.fixture(autouse=True)
def _worker_code_in_process(request, monkeypatch):
    if "real_worker" not in request.fixturenames:
        monkeypatch.setattr(isolate, "call", in_process)


def write(tmp_path: Path, name: str, data: str | bytes) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, never write_text: on Windows it would turn "\n" into "\r\n" under our feet.
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def fake_missing(monkeypatch, *modules: str):
    real = loaders.importlib.import_module

    def import_module(name, *args, **kwargs):
        if name in modules:
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(loaders.importlib, "import_module", import_module)


def worker_raises(monkeypatch, exc: Exception):
    def boom(*args):
        raise exc

    monkeypatch.setattr(isolate, "call", boom)


# --- which extension means what ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        (".md", ("text", "markdown")),
        (".txt", ("text", "text")),
        (".html", ("text", "html")),
        (".docx", ("text", "docx")),
        (".pdf", ("text", "pdf")),
        (".py", ("code", "python")),
        (".ts", ("code", "typescript")),
        (".tsx", ("code", "tsx")),
        (".js", ("code", "javascript")),
        (".jsx", ("code", "jsx")),
        (".MD", ("text", "markdown")),
    ],
)
def test_format_of_follows_the_extension(suffix, expected):
    assert loaders.format_of(Path(f"file{suffix}")) == expected


@pytest.mark.parametrize("name", ["a.exe", "a.png", "README", "a.md.bak", "a.rs"])
def test_format_of_ignores_everything_else(name):
    assert loaders.format_of(Path(name)) is None


# --- plain text and code ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind", "language"),
    [
        ("a.md", "text", "markdown"),
        ("a.txt", "text", "text"),
        ("a.py", "code", "python"),
        ("a.ts", "code", "typescript"),
        ("a.tsx", "code", "tsx"),
        ("a.js", "code", "javascript"),
        ("a.jsx", "code", "jsx"),
    ],
)
def test_reads_text_and_code_files(tmp_path, name, kind, language):
    loaded = loaders.load(write(tmp_path, name, "olá, mundo\n"))
    assert isinstance(loaded, Loaded)
    assert (loaded.kind, loaded.language) == (kind, language)
    assert loaded.text == "olá, mundo\n"
    assert loaded.confidence_cap == "high"
    assert loaded.notes == ()


def test_utf8_bom_is_dropped(tmp_path):
    loaded = loaders.load(write(tmp_path, "a.md", b"\xef\xbb\xbfcom bom"))
    assert isinstance(loaded, Loaded)
    assert loaded.text == "com bom"


def test_non_utf8_text_falls_back_to_cp1252_with_a_note(tmp_path):
    loaded = loaders.load(write(tmp_path, "a.txt", "ação é isso".encode("cp1252")))
    assert isinstance(loaded, Loaded)
    assert loaded.text == "ação é isso"
    assert any("cp1252" in n for n in loaded.notes)


def test_a_few_bad_bytes_do_not_push_valid_utf8_prose_into_cp1252(tmp_path):
    # One stray byte used to send the whole file through cp1252, turning every em dash into
    # three garbage characters and silencing the em-dash signals.
    prose = ("texto com travessão — e mais texto. " * 10).encode("utf-8")
    loaded = loaders.load(write(tmp_path, "a.md", prose + b"\xff" + prose))
    assert isinstance(loaded, Loaded)
    assert loaded.text.count("—") == 20
    assert any("inválido" in n for n in loaded.notes)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be"])
def test_utf16_with_a_bom_is_decoded_not_called_binary(tmp_path, encoding):
    data = b"\xfe\xff" + "olá — mundo\n".encode(encoding) if encoding.endswith("be") else None
    data = data or "olá — mundo\n".encode(encoding)  # "utf-16" writes the BOM itself
    loaded = loaders.load(write(tmp_path, "a.txt", data))
    assert isinstance(loaded, Loaded)
    assert loaded.text == "olá — mundo\n"
    assert any("UTF-16" in n for n in loaded.notes)


def test_binary_content_is_skipped(tmp_path):
    result = loaders.load(write(tmp_path, "a.txt", b"abc\x00def"))
    assert isinstance(result, UnsupportedFormat)
    assert "binário" in result.reason


def test_oversized_text_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(loaders, "MAX_TEXT_BYTES", 10)
    result = loaders.load(write(tmp_path, "a.md", "x" * 11))
    assert isinstance(result, UnsupportedFormat)
    assert "maior" in result.reason


def test_the_read_itself_is_capped_even_if_stat_lies(tmp_path, monkeypatch):
    # A file that grows between stat() and read(), or a pseudo-file with st_size 0.
    path = write(tmp_path, "a.md", "x" * 50)
    monkeypatch.setattr(loaders, "MAX_TEXT_BYTES", 10)

    class Tiny:
        st_size = 1

    monkeypatch.setattr(Path, "stat", lambda self, **kwargs: Tiny())
    result = loaders.load(path)
    assert isinstance(result, UnsupportedFormat)
    assert "maior" in result.reason


def test_oversized_binary_formats_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(loaders, "MAX_BINARY_BYTES", 10)
    for name in ("a.docx", "a.pdf"):
        result = loaders.load(write(tmp_path, name, b"x" * 11))
        assert isinstance(result, UnsupportedFormat)
        assert "maior" in result.reason


def test_read_errors_become_unsupported(tmp_path, monkeypatch):
    path = write(tmp_path, "a.md", "x")

    def denied(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "open", denied)
    result = loaders.load(path)
    assert isinstance(result, UnsupportedFormat)
    assert "leitura" in result.reason


@pytest.mark.parametrize("name", ["missing.md", "folder.md"])
def test_missing_path_and_directory_are_skipped_not_raised(tmp_path, name):
    (tmp_path / "folder.md").mkdir()
    result = loaders.load(tmp_path / name)
    assert isinstance(result, UnsupportedFormat)


def test_unknown_extension_is_skipped(tmp_path):
    result = loaders.load(write(tmp_path, "a.rs", "fn main() {}"))
    assert isinstance(result, UnsupportedFormat)
    assert "extensão" in result.reason


# --- HTML -------------------------------------------------------------------------------------

HTML = """\
<html><head><title>T</title><style>p { color: red }</style>
<script>var x = "vale notar";</script></head>
<body>
<h2>Why it matters</h2>
<p>First &amp; foremost, <b>bold</b> text.</p>
<ul><li>one</li><li>two</li></ul>
<table><tr><th>a</th><th>b</th></tr><tr><td>c</td><td>d</td></tr></table>
<p>Second<br>line</p>
</body></html>
"""


def test_html_keeps_structure_and_drops_script_and_style(tmp_path):
    loaded = loaders.load(write(tmp_path, "a.html", HTML))
    assert isinstance(loaded, Loaded)
    text = loaded.text
    assert "## Why it matters" in text
    assert "First & foremost, bold text." in text
    assert "\n- one\n- two" in text
    assert "| a | b |" in text
    assert "| c | d |" in text
    assert "Second\nline" in text
    assert "color: red" not in text
    assert "vale notar" not in text


def test_html_headings_feed_the_text_detector(tmp_path):
    loaded = loaders.load(write(tmp_path, "a.html", "<h2>Why it matters</h2><p>text</p>"))
    assert isinstance(loaded, Loaded)
    assert "template_heading" in {s.name for s in st.analyze(loaded.text).signals}


def test_malformed_and_deeply_nested_html_does_not_raise(tmp_path):
    for html in ("<div><p>unclosed <b>tags", "</p></div><<>>&", "<div>" * 20_000 + "x"):
        assert isinstance(loaders.load(write(tmp_path, "a.html", html)), Loaded)


# --- optional formats without their libraries -------------------------------------------------


@pytest.mark.parametrize(
    ("name", "module"), [("a.docx", "docx"), ("a.pdf", "pypdf")], ids=["docx", "pdf"]
)
def test_missing_library_returns_unsupported_with_the_install_hint(
    tmp_path, monkeypatch, name, module
):
    fake_missing(monkeypatch, module)
    result = loaders.load(write(tmp_path, name, b"PK\x03\x04 not really"))
    assert isinstance(result, UnsupportedFormat)
    assert module in result.reason
    assert "--group formats" in result.reason


# --- DOCX (needs python-docx) -----------------------------------------------------------------


def make_docx(path: Path) -> Path:
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_heading("Why it matters", level=1)
    doc.add_paragraph("First paragraph.")
    doc.add_paragraph("an item", style="List Bullet")
    table = doc.add_table(rows=2, cols=2)
    for r, row in enumerate((("a", "b"), ("c", "d"))):
        for c, cell in enumerate(row):
            table.cell(r, c).text = cell
    doc.add_paragraph("Last paragraph.")
    doc.save(path)
    return path


def lines_of(loaded) -> list[str]:
    assert isinstance(loaded, Loaded)
    return [line for line in loaded.text.splitlines() if line]


def test_docx_keeps_headings_lists_and_tables_in_order(tmp_path):
    loaded = loaders.load(make_docx(tmp_path / "a.docx"))
    assert lines_of(loaded) == [
        "# Why it matters",
        "First paragraph.",
        "- an item",
        "| a | b |",
        "| c | d |",
        "Last paragraph.",
    ]
    assert loaded.confidence_cap == "high"


def test_docx_goes_through_the_real_worker_process(tmp_path, real_worker):
    loaded = loaders.load(make_docx(tmp_path / "a.docx"))
    assert lines_of(loaded)[0] == "# Why it matters"


def test_docx_title_style_and_empty_paragraphs(tmp_path):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("A Title", style="Title")
    doc.add_paragraph("")
    doc.add_paragraph("Body")
    doc.save(tmp_path / "t.docx")
    assert lines_of(loaders.load(tmp_path / "t.docx")) == ["# A Title", "Body"]


def test_docx_with_an_xml_comment_and_a_nameless_style_is_still_read(tmp_path):
    docx = pytest.importorskip("docx")
    lxml_etree = pytest.importorskip("lxml.etree")
    doc = docx.Document()
    style = doc.styles.add_style("Temp", 1)
    doc.add_paragraph("styled text", style="Temp")
    doc.add_paragraph("plain text")
    style.element._remove_name()  # a valid package can carry a style with no <w:name>
    doc.element.body.insert(0, lxml_etree.Comment("a comment node has a function as its tag"))
    doc.save(tmp_path / "odd.docx")
    assert lines_of(loaders.load(tmp_path / "odd.docx")) == ["styled text", "plain text"]


def test_corrupt_docx_is_skipped(tmp_path):
    pytest.importorskip("docx")
    result = loaders.load(write(tmp_path, "a.docx", b"this is not a zip"))
    assert isinstance(result, UnsupportedFormat)
    assert "docx" in result.reason


def test_docx_with_no_zip_members_is_skipped(tmp_path):
    pytest.importorskip("docx")
    path = tmp_path / "a.docx"
    with zipfile.ZipFile(path, "w"):
        pass
    result = loaders.load(path)
    assert isinstance(result, UnsupportedFormat)
    assert "docx ilegível" in result.reason


def test_docx_that_decompresses_past_the_limit_is_refused(tmp_path, monkeypatch):
    make_docx(tmp_path / "a.docx")
    monkeypatch.setattr(loaders, "MAX_UNCOMPRESSED", 10)
    result = loaders.load(tmp_path / "a.docx")
    assert isinstance(result, UnsupportedFormat)
    assert "descomprime" in result.reason


def lying_bomb(path: Path, real_bytes: int) -> Path:
    """A zip whose directory claims 100 bytes for a member that really expands to ``real_bytes``."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"\0" * real_bytes)
    data = bytearray(path.read_bytes())
    central = data.rindex(b"PK\x01\x02")
    data[central + 24 : central + 28] = struct.pack("<I", 100)  # uncompressed size field
    path.write_bytes(bytes(data))
    return path


def test_a_zip_directory_that_lies_about_sizes_never_reaches_python_docx(tmp_path, monkeypatch):
    pytest.importorskip("docx")
    bomb = lying_bomb(tmp_path / "bomb.docx", 5_000_000)
    monkeypatch.setattr(loaders, "MAX_UNCOMPRESSED", 1_000_000)
    worker_raises(monkeypatch, AssertionError("python-docx must not be called on a bomb"))
    result = loaders.load(bomb)
    assert isinstance(result, UnsupportedFormat)
    assert "docx" in result.reason


def test_docx_text_is_capped_with_a_note(tmp_path, monkeypatch):
    make_docx(tmp_path / "a.docx")
    monkeypatch.setattr(loaders, "MAX_TEXT_CHARS", 20)
    loaded = loaders.load(tmp_path / "a.docx")
    assert isinstance(loaded, Loaded)
    assert len(loaded.text) == 20
    assert any("truncado" in n for n in loaded.notes)


def test_docx_worker_failures_become_skips_with_the_reason(tmp_path, monkeypatch):
    pytest.importorskip("docx")
    path = make_docx(tmp_path / "a.docx")
    worker_raises(monkeypatch, isolate.IsolatedError("KeyError: 'word/document.xml'"))
    result = loaders.load(path)
    assert isinstance(result, UnsupportedFormat)
    assert "docx ilegível (KeyError" in result.reason
    worker_raises(monkeypatch, TimeoutError("excedeu"))
    result = loaders.load(path)
    assert isinstance(result, UnsupportedFormat)
    assert "excedeu" in result.reason


# --- PDF (needs pypdf) ------------------------------------------------------------------------


def make_pdf(text: str) -> bytes:
    """A one-page PDF with a correct xref table, so pypdf reads it without repair."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


PDF = make_pdf("Hello world")


def test_pdf_text_is_extracted_and_confidence_is_capped(tmp_path):
    pytest.importorskip("pypdf")
    loaded = loaders.load(write(tmp_path, "a.pdf", PDF))
    assert isinstance(loaded, Loaded)
    assert "Hello world" in loaded.text
    assert loaded.confidence_cap == "medium"
    assert any("PDF" in n for n in loaded.notes)


def test_pdf_goes_through_the_real_worker_process(tmp_path, real_worker):
    pytest.importorskip("pypdf")
    loaded = loaders.load(write(tmp_path, "a.pdf", PDF))
    assert isinstance(loaded, Loaded)
    assert "Hello world" in loaded.text


def test_encrypted_pdf_is_skipped(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("secret", algorithm="RC4-128")
    with (tmp_path / "a.pdf").open("wb") as handle:
        writer.write(handle)
    result = loaders.load(tmp_path / "a.pdf")
    assert isinstance(result, UnsupportedFormat)
    assert result.reason == "PDF criptografado"


def test_owner_password_only_pdf_opens_with_an_empty_user_password(tmp_path):
    # The common "no copy, no print" PDF: encrypted, but readable without asking for anything.
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("", "owner-secret", algorithm="RC4-128")
    with (tmp_path / "a.pdf").open("wb") as handle:
        writer.write(handle)
    assert isinstance(loaders.load(tmp_path / "a.pdf"), Loaded)


@pytest.mark.parametrize(
    ("error_name", "expected"),
    [("DependencyError", "cryptography"), ("ValueError", "ValueError")],
    ids=["aes-needs-cryptography", "other"],
)
def test_encrypted_pdf_whose_decryption_raises_gets_a_specific_reason(
    tmp_path, monkeypatch, error_name, expected
):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("secret", algorithm="RC4-128")
    with (tmp_path / "a.pdf").open("wb") as handle:
        writer.write(handle)

    def decrypt(self, password):
        raise type(error_name, (Exception,), {})("needs a library")

    monkeypatch.setattr(pypdf.PdfReader, "decrypt", decrypt)
    result = loaders.load(tmp_path / "a.pdf")
    assert isinstance(result, UnsupportedFormat)
    assert expected in result.reason
    assert "criptografado" in result.reason


def test_garbage_pdf_is_skipped_with_the_error_name(tmp_path):
    pytest.importorskip("pypdf")
    result = loaders.load(write(tmp_path, "a.pdf", b"%PDF-1.4 total garbage"))
    assert isinstance(result, UnsupportedFormat)
    assert "PDF ilegível" in result.reason


def test_pdf_page_cap_adds_a_note(tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(100, 100)
    with (tmp_path / "a.pdf").open("wb") as handle:
        writer.write(handle)
    monkeypatch.setattr(loaders, "MAX_PDF_PAGES", 2)
    loaded = loaders.load(tmp_path / "a.pdf")
    assert isinstance(loaded, Loaded)
    assert any("2 de 3" in n for n in loaded.notes)


def test_pdf_stream_ceiling_is_lowered_inside_the_worker(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    config = getattr(pypdf, "Configuration", None)
    if config is None or not hasattr(config, "zlib_maximum_output_length"):
        pytest.skip("this pypdf predates Configuration; the legacy path has its own test")
    before = {n: getattr(config, n) for n in loaders._PDF_STREAM_LIMITS if hasattr(config, n)}
    try:
        loaders._pdf_extract(str(write(tmp_path, "a.pdf", PDF)), 5)
        assert all(getattr(config, n) == loaders.MAX_PDF_STREAM for n in before)
    finally:
        for name, value in before.items():
            setattr(config, name, value)


def test_limit_pdf_streams_handles_old_new_and_unknown_pypdf_layouts():
    new = SimpleNamespace(
        Configuration=SimpleNamespace(
            zlib_maximum_output_length=1, lzw_maximum_output_length=1, other=1
        )
    )
    loaders._limit_pdf_streams(new)
    assert new.Configuration.zlib_maximum_output_length == loaders.MAX_PDF_STREAM
    assert new.Configuration.lzw_maximum_output_length == loaders.MAX_PDF_STREAM
    assert new.Configuration.other == 1  # only the known stream limits are touched
    legacy = SimpleNamespace(filters=SimpleNamespace(ZLIB_MAX_OUTPUT_LENGTH=1))
    loaders._limit_pdf_streams(legacy)
    assert legacy.filters.ZLIB_MAX_OUTPUT_LENGTH == loaders.MAX_PDF_STREAM
    loaders._limit_pdf_streams(SimpleNamespace())  # neither layout: nothing to lower, no error
    loaders._limit_pdf_streams(SimpleNamespace(filters=SimpleNamespace()))


def test_pdf_worker_failures_become_skips_with_the_reason(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    path = write(tmp_path, "a.pdf", PDF)
    worker_raises(monkeypatch, TimeoutError("excedeu 30 s"))
    result = loaders.load(path)
    assert isinstance(result, UnsupportedFormat)
    assert "excedeu" in result.reason
    worker_raises(monkeypatch, isolate.IsolatedError("PdfReadError: EOF marker not found"))
    result = loaders.load(path)
    assert isinstance(result, UnsupportedFormat)
    assert "PdfReadError" in result.reason


# --- requires-python --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_requires_cache():
    loaders.find_requires_python.cache_clear()
    yield
    loaders.find_requires_python.cache_clear()


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (">=3.14", (3, 14)),
        (">=3.12,<4", (3, 12)),
        ("~=3.13", (3, 13)),
        (">= 3.10", (3, 10)),
        ("<4", None),
        ("nonsense", None),
    ],
)
def test_find_requires_python_reads_the_lower_bound(tmp_path, spec, expected):
    write(tmp_path, "pyproject.toml", f'[project]\nname = "x"\nrequires-python = "{spec}"\n')
    (tmp_path / "pkg").mkdir()
    assert loaders.find_requires_python(tmp_path / "pkg") == expected


def test_find_requires_python_uses_the_nearest_pyproject_and_tolerates_bad_ones(tmp_path):
    (tmp_path / "inner").mkdir()
    write(tmp_path, "pyproject.toml", '[project]\nname = "outer"\nrequires-python = ">=3.14"\n')
    assert loaders.find_requires_python(tmp_path / "inner") == (3, 14)  # inherited from the parent
    loaders.find_requires_python.cache_clear()
    write(tmp_path, "inner/pyproject.toml", '[dependency-groups]\nformats = ["x"]\n')
    assert loaders.find_requires_python(tmp_path / "inner") is None  # the nearest one wins


@pytest.mark.parametrize(
    "content",
    [
        b"this is [not toml",
        b"a = " + b"[" * 100_000 + b"]" * 100_000,  # RecursionError inside tomllib
        b'[project]\nrequires-python = ">=' + b"1" * 5000 + b'.1"\n',  # int() digit limit
        b"\xff\xfe\x00 not utf-8",
        b"[project]\nrequires-python = 3\n",
        b'project = "not a table"\n',
    ],
    ids=["bad-toml", "recursion", "huge-int", "bad-utf8", "wrong-type", "project-not-a-table"],
)
def test_a_hostile_pyproject_yields_none_instead_of_raising(tmp_path, content):
    write(tmp_path, "pyproject.toml", content)
    assert loaders.find_requires_python(tmp_path) is None


def test_an_oversized_pyproject_is_ignored(tmp_path, monkeypatch):
    write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.14"\n')
    monkeypatch.setattr(loaders, "MAX_TOML_BYTES", 10)
    assert loaders.find_requires_python(tmp_path) is None


def test_find_requires_python_without_any_pyproject(tmp_path):
    if any((p / "pyproject.toml").exists() for p in tmp_path.parents):
        pytest.skip("an ancestor of the temp dir has a pyproject.toml")
    assert loaders.find_requires_python(tmp_path / "nowhere") is None
