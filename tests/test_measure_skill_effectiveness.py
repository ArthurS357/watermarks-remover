"""Tests for tools/measure_skill_effectiveness.py (before/after over the detection package)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "measure_skill_effectiveness.py"
FIXTURES = ROOT / "tests" / "fixtures" / "stylometry"
sys.path.insert(0, str(TOOLS))

import measure_skill_effectiveness as measure
from stylometry import CATEGORY, CONFIDENCES, DISCLAIMER, SEVERITIES, score_signals
from stylometry import text as text_signals

AI = (FIXTURES / "text_ai_like.md").read_text(encoding="utf-8")
HUMAN = (FIXTURES / "text_human_like.md").read_text(encoding="utf-8")
PLAIN = "Uma frase simples sobre o gato.\n"  # no signal fires on this
LOW_ONLY = "# Gatos\n\n## 🚀 Começando\n\nUma frase simples sobre o gato.\n"  # one low signal

SPEC_KEYS = {
    "before_score",
    "after_score",
    "delta",
    "signals_before",
    "signals_after",
    "signals_remaining",
    "signals_eliminated",
    "effectiveness",
    "recommendation",
}


def put(base: Path, name: str, content: str | bytes) -> Path:
    path = base / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def pair(tmp_path: Path, before: str, after: str) -> tuple[Path, Path]:
    return put(tmp_path, "before.md", before), put(tmp_path, "after.md", after)


def run(capsys, *argv):
    code = measure.main([str(a) for a in argv])
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


# --- the contract --------------------------------------------------------------------------------


def test_a_rewrite_that_removes_the_signals_is_high_effectiveness(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    code, report, _ = run_json(capsys, before, after)
    assert code == 0
    assert set(report) >= SPEC_KEYS
    assert report["before_score"] > report["after_score"]
    assert report["delta"] == pytest.approx(
        report["after_score"] - report["before_score"], abs=1e-4
    )
    assert report["delta"] < -0.30
    assert report["effectiveness"] == "high"
    assert report["disclaimer"] == DISCLAIMER
    assert report["confidence"] in CONFIDENCES


def mechanical_rewrite(text: str) -> str:
    """The cheap part of a rewrite: no em dashes, emoji, template headings or bold lead-ins."""
    text = text.replace(" — ", ", ").replace("—", ",")
    text = re.sub(r"^(#+\s*)[\U0001f300-\U0001faff☀-➿]\s*", r"\1", text, flags=re.M)
    text = re.sub(
        r"^(#+\s*)(Por que|O que|A linha|Why|What|The bottom)", r"\1Sobre", text, flags=re.M
    )
    return re.sub(r"\*\*([^*\n]+?)\*\*(\s*[—–:-])", r"\1\2", text)


def test_a_partial_rewrite_is_medium_effectiveness(tmp_path, capsys):
    before, after = pair(tmp_path, AI, mechanical_rewrite(AI))
    _, report, _ = run_json(capsys, before, after)
    assert -0.30 <= report["delta"] < -0.10
    assert report["effectiveness"] == "medium"
    assert {"em_dash_density", "emoji_heading", "template_heading", "bold_lead_in"} <= set(
        report["signals_eliminated"]
    )
    assert report["signals_remaining"], "a mechanical pass leaves the structural habits"
    assert report["recommendation"].startswith("Ainda dispara")


def test_the_report_never_carries_a_verdict(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, report, _ = run_json(capsys, before, after)
    assert not {k for k in keys_anywhere(report) if "is_ai" in k or "verdict" in k}
    assert "is_ai" not in json.dumps(report)


def test_the_signal_lists_are_consistent_with_each_other(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, report, _ = run_json(capsys, before, after)
    b, a = set(report["signals_before"]), set(report["signals_after"])
    remaining, eliminated = set(report["signals_remaining"]), set(report["signals_eliminated"])
    introduced = set(report["signals_introduced"])
    assert remaining == b & a
    assert eliminated == b - a
    assert introduced == a - b
    assert b and eliminated, "the AI fixture must have signals the human one lacks"
    assert not remaining & eliminated


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (-0.9, "high"),
        (-0.3001, "high"),
        (-0.30, "medium"),  # -0.30 <= delta < -0.10
        (-0.2, "medium"),
        (-0.1001, "medium"),
        (-0.10, "low"),
        (-0.05, "low"),
        (0.0, "low"),
        (0.4, "low"),
    ],
)
def test_effectiveness_bands(delta, expected):
    assert measure.effectiveness(delta) == expected


def test_the_band_boundary_survives_float_noise():
    assert measure.effectiveness(0.5 - 0.8) == "medium"  # -0.30000000000000004 raw


def test_identical_files_are_low_effectiveness_with_nothing_eliminated(tmp_path, capsys):
    before, after = pair(tmp_path, AI, AI)
    _, report, _ = run_json(capsys, before, after)
    assert report["delta"] == 0
    assert report["effectiveness"] == "low"
    assert report["signals_eliminated"] == []
    assert set(report["signals_remaining"]) == set(report["signals_before"])


def test_a_rewrite_that_makes_it_worse_reports_what_it_introduced(tmp_path, capsys):
    before, after = pair(tmp_path, HUMAN, AI)
    _, report, _ = run_json(capsys, before, after)
    assert report["delta"] > 0
    assert report["effectiveness"] == "low"
    assert report["signals_introduced"]


def test_signal_deltas_show_both_sides_of_each_signal(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, report, _ = run_json(capsys, before, after)
    deltas = report["signal_deltas"]
    assert set(deltas) == set(report["signals_before"]) | set(report["signals_after"])
    gone = report["signals_eliminated"][0]
    assert deltas[gone]["severity_before"] in SEVERITIES
    assert deltas[gone]["severity_after"] is None
    assert deltas[gone]["value_after"] == 0
    assert deltas[gone]["value_before"] > 0


def test_the_scores_are_the_detectors_scores(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, report, _ = run_json(capsys, before, after)
    assert report["before_score"] == text_signals.analyze(AI).score
    assert report["after_score"] == text_signals.analyze(HUMAN).score


# --- the recommendation --------------------------------------------------------------------------


def test_the_recommendation_names_a_remaining_high_signal_and_an_action(tmp_path, capsys):
    before, after = pair(tmp_path, AI, AI)
    _, report, _ = run_json(capsys, before, after)
    named = re.search(r"`(\w+)`", report["recommendation"])
    assert named, report["recommendation"]
    name = named[1]
    assert name in report["signals_remaining"]
    assert report["signal_deltas"][name]["severity_after"] == "high"
    assert measure.ADVICE[name] in report["recommendation"]
    assert report["recommendation"].startswith("Ainda dispara")


def test_the_recommendation_prefers_a_structural_signal_among_equals(tmp_path, capsys):
    before, after = pair(tmp_path, AI, AI)
    _, report, _ = run_json(capsys, before, after)
    name = re.search(r"`(\w+)`", report["recommendation"])[1]
    highs = [n for n, d in report["signal_deltas"].items() if d["severity_after"] == "high"]
    weights = {n: measure.WEIGHT[CATEGORY[n]] for n in highs}
    assert weights[name] == max(weights.values())


def test_the_recommendation_flags_a_high_signal_the_rewrite_introduced(tmp_path, capsys):
    before, after = pair(tmp_path, PLAIN, AI)
    _, report, _ = run_json(capsys, before, after)
    assert report["signals_remaining"] == []
    assert report["recommendation"].startswith("A reescrita introduziu")
    assert "`" in report["recommendation"]


def test_with_no_signal_left_the_recommendation_says_so(tmp_path, capsys):
    before, after = pair(tmp_path, PLAIN, PLAIN)
    _, report, _ = run_json(capsys, before, after)
    assert report["before_score"] == report["after_score"] == 0
    assert report["signals_after"] == []
    assert report["recommendation"] == "Nenhum sinal restante."


def test_without_a_high_signal_the_recommendation_says_what_is_left(tmp_path, capsys):
    before, after = pair(tmp_path, LOW_ONLY, LOW_ONLY)
    _, report, _ = run_json(capsys, before, after)
    assert report["signals_after"] == ["emoji_heading"], "the precondition: one low signal"
    assert report["recommendation"] == (
        "Sem sinal de severidade alta restante. "
        f"Ainda dispara `emoji_heading` (low): {measure.ADVICE['emoji_heading']}."
    )


def test_every_signal_has_advice_and_nothing_else_does():
    assert set(measure.ADVICE) == set(CATEGORY)
    assert all(text and not text[0].isupper() for text in measure.ADVICE.values())


# --- --signals -----------------------------------------------------------------------------------


def test_signals_restricts_the_lists_and_recomputes_the_score(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, everything, _ = run_json(capsys, before, after)
    pick = everything["signals_eliminated"][0]
    _, report, _ = run_json(capsys, before, after, "--signals", pick)
    assert set(report["signals_before"]) <= {pick}
    assert set(report["signals_after"]) <= {pick}
    assert report["signals_filter"] == [pick]
    only_before = [s for s in text_signals.analyze(AI).signals if s.name == pick]
    assert report["before_score"] == score_signals(only_before)
    assert report["before_score"] < everything["before_score"]


def test_signals_takes_a_comma_separated_list_and_ignores_spaces(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, report, _ = run_json(capsys, before, after, "--signals", " em_dash_density , delve_family ")
    assert report["signals_filter"] == ["delve_family", "em_dash_density"]


def test_an_unknown_signal_name_is_a_usage_error(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    with pytest.raises(SystemExit) as stop:
        measure.main([str(before), str(after), "--signals", "em_dash_density,nope"])
    assert stop.value.code == 2
    assert "nope" in capsys.readouterr().err


def test_an_empty_signals_list_is_a_usage_error(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    with pytest.raises(SystemExit) as stop:
        measure.main([str(before), str(after), "--signals", " , "])
    assert stop.value.code == 2


# --- directories ---------------------------------------------------------------------------------


def make_dirs(tmp_path: Path) -> tuple[Path, Path]:
    before, after = tmp_path / "before", tmp_path / "after"
    put(before, "a.md", AI)
    put(after, "a.md", HUMAN)
    put(before, "sub/b.md", AI)
    put(after, "sub/b.md", AI)
    put(before, "gone.md", AI)
    put(after, "new.md", AI)
    return before, after


def test_directories_are_paired_by_relative_name(tmp_path, capsys):
    before, after = make_dirs(tmp_path)
    code, report, _ = run_json(capsys, before, after)
    assert code == 0
    assert report["mode"] == "directory"
    assert sorted(report["files"]) == ["a.md", "sub/b.md"]
    assert report["unmatched_before"] == ["gone.md"]
    assert report["unmatched_after"] == ["new.md"]
    assert set(report["files"]["a.md"]) >= SPEC_KEYS
    assert report["files"]["a.md"]["effectiveness"] == "high"
    assert report["files"]["sub/b.md"]["delta"] == 0


def test_the_aggregate_is_the_mean_over_the_paired_files(tmp_path, capsys):
    before, after = make_dirs(tmp_path)
    _, report, _ = run_json(capsys, before, after)
    files = report["files"].values()
    assert report["before_score"] == pytest.approx(
        sum(f["before_score"] for f in files) / 2, abs=1e-4
    )
    assert report["after_score"] == pytest.approx(
        sum(f["after_score"] for f in files) / 2, abs=1e-4
    )
    assert report["effectiveness"] == measure.effectiveness(report["delta"])


def test_a_signal_fixed_in_one_file_but_not_another_is_remaining_in_the_aggregate(tmp_path, capsys):
    before, after = make_dirs(tmp_path)
    _, report, _ = run_json(capsys, before, after)
    fixed_in_a = set(report["files"]["a.md"]["signals_eliminated"])
    still_in_b = set(report["files"]["sub/b.md"]["signals_remaining"])
    both = fixed_in_a & still_in_b
    assert both, "the fixtures must share a signal fixed in a.md and left alone in sub/b.md"
    assert both <= set(report["signals_remaining"])
    assert not both & set(report["signals_eliminated"])
    name = sorted(both)[0]
    assert report["signal_deltas"][name]["files_before"] == 2
    assert report["signal_deltas"][name]["files_after"] == 1


def test_a_file_skipped_on_one_side_is_not_reported_as_unmatched(tmp_path, capsys):
    before, after = tmp_path / "before", tmp_path / "after"
    put(before, "a.md", AI)
    put(after, "a.md", HUMAN)
    put(before, "bin.md", AI)
    put(after, "bin.md", b"\x00\x01binary")
    code, report, err = run_json(capsys, before, after)
    assert code == 0
    assert "bin.md" not in report["unmatched_before"]
    assert report["skipped"] == [{"side": "after", "path": "bin.md", "reason": "conteúdo binário"}]
    assert "aviso (depois): bin.md pulado: conteúdo binário" in err


def test_the_output_file_inside_a_scanned_directory_is_not_scanned(tmp_path, capsys):
    before, after = make_dirs(tmp_path)
    out = put(after, "report.md", AI)
    code, _, _ = run(capsys, before, after, "--output", out)
    assert code == 0
    written = json.loads(out.read_bytes())
    assert "report.md" not in written["files"]


# --- files and exit codes ------------------------------------------------------------------------


def test_two_files_pair_whatever_their_names(tmp_path, capsys):
    before = put(tmp_path, "draft.md", AI)
    after = put(tmp_path, "final.txt", HUMAN)
    code, report, _ = run_json(capsys, before, after)
    assert code == 0
    assert report["mode"] == "file"
    assert "files" not in report
    assert report["effectiveness"] == "high"


def test_a_missing_path_is_exit_1(tmp_path, capsys):
    before = put(tmp_path, "a.md", AI)
    code, out, err = run(capsys, before, tmp_path / "nope.md")
    assert (code, out) == (1, "")
    assert "não existe" in err


def test_a_file_against_a_directory_is_exit_1(tmp_path, capsys):
    before = put(tmp_path, "a.md", AI)
    code, _, err = run(capsys, before, tmp_path)
    assert code == 1
    assert "ambos" in err


def test_output_equal_to_an_input_file_is_refused(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    code, _, err = run(capsys, before, after, "--output", after)
    assert code == 1
    assert after.read_text(encoding="utf-8") == HUMAN
    assert "--output" in err


def test_nothing_paired_is_exit_2_with_no_report(tmp_path, capsys):
    before, after = tmp_path / "before", tmp_path / "after"
    put(before, "a.md", AI)
    put(after, "b.md", HUMAN)
    code, out, err = run(capsys, before, after)
    assert (code, out) == (2, "")
    assert "nenhum arquivo pareado" in err


def test_a_skipped_input_file_is_exit_2_and_names_the_side(tmp_path, capsys):
    before = put(tmp_path, "a.md", b"\x00binary")
    after = put(tmp_path, "b.md", HUMAN)
    code, out, err = run(capsys, before, after)
    assert (code, out) == (2, "")
    assert "aviso (antes)" in err


def test_output_writes_utf8_bytes_and_keeps_stdout_empty(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    out = tmp_path / "r.json"
    code, stdout, _ = run(capsys, before, after, "--output", out)
    assert (code, stdout) == (0, "")
    assert json.loads(out.read_bytes())["disclaimer"] == DISCLAIMER


def test_an_unwritable_output_is_exit_1(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    code, _, err = run(capsys, before, after, "--output", tmp_path)  # a directory
    assert code == 1
    assert "não foi possível escrever" in err


# --- markdown and the real script ----------------------------------------------------------------


def test_markdown_report_has_the_disclaimer_the_lists_and_the_recommendation(tmp_path, capsys):
    before, after = make_dirs(tmp_path)
    code, out, _ = run(capsys, before, after, "--format", "md")
    assert code == 0
    assert out.startswith("# Medição de efetividade")
    assert DISCLAIMER in out
    assert "Recomendação" in out
    assert "| `a.md` |" in out
    assert "Sem par" in out and "`gone.md`" in out and "`new.md`" in out


def test_markdown_shows_the_signals_filter(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, out, _ = run(capsys, before, after, "--format", "md", "--signals", "em_dash_density")
    assert "- Só estes sinais: `em_dash_density`" in out


def test_markdown_lists_skipped_files_without_raw_control_characters(tmp_path, capsys, monkeypatch):
    before, after = make_dirs(tmp_path)
    real = measure.detect.loaders.load

    def load(path):
        if path.name == "new.md":
            return measure.detect.loaders.UnsupportedFormat(path, "boom\x1b[2J")
        return real(path)

    monkeypatch.setattr(measure.detect.loaders, "load", load)
    code, out, err = run(capsys, before, after, "--format", "md")
    assert code == 0
    assert "## Arquivos pulados" in out
    assert "- `new.md` (after): boom?[2J" in out
    assert "\x1b" not in out + err
    assert "aviso (depois): new.md pulado: boom?[2J" in err


def test_markdown_report_for_two_files_has_no_table(tmp_path, capsys):
    before, after = pair(tmp_path, AI, HUMAN)
    _, out, _ = run(capsys, before, after, "--format", "md")
    assert "| Arquivo |" not in out
    assert "high" in out


def test_markdown_caps_the_file_table_and_says_how_many_were_left_out(tmp_path, capsys):
    before, after = tmp_path / "before", tmp_path / "after"
    for i in range(measure.TABLE_ROWS + 3):
        put(before, f"f{i:02d}.md", AI)
        put(after, f"f{i:02d}.md", AI)
    _, out, _ = run(capsys, before, after, "--format", "md")
    assert out.count("| `f") == measure.TABLE_ROWS
    assert "(+3)" in out


def test_the_script_survives_a_cp1252_console(tmp_path):
    before, after = pair(tmp_path, AI, HUMAN)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(before), str(after), "--format", "md"],
        capture_output=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert "# Medição de efetividade" in done.stdout.decode("utf-8")


def test_the_output_is_deterministic(tmp_path, capsys):
    before, after = make_dirs(tmp_path)
    first = run(capsys, before, after)[1]
    second = run(capsys, before, after)[1]
    assert first == second
