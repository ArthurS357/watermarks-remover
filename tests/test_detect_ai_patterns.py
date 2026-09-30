"""Tests for tools/detect_ai_patterns.py (the CLI over the stylometry package)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "detect_ai_patterns.py"
FIXTURES = ROOT / "tests" / "fixtures" / "stylometry"
sys.path.insert(0, str(TOOLS))

import detect_ai_patterns as cli
from stylometry import DISCLAIMER, SEVERITIES, isolate, loaders, printable
from stylometry_support import in_process

AI_TEXT = (FIXTURES / "text_ai_like.md").read_text(encoding="utf-8")
HUMAN_TEXT = (FIXTURES / "text_human_like.md").read_text(encoding="utf-8")
AI_PY = (FIXTURES / "code_ai_like.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _worker_code_in_process(monkeypatch):
    monkeypatch.setattr(isolate, "call", in_process)


def put(tmp_path: Path, name: str, content: str | bytes) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def run(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv)
    return code, json.loads(out), err


def keys_anywhere(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys_anywhere(v)
    elif isinstance(value, list):
        for item in value:
            yield from keys_anywhere(item)


@pytest.fixture
def tree(tmp_path):
    put(tmp_path, "docs/guide.md", AI_TEXT)
    put(tmp_path, "docs/human.md", HUMAN_TEXT)
    put(tmp_path, "notes.txt", "vale notar que sim. " * 30)
    put(tmp_path, "pkg/mod.py", AI_PY)
    put(tmp_path, "web/app.ts", 'const a = "x" as const;\n' * 4)
    put(tmp_path, "data.json", "{}")
    put(tmp_path, "image.png", b"\x89PNG\x00")
    return tmp_path


# --- output contract ---------------------------------------------------------------------------


def test_json_report_has_the_documented_shape(tree, capsys):
    code, report, _ = run_json(capsys, tree)
    assert code == 0
    assert set(report) == {
        "files_scanned",
        "by_format",
        "by_signal",
        "scores",
        "skipped",
        "disclaimer",
    }
    assert report["disclaimer"] == DISCLAIMER
    assert report["files_scanned"] == 5
    assert report["by_format"] == {"markdown": 2, "python": 1, "text": 1, "typescript": 1}
    entry = report["scores"]["docs/guide.md"]
    assert set(entry) == {"format", "kind", "score", "confidence", "signals", "notes"}
    assert 0.0 <= entry["score"] <= 1.0
    assert entry["confidence"] in ("low", "medium", "high")
    assert set(entry["signals"][0]) == {"name", "value", "severity", "line", "snippet"}
    assert report["by_signal"]["bold_lead_in"]["files"] == 1


def test_the_output_never_claims_a_verdict(tree, capsys):
    _, report, _ = run_json(capsys, tree)
    forbidden = {"is_ai", "is_ai_generated", "ai", "verdict", "generated_by_ai"}
    assert not forbidden & set(keys_anywhere(report))
    _, md, _ = run(capsys, tree, "--format", "md")
    assert "is_ai" not in md
    assert DISCLAIMER in md


def test_keys_are_relative_posix_paths_and_the_order_is_stable(tree, capsys):
    _, first, _ = run_json(capsys, tree)
    _, second, _ = run_json(capsys, tree)
    assert list(first["scores"]) == list(second["scores"])
    assert list(first["scores"]) == sorted(first["scores"])
    assert all("\\" not in k and not Path(k).is_absolute() for k in first["scores"])


def test_a_single_file_is_keyed_by_its_name(tree, capsys):
    code, report, _ = run_json(capsys, tree / "docs" / "guide.md")
    assert code == 0
    assert list(report["scores"]) == ["guide.md"]


def test_ai_like_outscores_human_like(tree, capsys):
    _, report, _ = run_json(capsys, tree / "docs")
    scores = {k: v["score"] for k, v in report["scores"].items()}
    assert scores["guide.md"] > scores["human.md"] + 0.4


# --- choosing files ----------------------------------------------------------------------------


def test_default_ignores_skip_dependency_and_cache_trees(tmp_path, capsys):
    put(tmp_path, "keep.md", AI_TEXT)
    for ignored in (
        ".venv/lib/x.md",
        "node_modules/y.md",
        "__pycache__/z.md",
        ".git/w.md",
        "build/b.md",
    ):
        put(tmp_path, ignored, AI_TEXT)
    _, report, _ = run_json(capsys, tmp_path)
    assert list(report["scores"]) == ["keep.md"]


def test_ignore_is_repeatable_and_matches_paths_and_names(tree, capsys):
    _, report, _ = run_json(capsys, tree, "--ignore", "docs/*", "--ignore", "*.txt")
    assert sorted(report["scores"]) == ["pkg/mod.py", "web/app.ts"]


def test_ignore_prunes_whole_directories(tree, capsys):
    _, report, _ = run_json(capsys, tree, "--ignore", "docs")
    assert not any(k.startswith("docs/") for k in report["scores"])


@pytest.mark.parametrize(
    ("only", "kinds"), [("text", {"text"}), ("code", {"code"}), ("all", {"text", "code"})]
)
def test_only_selects_prose_or_code(tree, capsys, only, kinds):
    _, report, _ = run_json(capsys, tree, "--only", only)
    assert {v["kind"] for v in report["scores"].values()} == kinds


def test_exclude_tests_skips_test_files_and_folders(tmp_path, capsys):
    for name in (
        "src/app.py",
        "src/test_helper.py",
        "src/app_test.py",
        "src/conftest.py",
        "tests/test_a.py",
        "tests/fixtures/ai.md",
        "src/ui.test.ts",
        "src/ui.spec.tsx",
        "src/ui.ts",
    ):
        put(tmp_path, name, "x = 1\n")
    _, everything, _ = run_json(capsys, tmp_path)
    _, report, _ = run_json(capsys, tmp_path, "--exclude-tests")
    assert len(everything["scores"]) == 9  # tests/fixtures/ai.md is prose, the rest code
    assert sorted(report["scores"]) == ["src/app.py", "src/ui.ts"]


def test_symlinks_are_never_followed(tmp_path, capsys):
    target = put(tmp_path, "real.md", AI_TEXT)
    try:
        (tmp_path / "link.md").symlink_to(target)
        (tmp_path / "linkdir").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need a privilege this environment does not grant")
    _, report, _ = run_json(capsys, tmp_path)
    assert list(report["scores"]) == ["real.md"]


def test_ntfs_junctions_are_never_followed(tmp_path, capsys):
    # os.walk(followlinks=False) still descends into a junction: islink() is False for one
    if sys.platform != "win32":
        pytest.skip("junctions are an NTFS thing")
    put(tmp_path, "tree/a.md", AI_TEXT)
    put(tmp_path, "outside/b.md", AI_TEXT)
    made = subprocess.run(
        [
            os.environ["COMSPEC"],
            *("/c", "mklink", "/J", str(tmp_path / "tree" / "link"), str(tmp_path / "outside")),
        ],
        capture_output=True,
        check=False,
    )
    assert made.returncode == 0, "mklink /J needs no privilege; the environment is broken"
    _, report, _ = run_json(capsys, tmp_path / "tree")
    assert list(report["scores"]) == ["a.md"]


def test_a_directory_reported_as_a_junction_is_skipped_on_any_platform(
    tmp_path, capsys, monkeypatch
):
    put(tmp_path, "ok/y.md", AI_TEXT)
    put(tmp_path, "jct/x.md", AI_TEXT)
    is_junction = os.path.isjunction
    monkeypatch.setattr(os.path, "isjunction", lambda p: Path(p).name == "jct" or is_junction(p))
    _, report, _ = run_json(capsys, tmp_path)
    assert list(report["scores"]) == ["ok/y.md"]


# --- names that reach a terminal or a report -----------------------------------------------------

HOSTILE = (
    "a\x1b[31m`b`\n.md"  # a POSIX file name can carry an escape sequence, a backtick, a newline
)


def test_printable_replaces_control_characters_and_nothing_else():
    assert printable("a\x1b[2Jb\x07\x9bc\td") == "a?[2Jb??c?d"
    assert printable("ação — ok.md") == "ação — ok.md"


def test_a_hostile_file_name_never_reaches_the_markdown_report_raw():
    analysis = cli.text_signals.analyze(AI_TEXT)
    scanned = cli.Scan(
        files={
            HOSTILE: cli.FileResult(HOSTILE, "markdown", "text", 0.9, "low", analysis.signals, [])
        },
        skipped=[(HOSTILE, "boom\x1b[2J")],
    )
    report = cli.render_md(scanned, "low")
    assert "\x1b" not in report
    assert "`a?[31m'b'?.md`" in report  # one code span: backticks became quotes, \n became ?
    assert report.count("`a?[31m'b'?.md`") == 2  # the ranking heading and the skipped list


def test_a_hostile_file_name_never_reaches_the_terminal_raw(tmp_path, capsys, monkeypatch):
    put(tmp_path, "ok.md", AI_TEXT)
    ghost = tmp_path.resolve() / HOSTILE
    monkeypatch.setattr(cli, "iter_files", lambda root, options: iter([ghost]))
    monkeypatch.setattr(
        loaders, "load", lambda path: loaders.UnsupportedFormat(path, "boom\x1b[2J")
    )
    code, _, err = run(capsys, tmp_path)
    assert code == 2
    assert "\x1b" not in err
    assert "a?[31m`b`?.md" in err and "boom?[2J" in err


# --- severity filter ---------------------------------------------------------------------------


def test_min_severity_hides_signals_but_never_changes_the_score(tree, capsys):
    _, everything, _ = run_json(capsys, tree)
    _, high_only, _ = run_json(capsys, tree, "--min-severity", "high")
    for name, entry in high_only["scores"].items():
        assert entry["score"] == everything["scores"][name]["score"]
        assert {s["severity"] for s in entry["signals"]} <= {"high"}
    assert {s["severity"] for e in everything["scores"].values() for s in e["signals"]} > {"high"}
    assert all(i["max_severity"] == "high" for i in high_only["by_signal"].values())


@pytest.mark.parametrize("floor", SEVERITIES)
def test_min_severity_is_a_floor(tree, capsys, floor):
    _, report, _ = run_json(capsys, tree, "--min-severity", floor)
    order = SEVERITIES.index(floor)
    for entry in report["scores"].values():
        assert all(SEVERITIES.index(s["severity"]) >= order for s in entry["signals"])


# --- markdown report ---------------------------------------------------------------------------


def test_markdown_report_is_readable_and_lists_lines(tree, capsys):
    code, out, _ = run(capsys, tree, "--format", "md")
    assert code == 0
    assert out.startswith("# Relatório estilométrico")
    assert DISCLAIMER in out
    assert "## Sinais mais frequentes" in out
    assert "### 1. `docs/guide.md`" in out  # highest score first
    assert "`bold_lead_in`" in out
    assert "linha 21:" in out
    assert "documento:" in out  # metrics have no line


def test_markdown_lists_only_the_top_ten_files(tmp_path, capsys):
    for i in range(12):
        put(tmp_path, f"doc{i:02d}.md", AI_TEXT)
    _, out, _ = run(capsys, tmp_path, "--format", "md")
    assert out.count("\n### ") == 10
    assert "Top 10 arquivos" in out


def test_markdown_caps_locations_per_signal_and_escapes_backticks(tmp_path, capsys):
    text = "".join(f"- **Termo{i}** — a `code` detail.\n" for i in range(12))
    put(tmp_path, "a.md", text)
    _, out, _ = run(capsys, tmp_path, "--format", "md")
    assert "(+7)" in out  # 12 lead-ins, 5 shown
    assert "`code`" not in out.split("bold_lead_in")[1].split("\n")[0]  # inner backticks replaced


def test_markdown_with_no_signals_says_so(tmp_path, capsys):
    put(tmp_path, "clean.md", HUMAN_TEXT)
    _, out, _ = run(capsys, tmp_path, "--format", "md")
    assert "Nenhum sinal no nível pedido." in out


def test_markdown_mentions_min_severity_and_notes(tmp_path, capsys):
    put(tmp_path, "page.html", "<h2>Why it matters</h2><p>x</p>")
    _, out, _ = run(capsys, tmp_path, "--format", "md", "--min-severity", "low")
    assert "texto extraído" in out
    _, out, _ = run(capsys, tmp_path, "--format", "md", "--min-severity", "high")
    assert "Só sinais de severidade high" in out


# --- --output ----------------------------------------------------------------------------------


def test_output_writes_utf8_to_the_file_and_nothing_to_stdout(tree, tmp_path, capsys):
    report = tmp_path / "out" / "report.md"
    report.parent.mkdir()
    code, out, err = run(capsys, tree, "--format", "md", "--output", report)
    assert code == 0
    assert out == ""
    assert "relatório escrito em" in err
    data = report.read_bytes()
    assert b"\r\n" not in data
    assert "🚀" in data.decode("utf-8")  # an emoji heading snippet survives


def test_the_report_inside_the_scanned_tree_is_not_scanned(tmp_path, capsys):
    put(tmp_path, "a.md", AI_TEXT)
    report = tmp_path / "report.md"
    for _ in range(2):  # the second run would ingest the first run's report if it were not skipped
        run(capsys, tmp_path, "--output", report)
    run(capsys, tmp_path, "--output", tmp_path / "again.json")
    assert json.loads((tmp_path / "again.json").read_text(encoding="utf-8"))["files_scanned"] == 2


def test_output_equal_to_the_input_file_is_refused_and_the_file_survives(tmp_path, capsys):
    path = put(tmp_path, "a.md", AI_TEXT)
    code, _, err = run(capsys, path, "--output", path)
    assert code == 1
    assert "próprio arquivo" in err
    assert path.read_text(encoding="utf-8") == AI_TEXT


def test_an_unwritable_output_is_an_error(tmp_path, capsys):
    put(tmp_path, "a.md", AI_TEXT)
    code, _, err = run(capsys, tmp_path / "a.md", "--output", tmp_path / "missing-dir" / "r.json")
    assert code == 1
    assert "não foi possível escrever" in err


# --- exit codes and skipping -------------------------------------------------------------------


def test_missing_path_exits_1(tmp_path, capsys):
    code, out, err = run(capsys, tmp_path / "nope")
    assert (code, out) == (1, "")
    assert "não existe" in err


def test_nothing_supported_exits_2_but_still_reports(tmp_path, capsys):
    put(tmp_path, "data.json", "{}")
    code, report, _ = run_json(capsys, tmp_path)
    assert code == 2
    assert report["files_scanned"] == 0
    assert report["disclaimer"] == DISCLAIMER


def test_an_empty_directory_exits_2(tmp_path, capsys):
    assert run(capsys, tmp_path)[0] == 2


def test_files_that_cannot_be_read_are_skipped_with_a_warning_not_fatal(tmp_path, capsys):
    put(tmp_path, "good.md", AI_TEXT)
    put(tmp_path, "binary.txt", b"abc\x00def")
    code, report, err = run_json(capsys, tmp_path)
    assert code == 0
    assert list(report["scores"]) == ["good.md"]
    assert report["skipped"] == [{"path": "binary.txt", "reason": "conteúdo binário"}]
    assert "aviso: binary.txt pulado" in err


def test_a_missing_optional_library_skips_docx_and_pdf_and_keeps_going(
    tmp_path, capsys, monkeypatch
):
    put(tmp_path, "good.md", AI_TEXT)
    put(tmp_path, "a.docx", b"PK\x03\x04")
    put(tmp_path, "a.pdf", b"%PDF-1.4")
    real = loaders.importlib.import_module
    monkeypatch.setattr(
        loaders.importlib,
        "import_module",
        lambda name, *a, **k: (
            (_ for _ in ()).throw(ImportError(name))
            if name in ("docx", "pypdf")
            else real(name, *a, **k)
        ),
    )
    code, report, err = run_json(capsys, tmp_path)
    assert code == 0
    assert list(report["scores"]) == ["good.md"]
    assert {s["path"] for s in report["skipped"]} == {"a.docx", "a.pdf"}
    assert all("--group formats" in s["reason"] for s in report["skipped"])
    assert err.count("aviso:") == 2


def test_only_unreadable_supported_files_exit_2(tmp_path, capsys):
    put(tmp_path, "binary.txt", b"abc\x00def")
    code, report, _ = run_json(capsys, tmp_path)
    assert code == 2
    assert len(report["skipped"]) == 1


# --- context handed to the code detectors ------------------------------------------------------


def test_small_project_context_limits_over_descriptive_names(tmp_path, capsys):
    source = "def handle_user_authentication_request():\n    pass\n"
    for i in range(3):
        put(tmp_path, f"small/m{i}.py", source)
    _, small, _ = run_json(capsys, tmp_path / "small")
    assert "over_descriptive_name" in small["by_signal"]
    for i in range(cli.SMALL_PROJECT_FILES + 1):
        put(tmp_path, f"big/m{i}.py", source)
    _, big, _ = run_json(capsys, tmp_path / "big")
    assert "over_descriptive_name" not in big["by_signal"]


def test_requires_python_is_read_from_the_nearest_pyproject(tmp_path, capsys):
    loaders.find_requires_python.cache_clear()
    source = "from __future__ import annotations\n\nx = 1\n"
    put(tmp_path, "new/pyproject.toml", '[project]\nname = "n"\nrequires-python = ">=3.14"\n')
    put(tmp_path, "new/m.py", source)
    put(tmp_path, "old/pyproject.toml", '[project]\nname = "o"\nrequires-python = ">=3.12"\n')
    put(tmp_path, "old/m.py", source)
    _, report, _ = run_json(capsys, tmp_path)
    fired = {k for k, v in report["scores"].items() if v["signals"]}
    assert fired == {"new/m.py"}


# --- real process behaviour --------------------------------------------------------------------


def run_script(*args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )


def test_stdout_survives_a_legacy_windows_code_page_and_emoji_snippets(tmp_path):
    put(tmp_path, "emoji.md", "## 🚀 Start\n\ntext\n")
    done = run_script(tmp_path, "--format", "md", env_extra={"PYTHONIOENCODING": "cp1252"})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert "🚀" in done.stdout.decode("utf-8")


def test_script_exit_codes_and_help(tmp_path):
    assert run_script(tmp_path / "missing").returncode == 1
    assert run_script(tmp_path).returncode == 2
    help_text = run_script("--help").stdout.decode("utf-8")
    for flag in ("--format", "--only", "--min-severity", "--ignore", "--output", "--exclude-tests"):
        assert flag in help_text
    assert run_script(tmp_path, "--format", "xml").returncode == 2  # argparse usage error


def test_running_the_script_on_a_file_end_to_end(tmp_path):
    path = put(tmp_path, "a.md", AI_TEXT)
    done = run_script(path)
    assert done.returncode == 0
    report = json.loads(done.stdout.decode("utf-8"))
    assert report["files_scanned"] == 1
    assert report["disclaimer"] == DISCLAIMER
