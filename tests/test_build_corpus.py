"""Tests for tools/build_corpus.py (personal corpus: init, check, compare)."""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPT = TOOLS / "build_corpus.py"
FIXTURES = ROOT / "tests" / "fixtures" / "stylometry"
sys.path.insert(0, str(TOOLS))

import build_corpus as bc
from stylometry import text as text_signals

AI = (FIXTURES / "text_ai_like.md").read_bytes()
HUMAN = (FIXTURES / "text_human_like.md").read_bytes()
AI_LINES = AI.splitlines(keepends=True)
# Ten prefixes of the model-like text, scoring from 0.28 to 0.88: a side with real spread.
AI_SPREAD = [b"".join(AI_LINES[:k]) for k in (5, 8, 11, 14, 17, 20, 23, 26, 32, 35)]


def fill(corpus: Path, side: str, *contents: bytes) -> None:
    """One ``.md`` file per item of ``contents``."""
    (corpus / side).mkdir(parents=True, exist_ok=True)
    for i, content in enumerate(contents):
        (corpus / side / f"{i:02}.md").write_bytes(content)


def run(capsys, *argv):
    code = bc.main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def score(content: bytes) -> float:
    return text_signals.analyze(content.decode("utf-8")).score


def test_the_spread_used_below_is_real():
    scores = [score(c) for c in AI_SPREAD]
    assert len(AI_SPREAD) == 10 and len(set(scores)) == 10
    assert score(HUMAN) == 0.0


# --- the statistics ----------------------------------------------------------------------------


def test_cohens_d_matches_a_hand_calculation():
    # means 0.2 and 0.5, both standard deviations 0.1: d = 0.3 / 0.1
    assert bc.cohens_d([0.1, 0.2, 0.3], [0.4, 0.5, 0.6]) == pytest.approx(3.0)
    assert bc.cohens_d([0.4, 0.5, 0.6], [0.1, 0.2, 0.3]) == pytest.approx(-3.0)


def test_cohens_d_is_none_when_neither_side_varies():
    assert bc.cohens_d([0.2] * 3, [0.2] * 3) is None
    assert bc.cohens_d([0.2] * 3, [0.7] * 3) is None
    assert bc.cohens_d([0.2, 0.3, 0.4], [0.7] * 3) is not None  # one side is enough


def test_the_interval_matches_a_hand_calculation():
    # d = 1, n = 10 + 10: se = sqrt(20/100 + 1/40) = 0.47434; 1 +- 1.96 * se
    low, high = bc.interval(1.0, 10, 10)
    assert (low, high) == (pytest.approx(0.0703, abs=1e-4), pytest.approx(1.9297, abs=1e-4))
    narrow = bc.interval(1.0, 1000, 1000)
    assert narrow[1] - narrow[0] < high - low


@pytest.mark.parametrize(
    ("human", "ai", "expected"),
    [
        ([0.1, 0.2], [0.3, 0.4], 1.0),
        ([0.3, 0.4], [0.1, 0.2], 0.0),
        ([0.5], [0.5], 0.5),  # a tie counts as half
        ([0.1, 0.5], [0.3], 0.5),
    ],
)
def test_auc_is_the_chance_that_an_ai_text_outscores_a_human_one(human, ai, expected):
    assert bc.auc(sorted(human), ai) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("d", "label"),
    [
        (1.5, "determinístico suficiente"),
        (0.65, "inconclusivo"),
        (0.2, "ML justificado"),
        (-1.2, "ML justificado"),
    ],
)
def test_the_recommendation_follows_the_written_thresholds(d: float, label: str):
    # with 10 000 per side the interval is +-0.03: far from every threshold, so d decides
    assert bc.verdict(d, 10_000, 10_000)[0] == label


@pytest.mark.parametrize("d", [0.8, 0.5])
def test_a_d_on_a_threshold_is_inconclusive_however_large_the_sample(d: float):
    label, note = bc.verdict(d, 10_000, 10_000)
    assert label == "inconclusivo"
    assert "cruza" in note


def test_a_small_sample_cannot_reach_a_hard_label_unless_the_effect_is_large():
    # review of R12: at a true d of 0.8 and n = 10 the label used to flip a quarter of the time
    assert bc.verdict(1.0, 10, 10)[0] == "inconclusivo"
    assert bc.verdict(0.0, 10, 10)[0] == "inconclusivo"
    assert bc.verdict(2.0, 10, 10)[0] == "determinístico suficiente"
    assert bc.verdict(-2.0, 10, 10)[0] == "ML justificado"


def test_a_negative_d_says_the_folders_may_be_swapped():
    assert "trocadas" in bc.verdict(-1.2, 10_000, 10_000)[1]
    assert "trocadas" not in bc.verdict(0.2, 10_000, 10_000)[1]


# --- init --------------------------------------------------------------------------------------


def test_init_creates_both_folders_and_a_readme(tmp_path, capsys):
    corpus = tmp_path / "corpus"
    code, out, _ = run(capsys, "init", "--dir", corpus)
    assert code == 0
    assert (corpus / "human").is_dir() and (corpus / "ai").is_dir()
    assert "10" in (corpus / "README.md").read_text(encoding="utf-8")
    assert "check" in out  # the next step


def test_init_twice_keeps_what_the_user_wrote(tmp_path, capsys):
    corpus = tmp_path / "corpus"
    run(capsys, "init", "--dir", corpus)
    (corpus / "README.md").write_text("minhas notas", encoding="utf-8")
    fill(corpus, "human", b"a")
    assert run(capsys, "init", "--dir", corpus)[0] == 0
    assert (corpus / "README.md").read_text(encoding="utf-8") == "minhas notas"
    assert (corpus / "human" / "00.md").read_bytes() == b"a"


@pytest.fixture
def fake_repo(tmp_path, monkeypatch) -> Path:
    """A stand-in repository root, so a regression of the guard cannot write into the real one."""
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    monkeypatch.setattr(bc, "ROOT", repo)
    return repo


@pytest.mark.parametrize("sub", ["corpus", "a/b/corpus", "."])
def test_init_refuses_a_folder_inside_the_repository(fake_repo, capsys, sub):
    target = fake_repo / sub
    code, _, err = run(capsys, "init", "--dir", target)
    assert code == 1
    assert "versionado" in err
    assert not (target / "human").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the extended-length prefix is Windows only")
def test_init_refuses_the_same_folder_spelled_with_the_long_path_prefix(fake_repo, capsys):
    # review of R12: resolve() keeps the prefix, and is_relative_to(ROOT) then said "outside"
    target = Path(bc.LONG_PATH + str(fake_repo / "corpus"))
    assert str(target.resolve()).startswith(bc.LONG_PATH)
    code, _, err = run(capsys, "init", "--dir", target)
    assert code == 1
    assert "versionado" in err
    assert not (fake_repo / "corpus").exists()


def test_a_sibling_whose_name_starts_like_the_repo_is_not_inside_it(fake_repo, capsys):
    sibling = fake_repo.parent / (fake_repo.name + "-corpus")
    assert run(capsys, "init", "--dir", sibling)[0] == 0
    assert (sibling / "human").is_dir()


def test_init_reports_a_folder_it_cannot_create(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    code, _, err = run(capsys, "init", "--dir", blocker / "corpus")
    assert code == 1
    assert err.startswith("erro:")


def test_the_default_folder_is_corpus_under_the_temp_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    assert bc.default_dir() == tmp_path / "corpus"
    assert run(capsys, "init")[0] == 0
    assert (tmp_path / "corpus" / "ai").is_dir()


def test_the_hint_quotes_a_path_with_spaces(tmp_path, capsys):
    corpus = tmp_path / "meu corpus"
    _, out, _ = run(capsys, "init", "--dir", corpus)
    assert f'--dir "{corpus}"' in out
    _, _, err = run(capsys, "check", "--dir", tmp_path / "outro corpus")
    assert f'--dir "{tmp_path / "outro corpus"}"' in err


# --- check -------------------------------------------------------------------------------------


def test_check_of_a_missing_folder_points_at_init(tmp_path, capsys):
    code, _, err = run(capsys, "check", "--dir", tmp_path / "nope")
    assert code == 1
    assert "init" in err


def test_check_of_a_fresh_corpus_asks_for_ten_in_each_folder(tmp_path, capsys):
    run(capsys, "init", "--dir", tmp_path)
    code, out, err = run(capsys, "check", "--dir", tmp_path)
    assert code == 1
    assert "human: 0 arquivos" in out
    assert "faltam 10 arquivo(s) em human" in err and "faltam 10 arquivo(s) em ai" in err


def test_check_demands_ten_files_in_each_folder(tmp_path, capsys):
    fill(tmp_path, "human", *[HUMAN] * 10)
    fill(tmp_path, "ai", *[AI] * 7)
    code, out, err = run(capsys, "check", "--dir", tmp_path)
    assert code == 1
    assert "human: 10 arquivos" in out and "ai: 7 arquivos" in out
    assert "faltam 3 arquivo(s) em ai" in err


def test_check_reports_the_spread_of_scores(tmp_path, capsys):
    fill(tmp_path, "human", *[HUMAN] * 10)
    fill(tmp_path, "ai", *AI_SPREAD)
    code, out, _ = run(capsys, "check", "--dir", tmp_path)
    scores = sorted(score(c) for c in AI_SPREAD)
    middle = (scores[4] + scores[5]) / 2
    assert code == 0
    assert (
        f"ai: 10 arquivos (mín {scores[0]:.3f}, mediana {middle:.3f}, máx {scores[-1]:.3f})" in out
    )
    assert "human: 10 arquivos (mín 0.000, mediana 0.000, máx 0.000)" in out


def test_check_counts_what_could_not_be_read(tmp_path, capsys):
    fill(tmp_path, "human", *[HUMAN] * 10, b"\x00\x01binario")
    fill(tmp_path, "ai", *[AI] * 10)
    _, out, _ = run(capsys, "check", "--dir", tmp_path)
    assert "human: 10 arquivos" in out
    assert "1 pulado(s)" in out


def test_check_says_how_many_files_it_did_not_look_at(tmp_path, capsys):
    # review of R12: a side with .rst or .py files used to show a smaller n with no reason
    fill(tmp_path, "human", *[HUMAN] * 10)
    fill(tmp_path, "ai", *[AI] * 10)
    (tmp_path / "human" / "code.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "human" / "notes.rst").write_text("texto\n", encoding="utf-8")
    _, out, _ = run(capsys, "check", "--dir", tmp_path)
    assert "human: 10 arquivos" in out
    assert "2 ignorado(s)" in out
    assert "pulado" not in out
    [ai_line] = [line for line in out.splitlines() if line.startswith("ai:")]
    assert "ignorado" not in ai_line


def test_subfolders_are_read(tmp_path, capsys):
    fill(tmp_path, "human", *[HUMAN] * 5)
    fill(tmp_path / "human", "sub", *[HUMAN] * 5)
    fill(tmp_path, "ai", *[AI] * 10)
    _, out, _ = run(capsys, "check", "--dir", tmp_path)
    assert "human: 10 arquivos" in out


# --- compare -----------------------------------------------------------------------------------


def test_compare_refuses_to_recommend_on_a_corpus_that_is_too_small(tmp_path, capsys):
    fill(tmp_path, "human", *[HUMAN] * 9)
    fill(tmp_path, "ai", *AI_SPREAD)
    code, out, err = run(capsys, "compare", "--dir", tmp_path)
    assert code == 1
    assert "recomendação" not in out
    assert "faltam 1 arquivo(s) em human" in err


def test_compare_refuses_a_corpus_made_of_copies_of_one_text(tmp_path, capsys):
    # review of R12: ten copies per side gave d = +inf and "determinístico suficiente"
    fill(tmp_path, "human", *[HUMAN] * 10)
    fill(tmp_path, "ai", *[AI] * 10)
    code, out, err = run(capsys, "compare", "--dir", tmp_path)
    assert code == 1
    assert "degenerado" in err
    assert "recomendação" not in out


def test_compare_of_two_clearly_separated_sides(tmp_path, capsys):
    fill(tmp_path, "human", *[HUMAN] * 10)
    fill(tmp_path, "ai", *AI_SPREAD)
    code, out, _ = run(capsys, "compare", "--dir", tmp_path)
    assert code == 0
    assert "AUC: 1.00" in out
    assert "recomendação: determinístico suficiente" in out


def test_compare_wires_the_scores_into_the_numbers(tmp_path, capsys):
    # human side: 8 plain texts and 2 that read like a model; ai side: all 10 like a model.
    fill(tmp_path, "human", *[HUMAN] * 8, *[AI] * 2)
    fill(tmp_path, "ai", *[AI] * 10)
    h, a = score(HUMAN), score(AI)
    mean_h = (8 * h + 2 * a) / 10
    var_h = (8 * (h - mean_h) ** 2 + 2 * (a - mean_h) ** 2) / 9  # sample variance
    d = (a - mean_h) / math.sqrt(var_h * 9 / 18)  # the ai side has none
    se = math.sqrt(20 / 100 + d * d / 40)
    _, out, _ = run(capsys, "compare", "--dir", tmp_path)
    assert f"Cohen's d: {d:+.3f}" in out
    assert f"IC 95% de d: [{d - 1.96 * se:+.2f}, {d + 1.96 * se:+.2f}]" in out
    assert f"human {mean_h:.3f}" in out and f"ai {a:.3f}" in out
    assert "AUC: 0.90" in out  # 80 of 100 pairs, plus 20 ties worth half


def test_compare_of_swapped_folders_recommends_ml_and_says_why(tmp_path, capsys):
    fill(tmp_path, "human", *AI_SPREAD)
    fill(tmp_path, "ai", *[HUMAN] * 10)
    code, out, _ = run(capsys, "compare", "--dir", tmp_path)
    assert code == 0
    assert "recomendação: ML justificado" in out
    assert "trocadas" in out
    assert "AUC: 0.00" in out


def test_a_small_sample_carries_a_warning_and_a_large_one_does_not(tmp_path, capsys):
    fill(tmp_path, "human", *[HUMAN] * 10)
    fill(tmp_path, "ai", *AI_SPREAD)
    assert "menos de 30" in run(capsys, "compare", "--dir", tmp_path)[1]
    fill(tmp_path, "human", *[HUMAN] * 30)
    fill(tmp_path, "ai", *(AI_SPREAD * 3))
    assert "menos de 30" not in run(capsys, "compare", "--dir", tmp_path)[1]


# --- the procedure document --------------------------------------------------------------------


def test_the_procedure_quotes_the_numbers_the_code_uses():
    doc = (ROOT / "docs" / "CORPUS.md").read_text(encoding="utf-8")

    def pt(x: float) -> str:
        return str(x).replace(".", ",")

    assert f"No mínimo {bc.MIN_PER_SIDE} arquivos em cada pasta" in doc
    assert f"Com {bc.STABLE_PER_SIDE} ou mais por pasta" in doc
    assert f"| {pt(bc.D_SUFFICIENT)} ou mais | `{bc.SUFFICIENT}` |" in doc
    assert (
        f"| de {pt(bc.D_MARGINAL)} até menos de {pt(bc.D_SUFFICIENT)} | `{bc.INCONCLUSIVE}` |"
        in doc
    )
    assert f"| menos de {pt(bc.D_MARGINAL)}, inclusive negativo | `{bc.ML}` |" in doc


# --- as a script -------------------------------------------------------------------------------


def script(*args, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        cwd=cwd,
        check=False,
        timeout=60,
    )


def test_the_script_runs_from_any_directory(tmp_path):
    corpus = tmp_path / "corpus"
    assert script("init", "--dir", corpus, cwd=tmp_path.parent).returncode == 0
    assert (corpus / "human").is_dir()
    done = script("check", "--dir", corpus, cwd=tmp_path.parent)  # empty
    # a bare exit 1 would also be an uncaught exception: the message is the proof
    assert (done.returncode, b"faltam 10 arquivo(s) em human" in done.stderr) == (1, True)


def test_the_script_needs_a_subcommand(tmp_path):
    assert script(cwd=tmp_path).returncode == 2
