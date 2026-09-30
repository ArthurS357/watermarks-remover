"""Deterministic naturalizer: rewrites the prose habits ``text.py`` detects, and nothing else.

No model, no network. Each transformation is one regex over one line, gated by the detector: it runs
only while ``text.analyze`` still reports its signal, so a signal the detector does not see is never
touched. The passes repeat until the text stops changing, which makes the result idempotent by
construction: running it again starts from the same text with the same gate.

Anything that could carry a fact is masked before the regexes run and restored afterwards: fenced
code, front matter, tables and block quotes (whole lines); inline code, link targets, URLs, e-mails,
paths, quoted strings, HTML tags, hashes and identifiers (spans). Numbers are not masked: no
transformation matches a digit, and a dash between two digits is a range, so it stays.

The catalogue is deliberately small. See ``docs/TODO.md`` (round R11) for what is out of scope and why.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from itertools import islice
from typing import NamedTuple
from urllib.parse import unquote

from . import Analysis, clean
from . import text as text_signals
from .text import _EMOJI, _FENCE, _FRONT_KEY, _H, _LIST

MAX_PASSES = 20  # every pass removes triggers and none creates one, so this is a safety net

_EOL = re.compile(r"(\r\n|\n|\r)")
_HEAD = re.compile(r"^(\s{0,3}#{1,6}[ \t]+)(.*)$")
_ANCHOR = re.compile(r"#([\w%-]+)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]\n]+\]:\s*\S")
_SETEXT = re.compile(r"^\s{0,3}(?:=+|-+)[ \t]*$")


class Transform(NamedTuple):
    signal: str
    line: int  # 1-based; passes never add or remove lines, so it is stable
    before: str
    after: str


class Span(NamedTuple):
    kind: str
    line: int  # first line
    text: str


class Result(NamedTuple):
    text: str
    before: Analysis
    after: Analysis
    transforms: tuple[Transform, ...]
    preserved: tuple[Span, ...]

    @property
    def changed(self) -> bool:
        return bool(self.transforms)


# --- masking -----------------------------------------------------------------------------------

# "dive into" can be literal ("safe to dive into the lake"), so only lead-ins that announce a topic.
_VERB_LEAD = r"(?:let['’]s|let\s+us|let\s+me|we['’]ll|we\s+will|i['’]ll|i\s+will|shall\s+we)"

_INLINE = re.compile(
    "|".join(
        f"(?P<{kind}>{pattern})"
        for kind, pattern in (
            ("code", r"``[^\n]+?``|`[^`\n]+`"),
            ("link", r"\]\([^)\n]{0,500}\)"),
            ("html", r"<[A-Za-z/!][^>\n]{0,300}>"),
            ("url", r"\b(?:https?|ftp|file)://[^\s<>\"'`)\]]+|\bwww\.[^\s<>\"'`)\]]+"),
            ("email", r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
            # A span never contains its own opener: a run of unmatched openers would otherwise be
            # quadratic. Single quotes count only where an apostrophe cannot be (not after a letter).
            (
                "quote",
                r"\"[^\"\n]+\"|“[^“”\n]+”|«[^«»\n]+»|(?<![\w'])'[^'\n]{1,200}'(?![\w'])",
            ),
            (
                "path",
                r"(?<!\w)[A-Za-z]:[\\/][^\s\"'<>|*?`]*"
                r"|\\\\[\w.$-]+\\[^\s\"'<>|*?`]*"
                r"|(?<![\w/:.])(?:~|\.{1,2})?/[\w.@~+—-]+(?:/[\w.@~+—-]+)*"
                r"|(?<![\w/.—-])[\w.—-]+(?:/[\w.—-]+)+",
            ),
            ("hash", r"\b(?=[0-9a-f]{0,39}\d)(?=[0-9a-f]{0,39}[a-f])[0-9a-f]{7,40}\b"),
            (
                "identifier",
                r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b"
                r"|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b"
                r"|\b[a-z]+(?:[A-Z][a-z0-9]*)+\b"
                r"|\b[A-Z]{2}[A-Z0-9]*\b",  # {2,} next to [A-Z0-9]* backtracks quadratically
            ),
        )
    )
)


def _sentinels(text: str) -> tuple[str, str]:
    """Two private-use characters absent from ``text``, to bracket a placeholder."""
    free = list(islice((c for c in map(chr, range(0xE000, 0xF900)) if c not in text), 2))
    if len(free) < 2:
        raise ValueError("o texto usa todos os caracteres de uso privado")
    return free[0], free[1]


class _Masker:
    """Swaps protected spans for opaque placeholders and back."""

    def __init__(self, text: str) -> None:
        self.open, self.close = _sentinels(text)
        self._store: list[str] = []
        self._ref = re.compile(re.escape(self.open) + r"([0-9a-f]+)" + re.escape(self.close))
        self.spans: list[Span] = []

    def mask(self, line: str, number: int) -> str:
        def swap(m: re.Match[str]) -> str:
            self._store.append(m[0])
            self.spans.append(Span(str(m.lastgroup), number, clean(m[0])))
            return f"{self.open}{len(self._store) - 1:x}{self.close}"

        return _INLINE.sub(swap, line)

    def restore(self, line: str) -> str:
        return self._ref.sub(lambda m: self._store[int(m[1], 16)], line)


def _line_kinds(lines: list[str], preserve: Sequence[str]) -> list[str | None]:
    """Why each line is off limits (``None`` = editable). Mirrors ``text._mask`` for fences and
    front matter, so the engine and the detector agree on what is code."""
    kinds: list[str | None] = [None] * len(lines)
    start = 0
    if len(lines) > 1 and lines[0].strip() == "---" and _FRONT_KEY.match(lines[1]):
        end = next(
            (i for i in range(1, min(len(lines), 200)) if lines[i].strip() in ("---", "...")), None
        )
        if end is not None:
            kinds[: end + 1] = ["front matter"] * (end + 1)
            start = end + 1
    fence = ""  # the opening run of ` or ~, empty outside a fence
    state, gap = (
        "none",
        True,
    )  # the last non-blank line (none|prose|list|code) and a blank before it
    for i in range(start, len(lines)):
        line = lines[i]
        m = _FENCE.match(line)
        if not fence and m:
            fence, kinds[i] = m[1], "code block"
        elif fence:
            kinds[i] = "code block"
            if m and _closes(fence, m[1], line):
                fence = ""
        elif not line.strip():
            gap = True
            continue
        else:
            kinds[i], state = _classify(lines, i, state, gap, preserve)
            gap = False
            continue
        state, gap = "none", True
    return kinds


def _closes(opener: str, run: str, line: str) -> bool:
    """A closing fence repeats the opener's character at least as many times and has no info
    string: a ``` line inside a ```` block is content (``text._mask`` lets it close the block)."""
    return run[0] == opener[0] and len(run) >= len(opener) and not line.lstrip()[len(run) :].strip()


def _classify(
    lines: list[str], i: int, state: str, gap: bool, preserve: Sequence[str]
) -> tuple[str | None, str]:
    """The reason line ``i`` (outside a fence) is off limits, and the state for the next line.

    An indented line is code when it follows a blank line outside a list (or continues code): inside
    a list it is a continuation. A line over a ``===``/``---`` underline is a setext title, whose
    anchor must not move. Code indented inside a list item is not recognised (TODO R11)."""
    line = lines[i]
    indented = line.startswith(("    ", "\t"))
    if indented and (state == "code" or (gap and state != "list")):
        return "indented code", "code"
    stripped = line.lstrip()
    listed = bool(_LIST.match(line))
    kind = None
    if stripped.startswith("|"):
        kind = "table"
    elif stripped.startswith(">"):
        kind = "quote block"
    elif _REF_DEF.match(line):
        kind = "link definition"
    elif any(fnmatchcase(line.strip(), glob) for glob in preserve):
        kind = "preserve"
    elif (
        not listed and not _HEAD.match(line) and i + 1 < len(lines) and _SETEXT.match(lines[i + 1])
    ):
        kind = "setext title"
    return kind, "list" if listed or (state == "list" and indented) else "prose"


def _block_spans(kinds: list[str | None], lines: list[str]) -> list[Span]:
    """One span per run of protected lines of the same kind."""
    spans: list[Span] = []
    for i, kind in enumerate(kinds):
        if kind is None or (i and kinds[i - 1] == kind):
            continue
        run = next((j for j in range(i, len(kinds)) if kinds[j] != kind), len(kinds)) - i
        extra = f" (+{run - 1} linhas)" if run > 1 else ""
        spans.append(Span(kind, i + 1, clean(lines[i] + extra)))
    return spans


_OPENERS = {'"': '"', "“": "”", "«": "»", "`": "`"}
_SENTENCE_END = re.compile(r"[.!?…:;][\"')\]*_”’]*\s*$")


def _hold_lines(masked: list[str], lines: list[str], kinds: list[str | None]) -> None:
    """Protect what the per-line masks cannot see. After masking, a quote mark or backtick that is
    left over is an opener without its closer on that line: the span wraps onto the next lines, so
    those lines are held until the closer or the end of the paragraph. A line with a ``|`` outside
    code is a table row even without a leading pipe."""
    closer = ""
    for i, line in enumerate(masked):
        if kinds[i] is not None or not line.strip():
            closer = ""
            continue
        if "|" in line:
            kind, closer = "table row", ""
        elif closer:
            kind, closer = "open quote", "" if closer in line else closer
        else:
            closer = _OPENERS.get(next((c for c in line if c in _OPENERS), ""), "")
            kind = "open quote" if closer else ""
        if kind:
            kinds[i], masked[i] = kind, lines[i]


def _glued(masked: list[str], kinds: list[str | None]) -> set[int]:
    """Lines that continue a sentence the previous line left open (hard-wrapped prose), so a line
    start there is not a sentence start. A block start (title, list item) never continues one."""
    out = set()
    for i in range(1, len(masked)):
        prev, line = masked[i - 1], masked[i]
        if (
            kinds[i] is None
            and kinds[i - 1] is None
            and prev.strip()
            and line.strip()
            and not _HEAD.match(prev)
            and not _HEAD.match(line)
            and not _LIST.match(line)
            and not _SENTENCE_END.search(prev)
        ):
            out.add(i)
    return out


def _heading_ids(
    lines: list[str], kinds: list[str | None], anchors: frozenset[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """(titles the document links to, every heading's slug). GitHub numbers repeated titles
    ``slug``, ``slug-1``, ``slug-2``: a linked one must keep its title, and a new title must not
    take the slug of a heading that exists (it would push that heading's anchor to ``-1``)."""
    seen: Counter[str] = Counter()
    kept: set[str] = set()
    for line, kind in zip(lines, kinds, strict=True):
        if kind == "setext title":
            title = line.strip()
        elif kind is None and (head := _heading(line)):
            title = head[1]
        else:
            continue
        slug = _slug(title)
        if (f"{slug}-{seen[slug]}" if seen[slug] else slug) in anchors:
            kept.add(title)
        seen[slug] += 1
    return frozenset(kept), frozenset(seen)


# --- transformations ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ctx:
    restore: Callable[[str], str]
    kept: frozenset[str]  # titles whose anchor the document links to
    slugs: frozenset[str]  # the slug of every heading in the document


def _heading(line: str) -> tuple[str, str, str] | None:
    """(marker, title, trailing blanks) of an ATX heading line. The blanks are split off with
    ``rstrip``: a lazy ``.*?`` before ``[ \\t]*$`` is quadratic on a long run of spaces."""
    m = _HEAD.match(line)
    if not m:
        return None
    title = m[2].rstrip(" \t")
    return m[1], title, m[2][len(title) :]


def _slug(title: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation and emoji dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


# Names that are written in lower case on purpose: "pip installs wheels" stays "pip".
_LOWER_NAMES = frozenset(
    {"pip", "pipx", "npm", "pnpm", "yarn", "npx", "uv", "git", "gh", "curl", "wget", "brew", "apt"}
    | {
        "docker",
        "kubectl",
        "make",
        "cmake",
        "gcc",
        "clang",
        "node",
        "deno",
        "bun",
        "cargo",
        "rustc",
    }
    | {"pytest", "ruff", "mypy", "bandit", "tox", "nox", "poetry", "conda", "bash", "zsh", "sudo"}
    | {"ssh", "scp", "rsync", "grep", "sed", "awk", "ffmpeg", "jq", "vim", "nvim"}
)


def _upper_first(word: str | None) -> str:
    """Capitalise the first letter of ``word`` (the first word after a dropped lead-in), unless it
    is a placeholder, already capitalised, or a name written in lower case."""
    if not word or not word[0].islower() or word in _LOWER_NAMES:
        return word or ""
    return word[0].upper() + word[1:]


_LEAD_IN = re.compile(r"^(\s*(?:(?:[-*+]|\d+[.)])\s+)?)\*\*([^*\n]+?)\*\*(\s*[—–:-])?")


def _bold_lead_in(line: str, ctx: _Ctx) -> str:
    """``**Termo** — x``, ``**Termo**: x`` and ``**Termo:** x`` become ``Termo: x``."""
    m = _LEAD_IN.match(line)
    if not m:
        return line
    label, sep = m[2].strip(), m[3]
    rest = line[m.end() :]
    if not (label[:1].isupper() and (sep or label.endswith(":"))):
        return line  # not what the detector counts
    if rest[:1].strip():  # "**Termo**-x": no gap after the separator, not a lead-in
        return line
    head = label.rstrip(":")
    if head[-1:] in ".!?;":
        return line
    return f"{m[1]}{head}:{rest}"


_PUA = f"{chr(0xE000)}-{chr(0xF8FF)}"  # the placeholder characters, as a class range
_WORD_SIDE = r"\w)\]}*_'’”»%" + _PUA
_DASH = re.compile(rf"(?<=[{_WORD_SIDE}])[ \t]*—[ \t]*(?=[\w(\[*_'\"“‘«{_PUA}])")


_RANGE_FROM = re.compile(r"\d[A-Za-z%]{0,3}$")  # "10", "9h", "5%": the end of a range's first half
_RANGE_TO = frozenset("0123456789$€£")


def _em_dash(line: str, ctx: _Ctx) -> str:
    """A dash with text on both sides becomes a comma, unless it is a number range (``10—20``,
    ``9h — 17h``, ``5% — 10%``, spaced or not). ``Monday — Friday`` has no digit and becomes a list."""
    if _HEAD.match(line):
        return line  # rewriting a title would move its anchor

    def swap(m: re.Match[str]) -> str:
        if line[m.end()] in _RANGE_TO and _RANGE_FROM.search(
            line, max(0, m.start() - 6), m.start()
        ):
            return m[0]
        return ", "

    return _DASH.sub(swap, line)


_TEMPLATES = {
    "why this matters": "Relevance",
    "why it matters": "Relevance",
    "why that matters": "Relevance",
    "what this means": "Implications",
    "what it means": "Implications",
    "what that means": "Implications",
    "what's next": "Next steps",
    "what happens next": "Next steps",
    "what comes next": "Next steps",
    "the bottom line": "Summary",
    "bottom line": "Summary",
    "por que isso importa": "Relevância",
    "por que isto importa": "Relevância",
    "por que isso é importante": "Relevância",
    "por que importa": "Relevância",
    "o que isso significa": "Implicações",
    "o que isto significa": "Implicações",
    "o que vem a seguir": "Próximos passos",
    "o que vem depois": "Próximos passos",
    "a linha de fundo": "Conclusão",
    "a linha final": "Conclusão",
}
_SYMBOLS = re.compile(r"^[^\w\s]+\s*")


def _template_heading(line: str, ctx: _Ctx) -> str:
    """A known template title becomes a plain one in the same language. The title is left alone
    when the document links to its anchor, or when the new one would take an existing slug (either
    way an anchor would move and a link break)."""
    head = _heading(line)
    if not head or ctx.restore(head[1]) != head[1]:
        return line
    marker, title, tail = head
    lead = _SYMBOLS.match(title)
    cut = lead.end() if lead else 0
    key = " ".join(title[cut:].lower().replace("’", "'").split()).rstrip("?!.:; ")
    new = _TEMPLATES.get(key)
    if new is None or title in ctx.kept or _slug(new) in ctx.slugs:
        return line
    return f"{marker}{title[:cut]}{new}{tail}"


_JOINERS = re.compile(f"[{chr(0xFE0F)}{chr(0x200D)}]")  # variation selector, ZWJ


def _emoji_heading(line: str, ctx: _Ctx) -> str:
    """Drop the emoji from a title (and the joiners that belong to it), unless an anchor points
    at the title, the bare title is another heading's slug, or nothing would be left."""
    head = _heading(line)
    if not head or not _EMOJI.search(head[1]):
        return line
    marker, old, tail = head
    title = _JOINERS.sub("", _EMOJI.sub("", old))
    title = re.sub(r"[ \t]{2,}", " ", title).strip(" \t")
    if not title or ctx.restore(old) in ctx.kept or _slug(ctx.restore(title)) in ctx.slugs:
        return line
    return f"{marker}{title}{tail}"


_START = r"(?:^[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?|(?<=[.!?])[ \t]+)"  # sentence start
_FAST_LEAD = (
    r"in\s+today['’]s\s+(?:fast-paced|fast\s+paced|ever-changing|ever-evolving|digital|modern)"
    r"(?:\s+(?:world|landscape|age|era|environment|economy|society))?",
    r"no\s+mundo\s+(?:atual|de\s+hoje|moderno)",
    r"em\s+um\s+mundo\s+cada\s+vez\s+mais\s+(?:digital|conectado|competitivo|acelerado)",
    r"nos\s+dias\s+de\s+hoje",
    r"na\s+era\s+(?:digital|da\s+informa[cç][aã]o)",
)
_FAST = re.compile(
    rf"(?P<head>{_START})(?:(?:{'|'.join(_FAST_LEAD)})[ \t]*,[ \t]+)+(?P<nxt>[^\W\d_]+|.)?",
    re.IGNORECASE,
)


def _fast_paced(line: str, ctx: _Ctx) -> str:
    """Delete a stock opening ("In today's fast-paced world, ") and capitalise what follows."""
    return _FAST.sub(lambda m: m["head"] + _upper_first(m["nxt"]), line)


_WORTH_LEAD = (
    r"(?:é\s+)?importante\s+(?:ressaltar|destacar|notar|mencionar|lembrar)\s+que",
    r"vale\s+(?:a\s+pena\s+)?(?:notar|destacar|ressaltar|mencionar|lembrar)\s+que",
    r"cabe\s+(?:destacar|ressaltar|notar)\s+que",
    r"it(?:['’]s|\s+is)\s+(?:also\s+)?(?:worth\s+(?:noting|mentioning)"
    r"|important\s+to\s+(?:note|mention))\s+that",
    r"worth\s+noting\s+that",
)
_CONNECTOR = (
    r"(?P<conn>(?:além\s+disso|também|ainda|porém|mas|e|also|additionally|moreover|furthermore"
    r"|but|and|however)\b,?[ \t]+)?"
)
_WORTH = re.compile(
    rf"(?P<head>(?:^[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?|(?<=[.!?:;,])[ \t]+){_CONNECTOR})"
    rf"(?:(?:{'|'.join(_WORTH_LEAD)})[ \t]+)+(?P<nxt>[^\W\d_]+|.)?",
    re.IGNORECASE,
)


def _worth_noting(line: str, ctx: _Ctx) -> str:
    """Drop "vale notar que" and its kin, keeping the clause. The clause is capitalised only when
    the lead-in opened the sentence."""

    def swap(m: re.Match[str]) -> str:
        opens = m.start() == 0 or line[m.start() - 1] in ".!?"
        nxt = m["nxt"] or ""
        return m["head"] + (_upper_first(nxt) if opens and not m["conn"] else nxt)

    return _WORTH.sub(swap, line)


_DELVE_VERBS = {
    "delve": "look",
    "delves": "looks",
    "delved": "looked",
    "delving": "looking",
    "dive": "look",
    "dives": "looks",
    "dived": "looked",
    "dove": "looked",
    "diving": "looking",
}
# ASCII: under IGNORECASE alone "ı" (dotless i) and "ſ" match "i" and "s", and no verb has them.
_ASCII_I = re.ASCII | re.IGNORECASE
_DELVE = re.compile(r"\b(delv(?:e|es|ed|ing))([ \t]+deeper)?[ \t]+into\b", _ASCII_I)
_DIVE = re.compile(
    rf"\b({_VERB_LEAD}[ \t]+)(div(?:e|es|ed|ing)|dove)([ \t]+deeper)?[ \t]+into\b", _ASCII_I
)


def _look(verb: str, deeper: str | None) -> str:
    look = _DELVE_VERBS[verb.lower()]
    return (look.capitalize() if verb[0].isupper() else look) + (" closer at" if deeper else " at")


def _delve(line: str, ctx: _Ctx) -> str:
    """``delve into X`` / ``let's dive into X`` become ``look at X``, with the verb inflected."""
    line = _DELVE.sub(lambda m: _look(m[1], m[2]), line)
    return _DIVE.sub(lambda m: m[1] + _look(m[2], m[3]), line)


_HEDGES = re.compile(rf"\b(?:{_H}[ \t]+)+({_H})\b", re.IGNORECASE)


def _hedge(line: str, ctx: _Ctx) -> str:
    """Two hedges in a row keep the last one: ``pode ser que talvez X`` becomes ``talvez X``.
    Dropping both would turn a hedged claim into a flat one."""

    def swap(m: re.Match[str]) -> str:
        kept = m[1]
        return kept[0].upper() + kept[1:] if m[0][0].isupper() else kept

    return _HEDGES.sub(swap, line)


_STEPS: tuple[tuple[str, Callable[[str, _Ctx], str]], ...] = (
    ("bold_lead_in", _bold_lead_in),  # before the dash: it consumes "**Termo** — "
    ("em_dash_density", _em_dash),
    ("emoji_heading", _emoji_heading),  # before the template: "## 🚀 Why this matters"
    ("template_heading", _template_heading),
    ("fast_paced_world", _fast_paced),  # before worth_noting: it can expose a lead-in
    ("worth_noting", _worth_noting),
    ("delve_family", _delve),
    ("hedge_double", _hedge),
)
TRANSFORMS = tuple(name for name, _ in _STEPS)
# The dash rewrite answers to both dash signals: a long document can trip the ratio alone.
_GATES = {"em_dash_density": frozenset({"em_dash_density", "em_dash_to_comma_ratio"})}


def _one_pass(
    text: str, active: Collection[str], anchors: frozenset[str], preserve: Sequence[str]
) -> tuple[str, list[Transform], list[Span]]:
    parts = _EOL.split(text)
    lines, ends = parts[0::2], [*parts[1::2], ""]
    kinds = _line_kinds(lines, preserve)
    masker = _Masker(text)
    masked = [
        masker.mask(line, n) if kinds[n - 1] is None else line for n, line in enumerate(lines, 1)
    ]
    _hold_lines(masked, lines, kinds)
    ctx = _Ctx(masker.restore, *_heading_ids(lines, kinds, anchors))
    # Prefixed to a wrapped line, so that nothing anchored at the line start matches it. No step
    # can touch these two characters: one is a sentinel, the other a newline, which no pattern eats.
    glue = masker.open + "\n"
    glued = _glued(masked, kinds)
    edits: list[Transform] = []
    for name, step in _STEPS:
        if name not in active:
            continue
        for i, line in enumerate(masked):
            if kinds[i] is not None:
                continue
            new = step(glue + line if i in glued else line, ctx)
            new = new.removeprefix(glue) if i in glued else new
            if new != line:
                edits.append(Transform(name, i + 1, masker.restore(line), masker.restore(new)))
                masked[i] = new
    spans = [*_block_spans(kinds, lines), *masker.spans]
    rebuilt = "".join(masker.restore(m) + end for m, end in zip(masked, ends, strict=True))
    if masker.open in rebuilt or masker.close in rebuilt:  # sentinels are absent from the input
        raise RuntimeError("um marcador de máscara vazou para o texto")
    return rebuilt, edits, spans


def naturalize(
    text: str, signals: Collection[str] | None = None, preserve: Sequence[str] = ()
) -> Result:
    """Rewrite ``text`` until its detectable habits are gone or only protected spans carry them.

    ``signals`` limits the transformations (names from :data:`TRANSFORMS`); ``preserve`` is a list
    of globs: a line that matches one is never touched.
    """
    selected = [n for n in TRANSFORMS if signals is None or n in signals]
    anchors = frozenset(a.lower() for raw in _ANCHOR.findall(text) for a in (raw, unquote(raw)))
    before = current = text_signals.analyze(text)
    now = text
    edits: list[Transform] = []
    spans: list[Span] = []
    for _ in range(MAX_PASSES):
        fired = {s.name for s in current.signals}
        active = [n for n in selected if _GATES.get(n, frozenset({n})) & fired]
        if not active:
            break
        new, step, found = _one_pass(now, active, anchors, preserve)
        spans = spans or found
        if new == now:
            break
        now, current = new, text_signals.analyze(new)
        edits += step
    return Result(now, before, current, tuple(edits), tuple(spans))
