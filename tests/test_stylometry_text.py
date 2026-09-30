"""Tests for tools/stylometry/text.py (deterministic prose signals)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stylometry import CATEGORY, SEVERITIES, Signal, cap_confidence, score_signals
from stylometry import text as st

FIXTURES = ROOT / "tests" / "fixtures" / "stylometry"

TEXT_SIGNALS = {
    "em_dash_density",
    "not_just_but",
    "delve_family",
    "worth_noting",
    "fast_paced_world",
    "on_the_other_hand_cascade",
    "hedge_double",
    "bold_lead_in",
    "tricolon_uniform",
    "template_heading",
    "emoji_heading",
    "meta_commentary",
    "paragraph_uniformity",
    "sentence_uniformity",
    "declarative_close",
    "here_is_why",
    "comparison_table_symmetry",
    "type_token_ratio",
    "sentence_length_stddev",
    "paragraph_length_stddev",
    "em_dash_to_comma_ratio",
}


def names(text: str) -> set[str]:
    return {s.name for s in st.analyze(text).signals}


def hits(text: str, name: str) -> list[Signal]:
    return [s for s in st.analyze(text).signals if s.name == name]


def worst(text: str, name: str) -> str | None:
    found = hits(text, name)
    return max((s.severity for s in found), key=SEVERITIES.index) if found else None


def paras(*sizes: int, sentence: str = "O script lê o arquivo e grava a saída limpa no disco."):
    """One paragraph per size, each with that many copies of ``sentence``."""
    return "\n\n".join(" ".join([sentence] * n) for n in sizes)


def sentences_of(*lengths: int) -> str:
    """One paragraph whose sentences have exactly these word counts."""
    return " ".join(" ".join(["Palavra"] * n) + "." for n in lengths)


TRICOLON = "O script lê o arquivo, limpa os caracteres e grava a saída no disco."
SYMMETRIC_TABLE = """\
| Aspecto | Opção A | Opção B |
|---|---|---|
| Entrada | Simples | Simples |
| Formato | Simples | Simples |
"""
LOPSIDED_TABLE = """\
| ID | Item | Estado |
|---|---|---|
| R1 | Descrição longa do primeiro item da lista | ok |
| R2 | Outra descrição bem longa | pendente |
"""

# (signal, text that must fire it, near-miss that must stay quiet)
CASES = [
    (
        "em_dash_density",
        "Um — dois. Três — quatro. Cinco — seis.",
        "Um dois. Três quatro. Cinco seis.",
    ),
    (
        "not_just_but",
        "A ferramenta não é apenas um filtro, é uma auditoria completa.",
        "A ferramenta não é apenas um filtro.",
    ),
    (
        "not_just_but",
        "This is not just a filter, it's a full audit.",
        "This is not just a filter.",
    ),
    ("delve_family", "Let's delve into the details.", "We explore the directory tree."),
    ("delve_family", "Time to dive into the code.", "The dive computer logs depth."),
    ("delve_family", "Vamos explorar o código agora.", "O script explora o diretório."),
    (
        "worth_noting",
        "Vale notar que o script preserva emoji.",
        "Isso merece uma nota no changelog.",
    ),
    (
        "worth_noting",
        "It's worth noting that emoji survive.",
        "It is worth a second look.",
    ),
    (
        "fast_paced_world",
        "In today's fast-paced world, tools matter.",
        "In the morning the script runs.",
    ),
    (
        "fast_paced_world",
        "Em um mundo onde tudo muda, é preciso revisar.",
        "Hoje o script roda em 40 ms.",
    ),
    (
        "on_the_other_hand_cascade",
        "Por outro lado, custa caro. Por outro lado, demora. Por outro lado, quebra.",
        "Por outro lado, custa caro. Por outro lado, demora.",
    ),
    (
        "hedge_double",
        "Pode ser que talvez funcione no Windows.",
        "Talvez funcione no Windows.",
    ),
    (
        "hedge_double",
        "This is arguably perhaps the best option.",
        "This is arguably the best option.",
    ),
    (
        "bold_lead_in",
        "- **Velocidade** — rápido.\n- **Segurança** — seguro.\n- **Clareza**: limpo.",
        "- **Velocidade** — rápido.\n- **Segurança** — seguro.\n- **Clareza** limpo.",
    ),
    (
        "bold_lead_in",
        "**Risco:** a\n\n**Motivo:** b\n\n**Custo:** c",
        "**risco:** a\n\n**motivo:** b\n\n**custo:** c",
    ),
    (
        "tricolon_uniform",
        "\n\n".join([TRICOLON] * 3),
        "\n\n".join([TRICOLON, TRICOLON, "O script grava a saída no disco."]),
    ),
    (
        "tricolon_uniform",
        "\n\n".join(["It reads files, strips marks, and writes output."] * 3),
        "\n\n".join(["It reads files, strips marks, cleans text, and writes output."] * 3),
    ),
    ("template_heading", "## Why it matters\n\ntexto", "## Whatever happens\n\ntexto"),
    ("template_heading", "# Por que isso importa\n\ntexto", "# Por favor leia\n\ntexto"),
    ("template_heading", "## 🚀 O que é isto\n\ntexto", "## Instalação\n\ntexto"),
    ("emoji_heading", "## 🚀 Início rápido\n\ntexto", "## Início rápido 100%\n\ntexto"),
    ("emoji_heading", "## ✅ Pronto\n\ntexto", "## Pronto\n\nTudo certo ✅ no corpo."),
    (
        "meta_commentary",
        "Nesta seção, vamos ver as flags.",
        "A seção de instalação está no README.",
    ),
    ("meta_commentary", "As we've seen, it works.", "We have seen nothing yet."),
    ("paragraph_uniformity", paras(3, 3, 3, 3, 3, 3), paras(1, 4, 2, 5, 3, 1)),
    (
        "sentence_uniformity",
        sentences_of(11, 11, 11, 11, 11, 11, 11, 11, 11),
        sentences_of(3, 20, 7, 14, 2, 25, 9, 16),
    ),
    (
        "declarative_close",
        "Texto anterior aqui.\n\nNão é velocidade. É confiança.",
        "Texto anterior aqui.\n\nNão é possível ler o arquivo. Use outro caminho.",
    ),
    (
        "declarative_close",
        "Intro text here.\n\nIt's not speed. It's trust.",
        "Intro text here.\n\nIt is not ready. Use the flag.",
    ),
    (
        "here_is_why",
        "Aqui está por quê: a lista muda.",
        "Aqui está o resultado: 3 arquivos.",
    ),
    ("here_is_why", "Here's why: the list changes.", "Here's the output: 3 files."),
    ("comparison_table_symmetry", SYMMETRIC_TABLE, LOPSIDED_TABLE),
    (
        "type_token_ratio",
        " ".join(["gato"] * 130),
        " ".join(f"termo{i}" for i in range(150)),
    ),
    (
        "sentence_length_stddev",
        sentences_of(4, 16, 4, 16, 4, 16, 4, 16),
        sentences_of(3, 20, 7, 14, 2, 25, 9, 16),
    ),
    (
        "paragraph_length_stddev",
        "\n\n".join(sentences_of(n) for n in (20, 21, 19, 20, 22)),
        "\n\n".join(sentences_of(n) for n in (5, 60, 20, 90, 12)),
    ),
    (
        "em_dash_to_comma_ratio",
        "A — b, c. D — e, f. G — h, i. J — k, l.",
        "a, " * 40 + "X — y. Z — w. V — u.",
    ),
]


def test_catalogue_is_complete_and_categorised():
    assert {c[0] for c in CASES} == TEXT_SIGNALS
    assert set(CATEGORY) >= TEXT_SIGNALS


@pytest.mark.parametrize(("name", "positive"), [c[:2] for c in CASES], ids=[c[0] for c in CASES])
def test_fires_on_positive(name, positive):
    assert name in names(positive)


@pytest.mark.parametrize(
    ("name", "negative"), [(c[0], c[2]) for c in CASES], ids=[c[0] for c in CASES]
)
def test_quiet_on_near_miss(name, negative):
    assert name not in names(negative)


# name -> (one sample, [(copies, expected worst severity)])
TIERS = {
    "not_just_but": (
        "This is not just a filter, it's a full audit.",
        [(1, "low"), (2, "medium"), (3, "high")],
    ),
    "delve_family": ("Let's delve into the details.", [(1, "low"), (2, "medium"), (3, "high")]),
    "worth_noting": (
        "It's worth noting that emoji survive.",
        [(1, "low"), (2, "medium"), (4, "high")],
    ),
    "fast_paced_world": (
        "In today's fast-paced world, tools matter.",
        [(1, "medium"), (2, "high")],
    ),
    "hedge_double": (
        "This is arguably perhaps the best option.",
        [(1, "low"), (2, "medium"), (3, "high")],
    ),
    "meta_commentary": (
        "In this section we look at flags.",
        [(1, "low"), (2, "medium"), (4, "high")],
    ),
    "here_is_why": ("Here's why: the list changes.", [(1, "low"), (2, "medium"), (3, "high")]),
    "template_heading": ("## Why it matters", [(1, "low"), (2, "medium"), (3, "high")]),
    "emoji_heading": ("## 🚀 Start", [(1, "low"), (2, "medium"), (4, "high")]),
    "bold_lead_in": ("- **Speed** — fast.", [(3, "low"), (6, "medium"), (12, "high")]),
}


@pytest.mark.parametrize(
    ("name", "copies", "expected"),
    [(n, k, sev) for n, (_, tiers) in TIERS.items() for k, sev in tiers],
)
def test_severity_follows_the_count(name, copies, expected):
    sample = TIERS[name][0]
    assert worst("\n\n".join([sample] * copies), name) == expected


def test_cascade_needs_three_hits_inside_one_window():
    spread = ("Por outro lado, custa caro. " + "palavra " * 500 + "\n\n") * 3
    assert "on_the_other_hand_cascade" not in names(spread)
    close = "Por outro lado, a. Por outro lado, b. Por outro lado, c."
    assert worst(close, "on_the_other_hand_cascade") == "medium"
    assert (
        worst(close + " Por outro lado, d. Por outro lado, e.", "on_the_other_hand_cascade")
        == "high"
    )


def test_em_dash_metrics_need_three_dashes():
    assert not names("Um — dois. Três — quatro.") & {"em_dash_density", "em_dash_to_comma_ratio"}


def test_uniformity_needs_enough_paragraphs_and_sentences():
    assert "paragraph_uniformity" not in names(paras(3, 3, 3, 3))
    assert "sentence_uniformity" not in names(sentences_of(11, 11, 11, 11, 11, 11, 11))


def test_type_token_ratio_needs_100_words():
    assert "type_token_ratio" not in names(" ".join(["gato"] * 50))


def test_comparison_table_needs_a_body():
    assert "comparison_table_symmetry" not in names(SYMMETRIC_TABLE.rsplit("\n", 2)[0] + "\n")


def test_declarative_close_is_stronger_in_the_last_paragraph():
    closing = "Texto.\n\nNão é velocidade. É confiança."
    middle = "Não é velocidade. É confiança.\n\nTexto final."
    assert worst(closing, "declarative_close") == "medium"
    assert worst(middle, "declarative_close") == "low"


def test_sentence_length_band_does_not_double_count_uniformity():
    assert worst(sentences_of(4, 16, 4, 16, 4, 16, 4, 16), "sentence_length_stddev") == "low"
    assert "sentence_length_stddev" not in names(sentences_of(*[11] * 9))


def test_line_numbers_follow_the_original_file():
    text = "# Titulo\n\nlinha um\nlinha dois\nvale\nnotar que sim.\n"
    [signal] = hits(text, "worth_noting")
    assert signal.line == 5
    assert "vale notar que sim" in signal.snippet


def test_line_separator_characters_do_not_shift_line_numbers():
    text = "um dois\x0ctres\n\nvale notar que sim.\n"
    assert [s.line for s in hits(text, "worth_noting")] == [3]


def test_fenced_code_and_front_matter_are_ignored_but_keep_numbering():
    text = "---\ntitle: vale notar\n---\n\n```\nvale notar\n```\n\nvale notar que sim.\n"
    assert [s.line for s in hits(text, "worth_noting")] == [9]


def test_unclosed_front_matter_is_not_swallowed():
    text = "---\nvale notar que sim.\n"
    assert [s.line for s in hits(text, "worth_noting")] == [2]


def test_cap_confidence_only_lowers():
    assert cap_confidence("high", "medium") == "medium"
    assert cap_confidence("low", "high") == "low"


def test_tables_do_not_count_as_prose():
    table = "| a — b | c — d |\n|---|---|\n| e — f | g |\n"
    assert not names(table) & {"em_dash_density", "em_dash_to_comma_ratio"}


def test_retained_occurrences_are_capped_but_the_total_is_not():
    found = hits(("vale notar. " * 500).strip(), "worth_noting")
    assert len(found) == 100
    assert {s.value for s in found} == {500}


def test_signal_shape_and_sorted_output():
    analysis = st.analyze((FIXTURES / "text_ai_like.md").read_text(encoding="utf-8"))
    assert Signal._fields == ("name", "value", "severity", "line", "snippet")
    assert {s.name for s in analysis.signals} <= set(CATEGORY)
    assert {s.severity for s in analysis.signals} <= set(SEVERITIES)
    keys = [(s.line is None, s.line or 0, s.name) for s in analysis.signals]
    assert keys == sorted(keys)
    assert all("\n" not in s.snippet and len(s.snippet) <= 100 for s in analysis.signals)


def test_empty_and_code_only_text_are_silent():
    for text in ("", "   \n\n", "```\nvale notar — x — y — z\n```\n"):
        analysis = st.analyze(text)
        assert analysis.signals == []
        assert analysis.score == 0.0
        assert analysis.confidence == "low"


def test_ai_like_fixture_scores_well_above_human_like():
    ai = st.analyze((FIXTURES / "text_ai_like.md").read_text(encoding="utf-8"))
    human = st.analyze((FIXTURES / "text_human_like.md").read_text(encoding="utf-8"))
    assert ai.score >= 0.6
    assert human.score <= 0.2
    assert len({s.name for s in ai.signals}) >= 14
    assert len({s.name for s in human.signals}) <= 2
    assert {s.name for s in ai.signals} <= TEXT_SIGNALS


def test_score_is_bounded_and_uses_the_worst_severity_per_signal():
    assert score_signals([]) == 0.0
    one = [Signal("bold_lead_in", 3, "low", 1, "x")]
    many = [*one, Signal("bold_lead_in", 3, "low", 2, "y")]
    assert score_signals(one) == score_signals(many)
    everything = [Signal(n, 9, "high", None, "") for n in CATEGORY]
    assert 0.99 < score_signals(everything) <= 1.0


def test_score_keeps_resolving_when_many_signals_fire():
    signals = st.analyze((FIXTURES / "text_ai_like.md").read_text(encoding="utf-8")).signals
    every_other = sorted({s.name for s in signals})[::2]
    half = [s for s in signals if s.name in every_other]
    assert 0.3 < score_signals(half) < score_signals(signals) < 1.0


@pytest.mark.parametrize(("words", "expected"), [(50, "low"), (300, "medium"), (700, "high")])
def test_confidence_follows_sample_size(words, expected):
    assert st.analyze(" ".join(f"termo{i}" for i in range(words))).confidence == expected


@pytest.mark.parametrize(
    "blob",
    [
        "a, " * 350_000,
        "— " * 300_000,
        "*" * 1_000_000,
        "** " + "x " * 400_000,
        "Não é " * 120_000,
        "talvez " * 120_000,
        "x" * 1_000_000,
    ],
    ids=["commas", "dashes", "stars", "open-bold", "nao-e", "hedges", "one-word"],
)
def test_pathological_input_stays_fast(blob):
    start = time.perf_counter()
    st.analyze(blob)
    assert time.perf_counter() - start < 15
