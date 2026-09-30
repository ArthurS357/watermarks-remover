"""Tests for tools/stylometry/naturalize.py (the deterministic naturalizer)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from naturalize_support import (
    CASES,
    OPEN,
    bold,
    dash,
    kept,
    names,
    out,
    probe,
    read,
    total,
)
from stylometry import CATEGORY
from stylometry import naturalize as nat

POSITIVE = (
    "bold_lead_in",
    "em_dash_density",
    "template_heading",
    "emoji_heading",
    "hedge_double",
    "delve_family",
    "worth_noting",
    "fast_paced_world",
)
ADVERSARIAL = ("natural", "protected_only")


# --- fixtures ----------------------------------------------------------------------------------


def test_every_case_directory_has_a_before_and_an_after():
    dirs = sorted(p.name for p in CASES.iterdir() if p.is_dir())
    assert set(dirs) == {*POSITIVE, *ADVERSARIAL, "preservation"}
    assert all((CASES / d / f).is_file() for d in dirs for f in ("before.md", "after.md"))


@pytest.mark.parametrize("case", sorted(p.name for p in CASES.iterdir() if p.is_dir()))
def test_the_output_is_exactly_the_golden_after(case: str):
    assert out(read(case)) == read(case, "after.md")


@pytest.mark.parametrize("name", POSITIVE)
def test_a_positive_fixture_lowers_its_own_signal_and_only_touches_it(name: str):
    result = nat.naturalize(read(name))
    assert {t.signal for t in result.transforms} == {name}
    assert total(result.after, name) < total(result.before, name)
    assert result.after.score < result.before.score


@pytest.mark.parametrize("name", ADVERSARIAL)
def test_adversarial_input_comes_back_byte_identical(name: str):
    result = nat.naturalize(read(name))
    assert result.text == read(name)
    assert not result.changed


def test_protected_only_opens_the_gates_so_identity_is_the_engines_doing():
    assert {"delve_family", "worth_noting", "hedge_double"} <= names(
        nat.naturalize(read("protected_only")).before
    )


def test_natural_text_with_sub_threshold_habits_is_left_alone():
    # one lead-in, one dash and one hedge are all below the detector's gates
    assert {"bold_lead_in", "em_dash_density"}.isdisjoint(
        names(nat.naturalize(read("natural")).before)
    )


def test_the_engine_only_claims_signals_the_detector_knows():
    assert set(nat.TRANSFORMS) <= set(CATEGORY)
    assert all(gate <= set(CATEGORY) for gate in nat._GATES.values())


# --- idempotence and structure -----------------------------------------------------------------

CORPUS = [
    *(CASES / case / "before.md" for case in (*POSITIVE, *ADVERSARIAL, "preservation")),
    ROOT / "README.md",
    ROOT / "docs" / "DONE.md",
    ROOT / "docs" / "TODO.md",
]


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_running_twice_gives_the_same_text_as_running_once(path: Path):
    once = out(path.read_bytes().decode("utf-8"))
    again = nat.naturalize(once)
    assert again.text == once
    assert not again.changed


@pytest.mark.parametrize("subset", [{"em_dash_density"}, {"hedge_double", "worth_noting"}])
def test_a_signal_subset_is_idempotent_too(subset: set[str]):
    once = out(read("preservation"), signals=subset)
    assert out(once, signals=subset) == once


@pytest.mark.parametrize("case", [*POSITIVE, "preservation"])
def test_lines_are_never_added_removed_or_touched_without_a_record(case: str):
    before = read(case)
    result = nat.naturalize(before)
    old, new = before.split("\n"), result.text.split("\n")
    assert len(old) == len(new)
    touched = {t.line for t in result.transforms}
    assert [i for i, (a, b) in enumerate(zip(old, new, strict=True), 1) if a != b] == sorted(
        touched
    )


def test_each_lines_own_ending_survives():
    text = "# Why this matters\r\nVale notar que sim.\rCabe destacar que não.\n\nfim"
    result = out(text)
    assert re.findall(r"\r\n|\n|\r", result) == re.findall(r"\r\n|\n|\r", text)
    assert result == "# Relevance\r\nSim.\rNão.\n\nfim"


def test_a_transform_records_the_line_before_and_after():
    result = nat.naturalize("Olá.\nVale notar que sim.\n")
    [edit] = result.transforms
    assert edit == nat.Transform("worth_noting", 2, "Vale notar que sim.", "Sim.")


# --- preservation: one test per category -------------------------------------------------------


def test_numbers_and_number_ranges_stay():
    line = "Vale notar que 1234, 0.5, 50% e 2 MB valem 10—20 e 2020—2024 — fim."
    result = out(OPEN + line + "\n")
    for token in ("1234", "0.5", "50%", "2 MB", "10—20", "2020—2024"):
        assert token in result
    assert "Vale notar" not in result


def test_a_dash_between_a_digit_and_a_letter_is_not_a_range():
    assert dash("item 3—a seguir") == "item 3, a seguir"


@pytest.mark.parametrize(
    "h", ["3f7c25d", "deadbeef1234", "0123456789abcdef0123456789abcdef01234567"]
)
def test_hashes_stay(h: str):
    kept(h)


@pytest.mark.parametrize("span", ["`a — b delve into`", "``x ` y — z``"])
def test_inline_code_stays(span: str):
    kept(span)


@pytest.mark.parametrize(
    "span",
    [
        "https://exemplo.com/a—b?x=vale—notar",
        "http://exemplo.com/in—today",
        "www.exemplo.com/a—b",
        "ftp://h/a—b",
    ],
)
def test_urls_stay(span: str):
    kept(span)


@pytest.mark.parametrize(
    "span",
    [
        "E:\\Projetos\\Scripts\\x—y.py",
        "C:/dir/vale—notar.txt",
        "\\\\host\\share\\a—b",
        "/usr/local/bin/x—y",
        "./tools/x—y.py",
        "~/docs/a—b",
        "docs/DONE—old.md",
    ],
)
def test_paths_stay(span: str):
    kept(span)


@pytest.mark.parametrize(
    "span",
    ['"vale notar que — isso"', "“in today's fast-paced world, — x”", "«pode ser que talvez — x»"],
)
def test_literal_quotes_stay(span: str):
    kept(span)


@pytest.mark.parametrize(
    "span", ["snake_case_name", "CamelCaseName", "camelCaseName", "UPPER_CASE", "API"]
)
def test_identifiers_stay(span: str):
    kept(span)


def test_an_identifier_after_a_dropped_lead_in_is_not_capitalised():
    assert probe("Vale notar que get_user falha.") == "get_user falha."
    assert probe("Vale notar que o parser falha.") == "O parser falha."


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
def test_fenced_blocks_stay(fence: str):
    block = f"{fence}\nvale notar que — delve into\nIn today's fast-paced world, x\n{fence}"
    result = out(f"{OPEN}{block}\n")
    assert block in result
    assert "We delve" not in result  # the prose above the block was worked on


@pytest.mark.parametrize(
    "block",
    [
        "    vale notar que — código\n    **Termo** — x",
        "\tvale notar que — código",
        "    a — b\n\n    vale notar que — c",  # a blank line does not end the block
    ],
)
def test_indented_code_stays(block: str):
    result = out(f"{OPEN}Exemplo:\n\n{block}\n\nFim.\n")
    assert block in result
    assert "We delve" not in result  # the prose around it was worked on


def test_an_indented_line_inside_a_list_or_a_paragraph_is_not_code():
    assert "continua, aqui" in out(f"{OPEN}- item\n\n    continua — aqui\n")
    assert "lazy, b" in out(f"{OPEN}Texto longo\n    lazy — b\n")


def test_code_after_a_list_and_a_paragraph_is_code_again():
    block = "    código — x"
    assert block in out(f"{OPEN}- item\n\nParágrafo.\n\n{block}\n")


@pytest.mark.parametrize("underline", ["=============", "-------------", "  ===  "])
def test_a_setext_title_stays_because_its_anchor_must_not_move(underline: str):
    title = f"Título — sub\n{underline}"
    result = out(f"{OPEN}{title}\n\nVeja [x](#título--sub).\n")
    assert title in result


def test_a_rule_after_a_list_item_or_an_atx_heading_is_not_a_setext_underline():
    assert "- item, x\n---" in out(f"{OPEN}- item — x\n---\n")
    assert "# Título — sub\n---" in out(f"{OPEN}# Título — sub\n---\n")


def test_an_unclosed_fence_protects_the_rest_of_the_file():
    text = "```\nVale notar que — a. B — c. D — e.\n"
    assert out(text) == text


def test_tables_stay():
    row = "| a — b | vale notar que x |"
    result = out(f"{OPEN}{row}\n|---|---|\n| delve into | y |\n")
    assert row in result
    assert "| delve into | y |" in result


def test_block_quotes_stay():
    quote = "> Vale notar que a citação — literal — não muda."
    assert quote in out(f"{OPEN}{quote}\n")


def test_front_matter_stays():
    front = "---\ntitle: Vale notar que — isto\n---"
    assert out(f"{front}\n\n{OPEN}").startswith(front)


def test_front_matter_that_never_closes_is_not_swallowed():
    assert out("---\ntitle: x\n\nVale notar que sim.\n") == "---\ntitle: x\n\nSim.\n"


def test_a_different_fence_does_not_close_a_block():
    block = "```\nvale notar que — x\n~~~\nvale notar que — y\n```"
    assert block in out(f"{OPEN}{block}\n")


def test_a_horizontal_rule_is_not_front_matter():
    assert out("---\n\nVale notar que sim.\n").endswith("Sim.\n")


def test_link_targets_html_tags_and_emails_stay():
    kept(
        "](https://e.com/a—b)",
        "Vale notar que [x](https://e.com/a—b) e [y](https://e.com/a—b) — fim.",
    )
    kept('<a href="x—y">', 'Vale notar que <a href="x—y">z</a> e <a href="x—y">w</a> — fim.')


def test_an_email_address_is_not_capitalised_after_a_dropped_lead_in():
    assert probe("Vale notar que joao@ex.com escreveu.") == "joao@ex.com escreveu."


def test_link_reference_definitions_stay():
    definition = "[ref]: https://e.com/vale—notar"
    assert definition in out(f"{OPEN}{definition}\n")


def test_preserve_globs_protect_matching_lines_only():
    text = "Vale notar que sim. Fonte: x.\nVale notar que não.\n"
    assert out(text, preserve=["*Fonte*"]) == "Vale notar que sim. Fonte: x.\nNão.\n"


def test_a_masked_span_is_reported_with_its_kind_and_line():
    result = nat.naturalize(read("preservation"))
    kinds = {(s.kind, s.line) for s in result.preserved}
    assert {("front matter", 1), ("code block", 19), ("table", 15)} <= kinds
    assert {k for k, _ in kinds} >= {"code", "url", "quote", "hash", "path", "identifier", "link"}
    [table] = [s for s in result.preserved if s.kind == "table"]
    assert table.text.endswith("(+2 linhas)")


def test_nothing_fired_means_nothing_was_masked():
    assert nat.naturalize(read("natural")).preserved == ()


# --- each transformation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("**Termo** — x", "Termo: x"),
        ("**Termo** – x", "Termo: x"),
        ("**Termo** - x", "Termo: x"),
        ("**Termo**: x", "Termo: x"),
        ("**Termo:** x", "Termo: x"),
        ("**Termo:**", "Termo:"),
        ("- **Termo** — x", "- Termo: x"),
        ("  * **Termo:** x", "  * Termo: x"),
        ("1. **Termo** — x", "1. Termo: x"),
        ("2) **Termo** — `c` e mais", "2) Termo: `c` e mais"),
        ("**Termo.** — x", "**Termo.** — x"),  # ends in a stop: not a lead-in
        ("**termo** — x", "**termo** — x"),  # lowercase label: the detector skips it
        ("Texto **Termo** — x", "Texto **Termo** — x"),  # not at the start of the line
        ("**Termo**-x", "**Termo**-x"),  # no gap after the separator
        ("**Termo** x", "**Termo** x"),  # no separator
        ("> **Termo** — x", "> **Termo** — x"),  # block quote
        ("**`code`** — x", "**`code`** — x"),  # label starts with code
    ],
)
def test_bold_lead_in(line: str, expected: str):
    assert bold(line) == expected  # one stray dash is below the dash gate, so it stays


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("a — b", "a, b"),
        ("a—b", "a, b"),
        ("a —b", "a, b"),
        ("a— b", "a, b"),
        ("a — 20", "a, 20"),
        ("`c` — b", "`c`, b"),
        ("10—20", "10—20"),
        ("a —, b", "a —, b"),
        ("— a", "— a"),
        ("a —", "a —"),
        ("Fim. — x", "Fim. — x"),
        ("a — — b", "a — — b"),
        ("# Título — sub", "# Título — sub"),
        ("- — x", "- — x"),
    ],
)
def test_em_dash(line: str, expected: str):
    assert dash(line) == expected


def test_a_chain_of_dashes_becomes_a_chain_of_commas():
    assert dash("A — b — c — d") == "A, b, c, d"


def test_the_comma_ratio_alone_opens_the_dash_gate():
    plain = "Uma frase simples sem nada. " * 13
    text = plain + "A — b, c, d. E — f, g, h. I — j, k, l."
    before = nat.naturalize(text).before
    assert names(before) >= {"em_dash_to_comma_ratio"}
    assert "em_dash_density" not in names(before)
    assert nat.naturalize(text).changed


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Why this matters", "Relevance"),
        ("Why It Matters?", "Relevance"),
        ("What’s next", "Next steps"),
        ("What this means:", "Implications"),
        ("The bottom line", "Summary"),
        ("Por que isso importa", "Relevância"),
        ("Por que isso é importante", "Relevância"),
        ("O que isso significa", "Implicações"),
        ("O que vem a seguir", "Próximos passos"),
        ("A linha de fundo", "Conclusão"),
        ("O que saiu", "O que saiu"),  # the detector counts it; the dictionary does not know it
        ("Why not?", "Why not?"),
        ("Why `this` matters", "Why `this` matters"),
    ],
)
def test_template_heading(title: str, expected: str):
    assert probe(f"## {title}", signals={"template_heading"}) == f"## {expected}".rstrip()


def test_a_template_heading_keeps_its_spacing():
    assert probe("##  Por   que   importa  ", signals={"template_heading"}) == "##  Relevância  "


def test_a_template_heading_keeps_its_symbol_prefix_and_level():
    assert probe("### 🚀 Why this matters", signals={"template_heading"}) == "### 🚀 Relevance"


def test_a_template_heading_with_an_anchor_pointing_at_it_stays():
    text = "## Why this matters\n\nVeja [aqui](#why-this-matters).\n"
    assert out(text, signals={"template_heading"}) == text


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("✅ Resultado", "Resultado"),
        ("Resultado ✅", "Resultado"),
        ("Antes 🚀 depois", "Antes depois"),
        ("❤️ Amor", "Amor"),
        ("👨‍👩‍👧 Família", "Família"),
        ("🎉", "🎉"),  # nothing would be left
        ("Sem emoji", "Sem emoji"),
    ],
)
def test_emoji_heading(title: str, expected: str):
    got = probe(f"## {title}", signals={"emoji_heading"})
    assert got == f"## {expected}"


def test_emoji_outside_a_heading_stays_and_an_anchor_protects_the_title():
    assert probe("Feito ✅ hoje.", signals={"emoji_heading"}) == "Feito ✅ hoje."
    text = "## 🔥 Destaque\n\n[x](#-destaque)\n"
    assert out(text, signals={"emoji_heading"}) == text


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("In today's fast-paced world, teams ship.", "Teams ship."),
        ("In today’s digital age, teams ship.", "Teams ship."),
        ("No mundo de hoje, o prazo encurta.", "O prazo encurta."),
        ("Em um mundo cada vez mais digital, o prazo encurta.", "O prazo encurta."),
        ("Nos dias de hoje, vale testar.", "Vale testar."),
        ("Na era da informação, o prazo encurta.", "O prazo encurta."),
        ("In today's fast-paced world, in today's digital age, teams ship.", "Teams ship."),
        ("Antes. In today's fast-paced world, teams ship.", "Antes. Teams ship."),
        ("- Na era digital, a lista perde.", "- A lista perde."),
        ("A equipe viu que in today's fast-paced world, nada muda.", None),  # mid-sentence
        ("In today's fast-paced world teams ship.", None),  # no comma after the lead
        ("In today's fast-paced world, `x` ship.", "`x` ship."),
    ],
)
def test_fast_paced_world(line: str, expected: str | None):
    assert probe(line, signals={"fast_paced_world"}) == (expected or line)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Vale notar que o parser é linear.", "O parser é linear."),
        ("Vale a pena destacar que o parser é linear.", "O parser é linear."),
        ("É importante notar que o parser é linear.", "O parser é linear."),
        ("Importante ressaltar que o parser é linear.", "O parser é linear."),
        ("Cabe destacar que o parser é linear.", "O parser é linear."),
        ("Além disso, é importante notar que o parser é linear.", "Além disso, o parser é linear."),
        ("Mas vale notar que o parser é linear.", "Mas o parser é linear."),
        ("Sai em JSON, e vale lembrar que o diff sai.", "Sai em JSON, e o diff sai."),
        ("Antes. Vale notar que o parser é linear.", "Antes. O parser é linear."),
        ("- Vale notar que o parser é linear.", "- O parser é linear."),
        ("It's worth noting that the tool is pure.", "The tool is pure."),
        ("It is also worth mentioning that the tool is pure.", "The tool is pure."),
        ("It is important to note that the tool is pure.", "The tool is pure."),
        ("Worth noting that the tool is pure.", "The tool is pure."),
        ("Vale notar que vale notar que o parser é linear.", "O parser é linear."),
        ("Não é importante notar que o parser muda.", None),  # negation
        ("Porque vale notar que o parser muda.", None),  # not a clause start
        ("Vale notar: o parser muda.", None),  # no "que"
    ],
)
def test_worth_noting(line: str, expected: str | None):
    assert probe(line, signals={"worth_noting"}) == (expected or line)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("We delve into the logs.", "We look at the logs."),
        ("Delve into the logs.", "Look at the logs."),
        (
            "She delves into it, he delved into it, we keep delving into it.",
            "She looks at it, he looked at it, we keep looking at it.",
        ),
        ("Delve deeper into the logs.", "Look closer at the logs."),
        ("Let's dive into the logs.", "Let's look at the logs."),
        ("We'll dive deeper into the logs.", "We'll look closer at the logs."),
        ("It is safe to dive into the lake.", None),  # literal: "to" is not a lead-in
        ("Divers dive into the water.", None),  # literal, no lead-in
        ("Dive in.", None),  # no object to keep
        ("We delve the logs.", None),  # not followed by "into"
    ],
)
def test_delve_family(line: str, expected: str | None):
    got = probe(line, signals={"delve_family"})
    assert got == (expected if expected is not None else line)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Pode ser que talvez o serviço caia.", "Talvez o serviço caia."),
        ("pode ser que talvez o serviço caia.", "talvez o serviço caia."),
        ("Talvez pode ser que o serviço caia.", "Pode ser que o serviço caia."),
        ("Arguably perhaps it fails.", "Perhaps it fails."),
        ("Possibly maybe perhaps it fails.", "Perhaps it fails."),
        ("Talvez o erro venha do cache, mas talvez não.", None),  # not adjacent
        ("Talvez, possivelmente, caia.", None),  # separated by a comma
    ],
)
def test_hedge_double(line: str, expected: str | None):
    assert probe(line, signals={"hedge_double"}) == (expected or line)


# --- gates, filters and the pass loop ----------------------------------------------------------


def test_a_signal_below_its_gate_is_not_touched():
    two_leads = "- **Um** — a\n- **Dois** — b\n"
    assert out(two_leads) == two_leads


def test_the_signals_filter_limits_what_runs():
    result = nat.naturalize(read("preservation"), signals={"hedge_double"})
    assert {t.signal for t in result.transforms} == {"hedge_double"}
    assert not nat.naturalize(read("preservation"), signals={"nope"}).changed
    assert not nat.naturalize(read("preservation"), signals=set()).changed


def test_triggers_that_uncover_each_other_converge():
    line = "In today's fast-paced world, vale notar que no mundo de hoje, o cache é opcional."
    assert probe(line) == "O cache é opcional."


def test_the_pass_cap_stops_a_chain_and_a_rerun_finishes_it(monkeypatch: pytest.MonkeyPatch):
    line = "In today's fast-paced world, vale notar que no mundo de hoje, o cache é opcional.\n"
    monkeypatch.setattr(nat, "MAX_PASSES", 1)
    capped = out(line)
    assert capped == "No mundo de hoje, o cache é opcional.\n"
    assert out(capped) == "O cache é opcional.\n"


def test_private_use_characters_in_the_text_are_left_alone():
    a, b = chr(0xE000), chr(0xE001)  # the two the masker would pick first
    assert out(f"Vale notar que `x` e {a} e {b}.") == f"`x` e {a} e {b}."


def test_a_text_that_uses_every_private_use_character_is_refused():
    text = "".join(map(chr, range(0xE000, 0xF900))) + "\nVale notar que sim.\n"
    with pytest.raises(ValueError, match="uso privado"):
        nat.naturalize(text)
