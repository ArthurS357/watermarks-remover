"""Regression tests for what the review of R11 found in the naturalizer, plus its fuzz and
hostile-input tests. Each finding was reproduced before it was fixed."""

from __future__ import annotations

import random
import re
import time

import pytest
from naturalize_support import BOLD_PAD, OPEN, dash, kept, out, probe
from stylometry import naturalize as nat

# --- found by the review of R11: each one was reproduced first ---------------------------------


@pytest.mark.parametrize(
    "line", ["We delv" + chr(0x131) + "ng into the data.", "We delve" + chr(0x17F) + " into it."]
)
def test_lookalike_letters_do_not_crash_the_delve_rewrite(line: str):
    # under IGNORECASE alone the dotless i and the long s match "i" and "s": a KeyError, exit 1
    assert probe(line, signals={"delve_family"}) == line


@pytest.mark.parametrize(
    "block",
    [
        "````md\n```\nfoo — bar — baz\n````",  # a shorter run is content
        "```\n```python\nfoo — bar\n```",  # a run with an info string is content
        "~~~\n```\nfoo — bar\n~~~",  # another character is content
    ],
)
def test_only_a_long_enough_bare_fence_closes_a_block(block: str):
    assert block in out(f"{OPEN}{block}\n")


def test_a_longer_fence_closes_and_the_text_after_it_is_editable():
    text = f"{OPEN}```\nfoo — bar\n````\n\nVale notar que sim.\n"
    assert out(text).endswith("foo — bar\n````\n\nSim.\n")


@pytest.mark.parametrize(
    "line",
    [
        "Budget 10 — 20 million",
        "years 1999 — 2005",
        "from 9h — 17h",
        "5% — 10%",
        "$5 — $10",
        "10—20",
    ],
)
def test_a_numeric_range_keeps_its_dash_spaced_or_not(line: str):
    assert dash(line) == line


def test_a_dash_is_a_comma_unless_both_sides_are_numbers():
    assert dash("item 3 — a seguir") == "item 3, a seguir"
    assert dash("Monday — Friday") == "Monday, Friday"  # documented: no digit, so a list


def test_single_quoted_literals_stay_and_apostrophes_are_not_quotes():
    kept("' — '")
    assert dash("It's fine — really") == "It's fine, really"
    assert dash("the dogs' toys and cats' food — ok") == "the dogs' toys and cats' food, ok"


def test_repeated_titles_keep_the_one_a_link_points_at():
    text = "## Why this matters\n\n## Why this matters\n\nSee [x](#why-this-matters-1).\n"
    assert out(text, signals={"template_heading"}) == text
    free = "## Why this matters\n\n## Why this matters\n"
    assert out(free, signals={"template_heading"}) == "## Relevance\n\n## Relevance\n"


def test_a_percent_encoded_link_protects_the_title():
    text = "## Por que isso é importante\n\nSee [x](#por-que-isso-%C3%A9-importante).\n"
    assert out(text, signals={"template_heading"}) == text


@pytest.mark.parametrize(
    "text",
    [
        "## Why this matters\n\n## Relevance\n\nSee [x](#relevance).\n",
        "## ✅ Resultado\n\n## Resultado\n",
        "Relevance\n=========\n\n## Why this matters\n",  # a setext title owns the slug too
    ],
)
def test_a_new_title_never_takes_the_slug_of_a_heading_that_exists(text: str):
    assert out(text, signals={"template_heading", "emoji_heading"}) == text


@pytest.mark.parametrize(
    "block",
    [
        'He said "we need this — and\nthat — too" ok.',
        "He said “we need this — and\nthat — too” ok.",
        "Run `pip install — and\nmore — stuff` now.",
        "a | b\n--|--\nfoo | long — short",
    ],
)
def test_quotes_and_code_spans_wrapped_over_lines_and_pipeless_tables_stay(block: str):
    assert block in out(f"{OPEN}{block}\n")


def test_an_open_quote_is_held_only_until_the_paragraph_ends():
    assert out('He said "hi\nthere\n\nVale notar que sim.\n').endswith("there\n\nSim.\n")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("In today's fast-paced world, pip installs wheels.", "pip installs wheels."),
        ("Vale notar que npm falha.", "npm falha."),
        ("In today's fast-paced world, teams ship.", "Teams ship."),
        ("In today's fast-paced world, ", ""),
    ],
)
def test_lower_case_tool_names_are_not_capitalised(line: str, expected: str):
    assert probe(line) == expected


def test_a_leaked_placeholder_is_an_error_not_corrupt_output(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nat._Masker, "restore", lambda self, line: line)
    with pytest.raises(RuntimeError, match="marcador"):
        nat.naturalize("Vale notar que `x` sim.\n")


def test_a_wrapped_line_start_is_not_a_sentence_start():
    wrapped = "and then the thing\nit's worth noting that the file is gone.\n"
    assert out(wrapped) == wrapped
    assert out("Uma frase acaba.\nVale notar que a próxima começa.\n") == (
        "Uma frase acaba.\nA próxima começa.\n"
    )


def test_a_title_or_a_list_item_after_an_unfinished_line_still_starts_a_sentence():
    assert out("# Título\nVale notar que sim.\n") == "# Título\nSim.\n"
    assert out("texto sem ponto\n- Vale notar que sim.\n") == "texto sem ponto\n- Sim.\n"


def test_a_lazy_list_continuation_is_not_a_lead_in():
    text = BOLD_PAD + "**Termo** — x\n"
    assert out(text).splitlines()[3] == "**Termo** — x"


# --- random documents --------------------------------------------------------------------------

FRAGMENTS = [
    "Vale notar que o parser é linear.",
    "It's worth noting that x holds.",
    "In today's fast-paced world, teams ship.",
    "Nos dias de hoje, vale testar.",
    "Pode ser que talvez caia.",
    "We delve into `code — x` and let's dive into it.",
    "- **Termo** — definição com `x`.",
    "**Nota:** texto — com travessão.",
    "## Why this matters",
    "## 🚀 Próximos passos",
    "A faixa 10—20 e 2020—2024 — fim.",
    "Veja https://ex.com/a—b e E:" + chr(92) + "dir" + chr(92) + "f—g.py agora.",
    'Ele disse "vale notar que — isso" e saiu.',
    "O commit 3f7c25d mudou 1234 linhas (50%, 0.5 MB).",
    "| a — b | vale notar que |",
    "> Vale notar que — citação.",
    "```\nvale notar que — x\n```",
    "get_user e CamelCase e UPPER_CASE — fim.",
    "Um — dois — três — quatro.",
    "Texto simples sem nada.",
    "",
]
PROTECTED = [
    re.compile(r"`[^`\n]+`"),
    re.compile(r"https?://\S+"),
    re.compile(r"\"[^\"\n]+\""),
    re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"),
    re.compile(r"\d+(?:[.,]\d+)?"),
]


def protected_tokens(text: str) -> list[str]:
    return sorted(m for rx in PROTECTED for m in rx.findall(text))


@pytest.mark.parametrize("seed", range(150))
def test_random_documents_keep_what_they_must_and_reach_a_fixpoint(seed: int):
    rng = random.Random(seed)  # noqa: S311 - seeded test data, not security
    parts = [rng.choice(FRAGMENTS) for _ in range(rng.randint(3, 25))]
    text = "".join(p + rng.choice(["\n", "\n\n", "\r\n"]) for p in parts)
    result = nat.naturalize(text)
    assert protected_tokens(result.text) == protected_tokens(text)
    assert len(re.findall(r"\r\n|\n|\r", result.text)) == len(re.findall(r"\r\n|\n|\r", text))
    assert nat.naturalize(result.text).text == result.text
    assert result.after.score <= result.before.score


# --- hostile input -----------------------------------------------------------------------------

OPEN_GATES = "\n\nVale notar que isso. A — b. C — d. E — f.\n"
HOSTILE = {
    "dashes": "a — " * 30_000,
    "tags": "<a " * 40_000,
    "links": "](" * 50_000,
    "sentences": ". " * 50_000,
    "slashes": "a/" * 50_000,
    "dots": "a." * 50_000,
    "quotes": '" ' * 50_000,
    "ticks": "` " * 50_000,
    "hedges": "talvez " * 20_000,
    "underscores": "a_" * 50_000,
    "capitals": "AB" * 50_000 + "_",
    "open_curly": "“ " * 60_000,
    "open_guillemet": "« " * 60_000,
    "open_single": "' " * 60_000,
    "open_backtick": "` " * 60_000,
    "many_lines": "palavra — x\n" * 40_000,
    "heading_spaces": "# a" + " " * 100_000 + "b",
    "heading_marks": "# Why this matters" + "?" * 100_000 + "x",
    "bold_unclosed": "- **" + "a" * 100_000,
    "indent": " " * 100_000 + "**Termo** — x",
    "reference": "[" + "a" * 100_000,
    "hex": "0a" * 50_000,
    "one_long_line": "palavra " * 30_000 + "— x",
}


@pytest.mark.parametrize("kind", HOSTILE)
def test_hostile_lines_cost_linear_time(kind: str):
    text = HOSTILE[kind] + OPEN_GATES
    start = time.perf_counter()
    nat.naturalize(text)
    assert time.perf_counter() - start < 20
