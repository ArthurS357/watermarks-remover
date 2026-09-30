"""Tests for tools/naturalize.py (the CLI over stylometry.naturalize)."""

from __future__ import annotations

import codecs
import difflib
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "naturalize.py"
BOM = codecs.BOM_UTF8
CASES = ROOT / "tests" / "fixtures" / "stylometry" / "naturalize"
sys.path.insert(0, str(TOOLS))

import measure_skill_effectiveness as measure
import naturalize as cli
from stylometry import DISCLAIMER, SEVERITIES, loaders
from stylometry import text as text_signals


def case(name: str, which: str = "before.md") -> str:
    return (CASES / name / which).read_bytes().decode("utf-8")


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
    code, out, err = run(capsys, *argv, "--format", "json")
    return code, json.loads(out), err


# --- the three output modes --------------------------------------------------------------------


def test_the_naturalized_text_goes_to_stdout_by_default(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("worth_noting"))
    code, out, err = run(capsys, source)
    assert (code, err) == (0, "")
    assert out == case("worth_noting", "after.md")
    assert source.read_bytes().decode() == case("worth_noting")  # the file is untouched


def test_a_txt_file_is_supported(tmp_path, capsys):
    source = put(tmp_path, "doc.txt", "Vale notar que sim.\n")
    assert run(capsys, source)[:2] == (0, "Sim.\n")


def test_nothing_applicable_exits_3_and_the_text_comes_out_unchanged(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("natural"))
    code, out, _ = run(capsys, source)
    assert (code, out) == (3, case("natural"))
    assert run(capsys, source, "--diff-only")[:2] == (3, "")


def test_diff_only_prints_a_unified_diff_and_writes_nothing(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("hedge_double"))
    code, out, _ = run(capsys, source, "--diff-only")
    assert code == 0
    lines = out.splitlines()
    assert lines[:2] == ["--- doc.md", "+++ doc.md (naturalizado)"]
    assert "-Pode ser que talvez o serviço caia. Arguably perhaps the simplest fix wins." in lines
    assert "+Talvez o serviço caia. Perhaps the simplest fix wins." in lines
    assert source.read_bytes().decode() == case("hedge_double")


def test_a_diff_never_carries_a_control_character(tmp_path, capsys):
    source = put(tmp_path, "doc.txt", "Vale notar que \x1b[31m sim\x07.\tok\n")
    out = run(capsys, source, "--diff-only")[1]
    assert "\x1b" not in out and "\x07" not in out
    assert "\t" in out  # tab is kept
    assert out.count("\n") >= 4  # the line breaks are real


def test_in_place_replaces_the_file_and_prints_nothing_on_stdout(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("worth_noting"))
    code, out, err = run(capsys, source, "--in-place")
    assert (code, out) == (0, "")
    assert "5 transformações" in err
    assert source.read_bytes().decode() == case("worth_noting", "after.md")
    assert [p.name for p in tmp_path.iterdir()] == ["doc.md"]  # no temp file left behind


def test_in_place_keeps_the_bom_and_every_line_ending(tmp_path, capsys):
    raw = BOM + "# Why this matters\r\nVale notar que sim.\rCabe destacar que não.\n\nfim".encode()
    source = put(tmp_path, "doc.md", raw)
    assert run(capsys, source, "--in-place")[0] == 0
    expected = BOM + "# Relevance\r\nSim.\rNão.\n\nfim".encode()
    assert source.read_bytes() == expected


def test_in_place_does_not_touch_a_file_with_nothing_to_do(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("natural"))
    before = source.stat().st_mtime_ns
    assert run(capsys, source, "--in-place")[0] == 3
    assert source.stat().st_mtime_ns == before


def test_in_place_and_diff_only_exclude_each_other(tmp_path, capsys):
    source = put(tmp_path, "doc.md", "x\n")
    with pytest.raises(SystemExit) as exc:
        cli.main([str(source), "--in-place", "--diff-only"])
    assert exc.value.code == 2


def test_a_failed_replacement_leaves_the_file_and_no_temp_file(tmp_path, capsys, monkeypatch):
    source = put(tmp_path, "doc.md", case("worth_noting"))

    def refuse(src, dst):
        raise PermissionError(13, "negado")

    monkeypatch.setattr(os, "replace", refuse)
    code, _, err = run(capsys, source, "--in-place")
    assert code == 1
    assert "não foi possível escrever" in err
    assert source.read_bytes().decode() == case("worth_noting")
    assert [p.name for p in tmp_path.iterdir()] == ["doc.md"]


def test_output_writes_the_result_to_a_file(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("worth_noting"))
    target = tmp_path / "out.md"
    code, out, err = run(capsys, source, "--output", target)
    assert (code, out) == (0, "")
    assert "resultado escrito em" in err
    assert target.read_bytes().decode() == case("worth_noting", "after.md")
    assert source.read_bytes().decode() == case("worth_noting")


def test_output_may_not_be_the_input_and_must_be_writable(tmp_path, capsys):
    source = put(tmp_path, "doc.md", "Vale notar que sim.\n")
    assert run(capsys, source, "--output", source)[0] == 1
    code, _, err = run(capsys, source, "--output", tmp_path)  # a directory
    assert code == 1
    assert "não foi possível escrever" in err


def test_output_and_in_place_combine(tmp_path, capsys):
    source = put(tmp_path, "doc.md", "Vale notar que sim.\n")
    report = tmp_path / "report.json"
    code, out, _ = run(capsys, source, "--in-place", "--format", "json", "--output", report)
    assert (code, out) == (0, "")
    assert source.read_bytes() == b"Sim.\n"
    assert json.loads(report.read_bytes())["mode"] == "in-place"


# --- errors ------------------------------------------------------------------------------------


def test_a_missing_path_exits_1(tmp_path, capsys):
    code, out, err = run(capsys, tmp_path / "nope.md")
    assert (code, out) == (1, "")
    assert "não existe" in err


def test_a_directory_exits_1(tmp_path, capsys):
    assert run(capsys, tmp_path)[0] == 1


@pytest.mark.parametrize("name", ["doc.html", "doc.docx", "doc.pdf", "doc.py", "doc", "doc.json"])
def test_an_unsupported_format_exits_2(tmp_path, capsys, name):
    source = put(tmp_path, name, "Vale notar que sim.\n")
    code, out, err = run(capsys, source)
    assert (code, out) == (2, "")
    assert "formato não suportado" in err


@pytest.mark.parametrize(
    ("content", "reason"),
    [(b"\xff\xfeV\x00", "UTF-8"), (b"Vale notar\x00 que sim.", "binário")],
)
def test_undecodable_input_exits_2(tmp_path, capsys, content, reason):
    code, _, err = run(capsys, put(tmp_path, "doc.md", content))
    assert code == 2
    assert reason in err


def test_a_file_over_the_size_limit_exits_2(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(loaders, "MAX_TEXT_BYTES", 20)
    code, _, err = run(capsys, put(tmp_path, "doc.md", "Vale notar que sim. " * 5))
    assert (code, "limite" in err) == (2, True)


def test_an_unreadable_file_exits_2(tmp_path, capsys, monkeypatch):
    source = put(tmp_path, "doc.md", "x\n")

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "negado")

    monkeypatch.setattr(Path, "open", refuse)
    code, _, err = run(capsys, source)
    assert code == 2
    assert "erro de leitura" in err


def test_a_text_the_engine_refuses_exits_2(tmp_path, capsys):
    crowded = "".join(map(chr, range(0xE000, 0xF900))) + "\nVale notar que sim.\n"
    code, _, err = run(capsys, put(tmp_path, "doc.md", crowded))
    assert code == 2
    assert "uso privado" in err


@pytest.mark.parametrize("csv", ["nope", "bold_lead_in,nope", ","])
def test_an_unknown_or_empty_signal_list_is_a_usage_error(tmp_path, csv):
    source = put(tmp_path, "doc.md", "x\n")
    with pytest.raises(SystemExit) as exc:
        cli.main([str(source), "--signals", csv])
    assert exc.value.code == 2


# --- --signals and --preserve ------------------------------------------------------------------


def test_signals_limits_the_rewrites(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("preservation"))
    code, report, _ = run_json(capsys, source, "--signals", "hedge_double, template_heading")
    assert code == 0
    assert {t["signal"] for t in report["transforms"]} == {"hedge_double", "template_heading"}


def test_a_path_glob_leaves_the_file_alone(tmp_path, capsys):
    source = put(tmp_path, "keep-this.md", "Vale notar que sim.\n")
    code, report, _ = run_json(capsys, source, "--preserve", "keep-*")
    assert code == 3
    assert report["transforms"] == []
    assert "arquivo preservado por --preserve" in report["notes"]
    assert run(capsys, source, "--preserve", "*/keep-this.md")[:2] == (3, "Vale notar que sim.\n")


def test_a_line_glob_leaves_the_line_alone(tmp_path, capsys):
    source = put(tmp_path, "doc.md", "Vale notar que sim. Fonte: x.\nVale notar que não.\n")
    out = run(capsys, source, "--preserve", "*Fonte*")[1]
    assert out == "Vale notar que sim. Fonte: x.\nNão.\n"


# --- the reports -------------------------------------------------------------------------------


def test_the_json_report_has_the_contract_fields(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("preservation"))
    code, report, _ = run_json(capsys, source)
    assert code == 0
    assert {
        "file",
        "signals_before",
        "signals_after",
        "delta",
        "transforms",
        "preserved_spans",
        "confidence",
        "disclaimer",
    } <= report.keys()
    assert report["disclaimer"] == DISCLAIMER
    assert report["confidence"] in ("low", "medium", "high")
    assert report["mode"] == "stdout"
    assert report["delta"] == round(report["score_after"] - report["score_before"], 4)
    assert report["delta"] < 0
    assert set(report["signals_after"]) < set(report["signals_before"])
    assert {"signal", "line", "before", "after"} == set(report["transforms"][0])
    assert {"kind", "line", "text"} == set(report["preserved_spans"][0])
    assert report["transforms_total"] == len(report["transforms"]) == 8
    assert report["diff"].startswith("--- doc.md\n+++ doc.md (naturalizado)\n")
    worst: dict[str, int] = {}  # ranked: the most severe signal first, then by name
    for s in text_signals.analyze(case("preservation")).signals:
        worst[s.name] = max(worst.get(s.name, 0), SEVERITIES.index(s.severity))
    assert report["signals_before"] == sorted(worst, key=lambda n: (-worst[n], n))


def test_the_delta_matches_what_the_compare_of_r10_measures(tmp_path, capsys):
    source = put(tmp_path, "before.md", case("preservation"))
    target = tmp_path / "after.md"
    assert run(capsys, source, "--output", target)[0] == 0
    measured = json.loads(run(capsys, source, "--format", "json")[1])
    code = measure.main([str(source), str(target)])
    compared = json.loads(capsys.readouterr().out)
    assert code == 0
    assert compared["before_score"] == measured["score_before"]
    assert compared["after_score"] == measured["score_after"]
    assert compared["delta"] == measured["delta"]
    assert compared["effectiveness"] == measured["effectiveness"]


def test_the_report_caps_what_it_lists_but_keeps_the_totals(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "MAX_EDITS", 2)
    monkeypatch.setattr(cli, "MAX_SPANS", 3)
    source = put(tmp_path, "doc.md", case("preservation"))
    _, report, _ = run_json(capsys, source)
    assert len(report["transforms"]) == 2
    assert report["transforms_total"] == 8
    assert len(report["preserved_spans"]) == 3
    assert report["preserved_total"] > 3


def test_a_report_shows_the_changed_part_of_a_long_line(tmp_path, capsys):
    long = "Palavras " * 30 + "acabam. Vale notar que o fim muda. " + "Mais " * 30
    source = put(tmp_path, "doc.md", long + "\n")
    _, report, _ = run_json(capsys, source)
    [edit] = report["transforms"]
    assert "Vale notar que" in edit["before"]
    assert "Vale notar que" not in edit["after"]


def test_the_markdown_report_has_the_table_and_the_diff(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("worth_noting"))
    code, out, _ = run(capsys, source, "--format", "md")
    assert code == 0
    assert out.startswith("# Naturalização\n\n> " + DISCLAIMER)
    assert "| Sinal | Linha | Antes | Depois |" in out
    assert "- Transformações: 5 (worth_noting 5)" in out
    assert "## Diff\n\n```diff\n--- doc.md" in out
    assert out.rstrip().endswith("```")


def test_the_markdown_report_truncates_a_long_table_and_reports_no_changes(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(cli, "TABLE_ROWS", 2)
    source = put(tmp_path, "doc.md", case("worth_noting"))
    assert "(+3) fora da tabela" in run(capsys, source, "--format", "md")[1]
    untouched = put(tmp_path, "natural.md", case("natural"))
    out = run(capsys, untouched, "--format", "md")[1]
    assert "- Transformações: 0 (nenhuma)" in out
    assert "## Diff" not in out


def test_markdown_cells_escape_pipes_and_the_fence_outgrows_the_diff():
    assert cli._cell("a | b") == "`a " + chr(92) + "| b`"
    assert cli._fence("sem crase") == "```"
    assert cli._fence("x ```` y `` z") == "`````"


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("igual", "igual", ("igual", "igual")),
        ("abc", "abcd", ("abc", "abcd")),
        (
            "x" * 100 + "AAA" + "y" * 100,
            "x" * 100 + "y" * 100,
            ("x" * 25 + "AAA" + "y" * 25, "x" * 25 + "y" * 25),
        ),
    ],
)
def test_changed_windows_the_difference(before, after, expected):
    assert cli._changed(before, after) == expected


# --- as a script -------------------------------------------------------------------------------


def script(*args, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        cwd=cwd,
        check=False,
        timeout=60,
    )


def test_the_script_runs_from_any_directory_and_keeps_the_bytes(tmp_path):
    raw = b"# Why this matters\r\nVale notar que sim.\r\n"
    source = put(tmp_path, "doc.md", raw)
    done = script(source, cwd=tmp_path.parent)
    assert (done.returncode, done.stdout) == (0, b"# Relevance\r\nSim.\r\n")


def test_the_script_exit_codes(tmp_path):
    assert script(tmp_path / "nope.md", cwd=tmp_path).returncode == 1
    assert script(put(tmp_path, "a.html", "x"), cwd=tmp_path).returncode == 2
    assert script(put(tmp_path, "b.md", case("natural")), cwd=tmp_path).returncode == 3


def test_running_the_output_again_changes_nothing(tmp_path, capsys):
    source = put(tmp_path, "doc.md", case("preservation"))
    once = tmp_path / "once.md"
    assert run(capsys, source, "--output", once)[0] == 0
    code, out, _ = run(capsys, once)
    assert (code, out) == (3, once.read_bytes().decode())


# --- found by the review of R11 ----------------------------------------------------------------


def test_the_diff_is_linear_where_difflib_took_minutes(tmp_path):
    before = "\n".join(f"linha {i} — x" if i % 2 else f"linha {i}" for i in range(60_000))
    after = "\n".join(f"linha {i}, x" if i % 2 else f"linha {i}" for i in range(60_000))
    start = time.perf_counter()
    diff = cli.unified_diff(before, after, "big.md")
    assert time.perf_counter() - start < 5
    assert diff.count("\n-") == 30_000


@pytest.mark.parametrize("seed", range(40))
def test_the_diff_agrees_with_difflib_when_no_line_repeats(seed):
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not security
    old = [f"linha {i}" for i in range(rng.randint(1, 40))]
    new = [f"{line} mudou" if rng.random() < 0.25 else line for line in old]
    expected = "".join(
        line + "\n"
        for line in difflib.unified_diff(old, new, "f.md", "f.md (naturalizado)", lineterm="")
    )
    assert cli.unified_diff("\n".join(old), "\n".join(new), "f.md") == expected


def test_an_unchanged_text_has_an_empty_diff_and_hunks_merge_when_context_meets():
    assert cli.unified_diff("a\nb", "a\nb", "f.md") == ""
    body = "\n".join(str(i) for i in range(30))
    changed = body.replace("\n5\n", "\nX\n").replace("\n9\n", "\nY\n").replace("\n25\n", "\nZ\n")
    hunks = [
        line for line in cli.unified_diff(body, changed, "f.md").splitlines() if line[0] == "@"
    ]
    assert hunks == ["@@ -3,11 +3,11 @@", "@@ -23,7 +23,7 @@"]  # 5 and 9 share context; 25 is apart


def test_the_default_modes_do_not_pay_for_a_diff(tmp_path, capsys, monkeypatch):
    def boom(*args):
        raise AssertionError("the diff was built")

    monkeypatch.setattr(cli, "unified_diff", boom)
    source = put(tmp_path, "doc.md", "Vale notar que sim.\n")
    assert run(capsys, source)[:2] == (0, "Sim.\n")
    assert run(capsys, source, "--in-place")[0] == 0


def test_bidi_overrides_and_escapes_never_reach_a_report_or_a_diff(tmp_path, capsys):
    evil = f"Vale notar que {chr(0x202E)}sim{chr(0x1B)}[31m.\n"
    source = put(tmp_path, "doc.md", evil)
    for fmt_args in (["--diff-only"], ["--format", "md"], ["--format", "json"]):
        out = run(capsys, source, *fmt_args)[1]
        assert chr(0x202E) not in out and chr(0x1B) not in out


def test_text_sent_to_a_terminal_is_sanitised_but_a_pipe_gets_the_bytes(
    tmp_path, capsys, monkeypatch
):
    source = put(tmp_path, "doc.md", f"Vale notar que a {chr(0x1B)}]0;x{chr(7)}b{chr(0x202E)}c.\n")
    piped = run(capsys, source)[1]
    assert chr(0x1B) in piped and chr(0x202E) in piped  # a file is a file
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    shown = run(capsys, source)[1]
    assert chr(0x1B) not in shown and chr(7) not in shown and chr(0x202E) not in shown
    assert shown.endswith("\n")  # the line break survives


def test_output_cannot_be_a_hard_link_to_the_input(tmp_path, capsys):
    source = put(tmp_path, "src.md", "Vale notar que sim.\n")
    link = tmp_path / "link.json"
    try:
        os.link(source, link)
    except OSError:
        pytest.skip("hard links are not available here")
    code, _, err = run(capsys, source, "--format", "json", "--output", link)
    assert (code, "próprio arquivo" in err) == (1, True)
    assert source.read_bytes() == b"Vale notar que sim.\n"


def test_output_replaces_the_file_instead_of_writing_through_a_hard_link(tmp_path, capsys):
    source = put(tmp_path, "src.md", "Vale notar que sim.\n")
    target = put(tmp_path, "out.md", "old\n")
    other = tmp_path / "other.md"
    try:
        os.link(target, other)
    except OSError:
        pytest.skip("hard links are not available here")
    assert run(capsys, source, "--output", target)[0] == 0
    assert target.read_bytes() == b"Sim.\n"
    assert other.read_bytes() == b"old\n"  # the other name still has the old content


def test_a_file_edited_after_it_was_read_is_not_overwritten(tmp_path, capsys, monkeypatch):
    source = put(tmp_path, "doc.md", "Vale notar que sim.\n")
    real = cli.engine.naturalize

    def edit_then_naturalize(*args, **kwargs):
        source.write_bytes(b"edited meanwhile, and longer\n")
        return real(*args, **kwargs)

    monkeypatch.setattr(cli.engine, "naturalize", edit_then_naturalize)
    code, _, err = run(capsys, source, "--in-place")
    assert (code, "mudou depois de lido" in err) == (1, True)
    assert source.read_bytes() == b"edited meanwhile, and longer\n"
    assert [p.name for p in tmp_path.iterdir()] == ["doc.md"]
