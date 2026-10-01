"""Prose signals: lexical tics, structural templates and cadence metrics.

Input is markdown-ish text (also what the loaders extract from HTML, DOCX and PDF). Fenced code
and front matter are blanked before analysis, which keeps line numbers aligned with the original
file. Cost is linear in the input size: the patterns are anchored or bounded and a block's joined
text is computed once, which the tests check against adversarial blobs (see the perf tests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from statistics import mean, pstdev

from . import (
    MAX_OCCURRENCES,
    Analysis,
    Hit,
    Signal,
    by_below,
    by_count,
    clean,
    metric,
    occurrences,
    score_signals,
    split_lines,
)

MAX_BLOCKS = 50_000

_FRONT_KEY = re.compile(r"^[\w.-]+\s*:")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[\"'“‘(\[*_]*[A-ZÀ-ÖØ-Þ0-9])")
_WORD = re.compile(r"[^\W_][\w'’-]*")
_TEXTY = ("prose", "list", "heading")


@dataclass(frozen=True)
class Block:
    kind: str  # heading | table | list | prose
    start: int  # 1-based line of the first line
    lines: tuple[str, ...]

    @cached_property
    def text(self) -> str:
        return "\n".join(self.lines)

    @cached_property
    def flat(self) -> str:
        return " ".join(line.strip() for line in self.lines)


def _mask(lines: list[str]) -> list[str]:
    """Blank front matter and fenced code so they never match, without shifting line numbers.

    Front matter is only a leading ``---`` whose next line is a ``key:`` line; a horizontal rule
    at the top of a document must not swallow everything up to the next one.
    """
    out = list(lines)
    start = 0
    if len(out) > 1 and out[0].strip() == "---" and _FRONT_KEY.match(out[1]):
        end = next(
            (i for i in range(1, min(len(out), 200)) if out[i].strip() in ("---", "...")), None
        )
        if end is not None:
            out[: end + 1] = [""] * (end + 1)
            start = end + 1
    fence = ""  # the opening run of ` or ~, empty outside a fence
    for i in range(start, len(out)):
        m = _FENCE.match(out[i])
        if not fence and m:
            fence = m[1]
        elif fence and m and _closes(fence, m[1], out[i]):
            fence = ""
        elif not fence:
            continue
        out[i] = ""
    return out


def _closes(opener: str, run: str, line: str) -> bool:
    """A closing fence repeats the opener's character at least as many times and has no info
    string: a ``` line inside a ```` block is content. The naturalizer uses this same rule to
    decide where a fence ends, so the two agree on fenced code. It also protects things the
    detector still scores (tables, quotes, indented code); only the fence is shared."""
    return run[0] == opener[0] and len(run) >= len(opener) and not line.lstrip()[len(run) :].strip()


def _kind(line: str, previous: str | None) -> str | None:
    if not line.strip():
        return None
    if _HEADING.match(line):
        return "heading"
    if line.lstrip().startswith("|"):
        return "table"
    if _LIST.match(line) or (previous == "list" and line[0].isspace()):
        return "list"
    return "prose"


def _blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    kind: str | None = None
    start = 1
    buf: list[str] = []
    for n, line in enumerate(lines, 1):
        k = _kind(line, kind)
        if k != kind or k == "heading":
            if kind is not None:
                blocks.append(Block(kind, start, tuple(buf)))
            kind, start, buf = k, n, []
        if k is not None:
            buf.append(line)
    if kind is not None:
        blocks.append(Block(kind, start, tuple(buf)))
    return blocks


def _sentences(flat: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(flat.strip()) if s.strip()]


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _snip(text: str, m: re.Match[str]) -> str:
    return " ".join(text[max(0, m.start() - 25) : m.end() + 25].split())[:100]


def _hits(blocks: list[Block], rx: re.Pattern[str], kinds: tuple[str, ...] = _TEXTY) -> list[Hit]:
    """Matches with their original line. Offsets run across blocks; line counting is incremental,
    so many hits in one giant block stay linear."""
    found: list[Hit] = []
    base = 0
    for b in blocks:
        if b.kind not in kinds:
            continue
        text = b.text
        line, seen = b.start, 0
        for m in rx.finditer(text):
            line += text.count("\n", seen, m.start())
            seen = m.start()
            found.append(Hit(line, _snip(text, m), base + m.start()))
        base += len(text) + 1
    return found


def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


# --- lexical -----------------------------------------------------------------------------------

_NOT_JUST_BUT = _rx(
    r"\bn[ãa]o\s+(?:é|foi|s[ãa]o|era)\s+(?:apenas|s[óo]|somente|meramente|simplesmente)\b"
    r"[^.!?]{1,120}?[,;:—–-]\s*(?:é|foi|s[ãa]o|era|mas)\b",
    r"\b(?:it|this|that)(?:\s+is\s+not|\s+isn['’]t|['’]s\s+not)\s+(?:just|only|merely|simply)\b"
    r"[^.!?]{1,120}?[,;:—–-]\s*(?:it|this|that)(?:\s+is|['’]s)\b",
    r"\bnot\s+just\b[^.!?]{1,80}?,\s*it['’]s\b",
)
# "explore"/"unpack" only count after a lead-in: alone they are ordinary verbs.
_DELVE = _rx(
    r"\bdelv(?:e|es|ed|ing)\b",
    r"\bdiv(?:e|es|ing)\s+(?:in|into|deeper)\b",
    r"\b(?:let['’]s|let\s+us|we['’]ll|we\s+will|vamos)\s+"
    r"(?:explore|unpack|explorar|desvendar|mergulhar)\b",
    r"\bmergulh(?:ar|emos|e)\s+(?:em|no|na|nos|nas|fundo)\b",
)
_WORTH = _rx(
    r"\bvale\s+(?:a\s+pena\s+)?(?:notar|destacar|ressaltar|mencionar|lembrar)\b",
    r"\bimportante\s+(?:ressaltar|destacar|notar|mencionar|lembrar)\b",
    r"\bcabe\s+(?:destacar|ressaltar|notar)\b",
    r"\bit(?:['’]s|\s+is)\s+(?:also\s+)?(?:worth\s+(?:noting|mentioning)"
    r"|important\s+to\s+(?:note|mention))\b",
    r"\bworth\s+noting\b",
)
_FAST = _rx(
    r"\bin\s+today['’]s\s+(?:fast-paced|fast\s+paced|ever-(?:changing|evolving)|digital|modern)\b",
    r"\bin\s+an?\s+(?:era|world|age)\s+where\b",
    r"\bem\s+um\s+mundo\s+(?:onde|cada\s+vez\s+mais)\b",
    r"\bno\s+mundo\s+(?:atual|de\s+hoje|moderno)\b",
    r"\bnos\s+dias\s+de\s+hoje\b",
    r"\bna\s+era\s+(?:digital|da\s+informa[cç][aã]o)\b",
)
_H = r"(?:pode\s+ser\s+que|talvez|possivelmente|quem\s+sabe|arguably|perhaps|maybe|possibly)"
_HEDGE = _rx(rf"\b{_H}\W+(?:\w+\W+){{0,2}}?{_H}\b")
_META = _rx(
    r"\bnesta\s+se[cç][aã]o\b",
    r"\bneste\s+(?:cap[ií]tulo|t[oó]pico|artigo|texto|guia)\b",
    r"\bcomo\s+(?:j[aá]\s+)?vimos\b",
    r"\bcomo\s+(?:j[aá]\s+)?(?:mencionado|discutido|visto)\s+(?:acima|anteriormente)\b",
    r"\bna\s+pr[oó]xima\s+se[cç][aã]o\b",
    r"\bin\s+this\s+(?:section|article|post|guide|chapter)\b",
    r"\bas\s+we(?:['’]ve|\s+have)\s+seen\b",
    r"\bas\s+(?:mentioned|discussed)\s+(?:above|earlier|previously)\b",
    r"\bin\s+the\s+next\s+section\b",
)
_WHY = _rx(
    r"\baqui\s+est[aá]\s+(?:por\s+qu[eê]|o\s+porqu[eê])\s*:",
    r"\bhere(?:['’]s|\s+is)\s+why\s*:",
)
_OTHER_HAND = _rx(r"\bpor\s+outro\s+lado\b", r"\bon\s+the\s+other\s+hand\b")
_CLOSE = _rx(
    r"\bn[ãa]o\s+(?:é|foi|s[ãa]o|era)\s+[^.!?]{1,60}[.!]\s+(?:é|foi|s[ãa]o|era)\b",
    r"\b(?:it|this|that)(?:\s+is\s+not|\s+isn['’]t|['’]s\s+not)\s+[^.!?]{1,60}[.!]\s+"
    r"(?:it|this|that)(?:\s+is|['’]s)\b",
)

# name, pattern, (low, medium, high) thresholds on the number of hits
_LEXICAL = (
    ("not_just_but", _NOT_JUST_BUT, (1, 2, 3)),
    ("delve_family", _DELVE, (1, 2, 3)),
    ("worth_noting", _WORTH, (1, 2, 4)),
    ("fast_paced_world", _FAST, (None, 1, 2)),
    ("hedge_double", _HEDGE, (1, 2, 3)),
    ("meta_commentary", _META, (1, 2, 4)),
    ("here_is_why", _WHY, (1, 2, 3)),
)


def _lexical(blocks: list[Block]) -> list[Signal]:
    out: list[Signal] = []
    for name, rx, tiers in _LEXICAL:
        found = _hits(blocks, rx)
        out += occurrences(name, found, by_count(len(found), *tiers))
    return out


def _cascade(blocks: list[Block]) -> list[Signal]:
    """3+ "por outro lado" inside one 2500-character window (two pointers, linear)."""
    found = _hits(blocks, _OTHER_HAND)
    densest, j = 0, 0
    for i, hit in enumerate(found):
        while found[j].pos < hit.pos - 2500:
            j += 1
        densest = max(densest, i - j + 1)
    return occurrences("on_the_other_hand_cascade", found, by_count(densest, medium=3, high=5))


def _declarative_close(blocks: list[Block]) -> list[Signal]:
    prose = [b.start for b in blocks if b.kind == "prose"]
    closing = prose[-1] if prose else 0
    found = _hits(blocks, _CLOSE)
    return [
        Signal(
            "declarative_close",
            len(found),
            "medium" if h.line >= closing else "low",
            h.line,
            clean(h.snippet),
        )
        for h in found[:MAX_OCCURRENCES]
    ]


# --- structural --------------------------------------------------------------------------------

_BOLD = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?\*\*([^*\n]+?)\*\*(\s*[—–:-])?")
_TEMPLATE = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:[^\w\s]+\s*)?(?:por\s+qu[eê]|o\s+que|a\s+linha|why|what|the\s+bottom)\b",
    re.IGNORECASE,
)
# Emoji blocks plus dingbats (the check marks, warning signs and sparkles assistants like).
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
_CONJ = re.compile(r"\s(?:and|or|e|ou)\s", re.IGNORECASE)
_LEAD_CONJ = re.compile(r"(?:and|or|e|ou)\s+", re.IGNORECASE)
_SEPARATOR = re.compile(r":?-+:?")


def _bold_lead_in(blocks: list[Block]) -> list[Signal]:
    found: list[Hit] = []
    for b in blocks:
        if b.kind not in ("prose", "list"):
            continue
        for n, line in enumerate(b.lines, b.start):
            m = _BOLD.match(line)
            if not m:
                continue
            label = m[1].strip()
            if label[:1].isupper() and (m[2] or label.endswith(":")):
                found.append(Hit(n, line.strip()[:100]))
    return occurrences("bold_lead_in", found, by_count(len(found), 3, 6, 12))


def _is_tricolon(sentence: str) -> bool:
    """Exactly three short items, with or without the Oxford comma."""
    parts = [p.strip() for p in sentence.rstrip(".!?… ").split(",")]
    if len(parts) < 2:
        return False
    tail = parts[-1]
    if lead := _LEAD_CONJ.match(tail):
        items = [*parts[:-1], tail[lead.end() :]]
    else:
        pair = _CONJ.split(tail, maxsplit=1)
        if len(pair) != 2:
            return False
        items = [*parts[:-1], *pair]
    return len(items) == 3 and all(1 <= len(i.split()) <= 6 for i in items)


def _tricolons(blocks: list[Block]) -> list[Signal]:
    """The longest run of consecutive prose paragraphs that each contain a three-item series."""
    runs: list[list[Hit]] = []
    run: list[Hit] = []
    for b in blocks:
        first = None
        if b.kind == "prose":
            first = next((s for s in _sentences(b.flat) if _is_tricolon(s)), None)
        if first is None:
            runs.append(run)
            run = []
        else:
            run.append(Hit(b.start, first[:100]))
    runs.append(run)
    longest = max(runs, key=len)
    return occurrences("tricolon_uniform", longest, by_count(len(longest), medium=3, high=5))


def _headings(blocks: list[Block]) -> list[Signal]:
    heads = [b for b in blocks if b.kind == "heading"]
    template = [
        Hit(b.start, b.lines[0].strip()[:100]) for b in heads if _TEMPLATE.match(b.lines[0])
    ]
    emoji = [Hit(b.start, b.lines[0].strip()[:100]) for b in heads if _EMOJI.search(b.lines[0])]
    return occurrences(
        "template_heading", template, by_count(len(template), 1, 2, 3)
    ) + occurrences("emoji_heading", emoji, by_count(len(emoji), 1, 2, 4))


def _table_symmetry(blocks: list[Block]) -> list[Signal]:
    """Tables whose columns all have (within 10%) the same average cell length."""
    found: list[Hit] = []
    for b in blocks:
        if b.kind != "table":
            continue
        rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in b.lines]
        rows = [r for r in rows if not all(_SEPARATOR.fullmatch(c) for c in r)]
        if len(rows) < 3 or len({len(r) for r in rows}) != 1 or len(rows[0]) < 2:
            continue
        means = [mean(len(r[j]) for r in rows) for j in range(len(rows[0]))]
        avg = mean(means)
        if avg >= 4 and all(abs(m - avg) <= 0.10 * avg for m in means):
            found.append(Hit(b.start, b.lines[0].strip()[:100]))
    return occurrences("comparison_table_symmetry", found, by_count(len(found), medium=1, high=2))


# --- metrics -----------------------------------------------------------------------------------


def _cadence(blocks: list[Block]) -> list[Signal]:
    prose = [b for b in blocks if b.kind == "prose"]
    per_paragraph = [_sentences(b.flat) for b in prose]
    sentences = [s for para in per_paragraph for s in para]
    out: list[Signal] = []
    if len(prose) >= 5:
        sd = pstdev([len(p) for p in per_paragraph])
        out += metric(
            "paragraph_uniformity",
            sd,
            by_below(sd, medium=0.5, high=0.25),
            f"{len(prose)} parágrafos, desvio de {sd:.2f} frases",
        )
        sd = pstdev([len(_words(b.flat)) for b in prose])
        out += metric(
            "paragraph_length_stddev",
            sd,
            by_below(sd, low=12, medium=8, high=4),
            f"desvio de {sd:.1f} palavras por parágrafo",
        )
    if len(sentences) >= 8:
        sd = pstdev([len(_words(s)) for s in sentences])
        detail = f"{len(sentences)} frases, desvio de {sd:.2f} palavras"
        out += metric("sentence_uniformity", sd, by_below(sd, medium=5, high=3), detail)
        # Band just above the structural threshold, so one quantity is not counted twice.
        out += metric("sentence_length_stddev", sd, "low" if 5 <= sd < 7 else None, detail)
    return out


def _dashes(texty: list[Block]) -> list[Signal]:
    dashes = sum(b.text.count("—") for b in texty)
    if dashes < 3:
        return []
    sentences = sum(
        len(_sentences(b.flat)) if b.kind == "prose" else len(b.lines) if b.kind == "list" else 1
        for b in texty
    )
    commas = sum(b.text.count(",") for b in texty)
    density, ratio = dashes / max(sentences, 1), dashes / max(commas, 1)
    return metric(
        "em_dash_density",
        density,
        by_count(density, 0.20, 0.40, 0.80),
        f"{dashes} em-dash em {sentences} frases",
    ) + metric(
        "em_dash_to_comma_ratio",
        ratio,
        by_count(ratio, 0.15, 0.30, 0.60),
        f"{dashes} em-dash para {commas} vírgulas",
    )


def _ttr(words: list[str]) -> list[Signal]:
    """Type-token ratio of the first 300 words (it falls with length, so the window is fixed)."""
    if len(words) < 100:
        return []
    window = [w.lower() for w in words[:300]]
    ratio = len(set(window)) / len(window)
    return metric(
        "type_token_ratio",
        ratio,
        by_below(ratio, low=0.50, medium=0.42, high=0.35),
        f"{len(set(window))} únicas em {len(window)} palavras",
    )


def analyze(text: str) -> Analysis:
    blocks = _blocks(_mask(split_lines(text)))
    notes: tuple[str, ...] = ()
    if len(blocks) > MAX_BLOCKS:  # linear cost, but ~30 µs per block: bound the worst case
        blocks = blocks[:MAX_BLOCKS]
        notes = (f"texto muito longo: só os primeiros {MAX_BLOCKS} blocos foram analisados",)
    texty = [b for b in blocks if b.kind in _TEXTY]
    words = [w for b in texty for w in _words(b.text)]
    signals = [
        *_lexical(blocks),
        *_cascade(blocks),
        *_declarative_close(blocks),
        *_bold_lead_in(blocks),
        *_tricolons(blocks),
        *_headings(blocks),
        *_table_symmetry(blocks),
        *_cadence(blocks),
        *_dashes(texty),
        *_ttr(words),
    ]
    signals.sort(key=lambda s: (s.line is None, s.line or 0, s.name))
    confidence = "low" if len(words) < 150 else "medium" if len(words) < 600 else "high"
    return Analysis(signals, score_signals(signals), confidence, notes)
