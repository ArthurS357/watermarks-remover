"""Source-code signals for Python (``ast`` + ``tokenize``) and TypeScript/JavaScript.

TS/JS use tree-sitter when ``tree-sitter`` and ``tree-sitter-typescript`` are installed (the
``formats`` dependency group) and fall back to regexes otherwise: less precise, so the result
carries a note and the confidence is capped at ``low``. Python needs only the standard library.
Cost is linear in the file size: regexes are anchored (lookbehind) or bounded, and a few perf
tests run adversarial blobs against each of them. Files too big for ``ast`` skip the AST signals.
"""

from __future__ import annotations

import ast
import functools
import importlib
import importlib.util
import io
import re
import tokenize
import warnings
from dataclasses import dataclass
from re import Pattern
from typing import Any, NamedTuple

from . import (
    Analysis,
    Hit,
    Signal,
    by_count,
    cap_confidence,
    isolate,
    metric,
    occurrences,
    score_signals,
    split_lines,
)

PYTHON = "python"
TS_LANGUAGES = ("typescript", "tsx", "javascript", "jsx")
TS_TIMEOUT = 10.0  # seconds the tree-sitter worker gets for one file before it is killed
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Context:
    """Facts one file cannot tell. When a fact is absent, the signal that needs it stays quiet
    instead of guessing."""

    small_project: bool = False  # over_descriptive_name only makes sense in a small code base
    requires_python: tuple[int, int] | None = None  # floor from the nearest pyproject.toml


# --- comments (shared by every language) -------------------------------------------------------


class Comment(NamedTuple):
    line: int
    raw: str
    full_line: bool

    @property
    def body(self) -> str:
        return self.raw.lstrip("#/").strip()


# Tool directives (shebang, noqa, type: ignore, pragma, ...) are not prose: they do not count as
# comments in the density metric. Word boundaries keep "Pragmatic choice: ..." a real comment.
_DIRECTIVE = re.compile(
    r"(?:!|noqa\b|type:\s*ignore\b|pragma\b|pylint\b|fmt:|ruff:|mypy:|pyright:|isort:|flake8\b"
    r"|-\*-|(?:vim?|coding)[:=])",
    re.IGNORECASE,
)
_WARN = re.compile(r"(?:note|important|warning|caution|attention)\s*:\s*(.*)", re.IGNORECASE)
_CRITICAL = re.compile(
    r"\b(?:secur\w*|secret|password|token|unsafe|race|deadlock|thread\w*|lock\w*|leak\w*|never"
    r"|must\s+not|do\s+not|don['’]t|break\w*|inject\w*|overflow|crash\w*|corrupt\w*|data\s+loss"
    r"|irreversible|dangerous)\b",
    re.IGNORECASE,
)
_TODO = re.compile(r"\bTODO\b")
_TODO_SHAPED = re.compile(r"\bTODO\([^)\s]{1,80}\)\s*:")
_OBVIOUS = re.compile(
    r"(?:initiali[sz]e|set|import|define|create|return|increment|call|get|add)\b", re.IGNORECASE
)
# A comment that explains *why* ("because", "see #412", "Return early: ...") is not obvious.
_EXPLAINS = re.compile(r"[:(]|\b(?:because|since|see)\b", re.IGNORECASE)


def _py_comments(source: str, lines: list[str]) -> list[Comment]:
    found: list[Comment] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                found.append(
                    Comment(tok.start[0], tok.string, not tok.line[: tok.start[1]].strip())
                )
    except (tokenize.TokenError, SyntaxError, ValueError):
        # Broken file: whole-line comments only, so the lexical signals still work.
        return [
            Comment(n, line.strip(), True)
            for n, line in enumerate(lines, 1)
            if line.lstrip().startswith("#")
        ]
    return found


def _ts_comments(lines: list[str]) -> list[Comment]:
    return [
        Comment(n, line.strip(), True)
        for n, line in enumerate(lines, 1)
        if line.lstrip().startswith("//")
    ]


def _comment_signals(comments: list[Comment]) -> list[Signal]:
    warnings: list[Hit] = []
    todos: list[Comment] = []
    for c in comments:
        m = _WARN.match(c.body)
        if m and not _CRITICAL.search(m[1]):
            warnings.append(Hit(c.line, c.raw[:100]))
        if _TODO.search(c.body):
            todos.append(c)
    shaped = [Hit(c.line, c.raw[:100]) for c in todos if _TODO_SHAPED.search(c.body)]
    uniform = shaped if len(shaped) == len(todos) else []  # one odd TODO breaks the uniformity
    return occurrences("warning_comment", warnings, by_count(len(warnings), 1, 3, 6)) + occurrences(
        "todo_comment_style", uniform, by_count(len(uniform), 3, 6)
    )


# --- Python ------------------------------------------------------------------------------------

_NAME_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_DOC_WORDS = re.compile(r"[A-Za-z0-9]+")
_STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "and",
        "this",
        "that",
        "is",
        "are",
        "given",
        "specified",
        "current",
        "by",
        "in",
        "on",
        "with",
        "from",
    ]
)
_SIMPLE = (
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Import,
    ast.ImportFrom,
    ast.Return,
    ast.Expr,
)


def _stem(word: str) -> str:
    """Crude suffix strip, applied to both sides so "handle" and "handles" meet."""
    for suffix in ("ing", "ed", "es", "s", "e"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


_STOP_STEMS = {_stem(w) for w in _STOP}


def _is_echo(name: str, doc: str) -> bool:
    tokens = {_stem(t.lower()) for t in _NAME_WORDS.findall(name)}
    words = {_stem(w.lower()) for w in _DOC_WORDS.findall(doc)}
    return bool(tokens) and tokens <= words and not words - tokens - _STOP_STEMS


def _density(lines: list[str], comments: list[Comment]) -> list[Signal]:
    counted = [c for c in comments if not _DIRECTIVE.match(c.body)]
    code = sum(1 for line in lines if line.strip()) - sum(1 for c in comments if c.full_line)
    if code < 30:
        return []
    ratio = len(counted) / code
    return metric(
        "comment_density",
        ratio,
        by_count(ratio, 0.15, 0.20, 0.25),
        f"{len(counted)} comentários / {code} linhas de código",
    )


def _obvious(nodes: list[ast.AST], lines: list[str], comments: list[Comment]) -> list[Signal]:
    stmts: dict[int, ast.stmt] = {}
    for n in nodes:  # ast.walk is breadth-first: the outer statement wins a shared line
        if isinstance(n, ast.stmt):
            stmts.setdefault(n.lineno, n)
    # next_code[i]: first code line after line i (blank and comment-only lines are skipped),
    # built backwards in one pass. Scanning forward from every comment is quadratic on a wall
    # of consecutive comments.
    next_code = [0] * (len(lines) + 2)
    following = len(lines) + 1
    for i in range(len(lines), 0, -1):
        next_code[i] = following
        stripped = lines[i - 1].lstrip()
        if stripped and stripped[0] != "#":
            following = i
    found: list[Hit] = []
    for c in comments:
        body = c.body
        if not (c.full_line and _OBVIOUS.match(body)):
            continue
        if len(body.split()) > 6 or _EXPLAINS.search(body):
            continue  # a long comment, or one that says why, is not stating the obvious
        stmt = stmts.get(next_code[c.line])
        if isinstance(stmt, _SIMPLE) and stmt.end_lineno == stmt.lineno:
            found.append(Hit(c.line, c.raw))
    return occurrences("obvious_comment", found, by_count(len(found), 1, 3, 6))


def _docstring_echo(nodes: list[ast.AST]) -> list[Signal]:
    found: list[Hit] = []
    for fn in nodes:
        if not isinstance(fn, _FUNCS) or fn.name.startswith("__"):
            continue
        doc = ast.get_docstring(fn)
        if doc and "\n" not in doc.strip() and _is_echo(fn.name, doc):
            found.append(Hit(fn.lineno, f"{fn.name}: {doc}"[:100]))
    return occurrences("docstring_echoes_name", found, by_count(len(found), 1, 3, 6))


def _repeats_literal(annotation: ast.expr, value: ast.expr) -> bool:
    """``x: int = 0``: an annotation that only repeats the type of a scalar literal.

    ``x: list[str] = []``, ``x: str | None = None`` and ``x: float = 0`` are not trivial: the
    annotation says what the value cannot, and ``mypy --strict`` asks for it.
    """
    return (
        isinstance(value, ast.Constant)
        and isinstance(annotation, ast.Name)
        and annotation.id == type(value.value).__name__
    )


def _trivial_locals(nodes: list[ast.AST], lines: list[str]) -> list[Signal]:
    found: dict[tuple[int, int], Hit] = {}
    for fn in nodes:
        if not isinstance(fn, _FUNCS):
            continue
        for n in ast.walk(fn):
            if (
                isinstance(n, ast.AnnAssign)
                and isinstance(n.target, ast.Name)
                and n.value is not None
                and _repeats_literal(n.annotation, n.value)
            ):
                # The source line, not ast.unparse: unparse recurses and a deep annotation such
                # as ``x: a.a.a...`` raises RecursionError on a perfectly valid file.
                found[(n.lineno, n.col_offset)] = Hit(n.lineno, lines[n.lineno - 1])
    hits = [found[k] for k in sorted(found)]
    return occurrences("type_hint_on_trivial_local", hits, by_count(len(hits), 1, 3, 6))


_BROAD = {"Exception", "BaseException"}


def _generic_except(nodes: list[ast.AST]) -> list[Signal]:
    found = [
        Hit(n.lineno, f"except {n.type.id if n.type else ''}: pass".replace(" :", ":"))
        for n in nodes
        if isinstance(n, ast.ExceptHandler)
        and (n.type is None or (isinstance(n.type, ast.Name) and n.type.id in _BROAD))
        and all(isinstance(s, ast.Pass) for s in n.body)
    ]
    return occurrences("generic_try_except", found, by_count(len(found), medium=1, high=3))


def _params(nodes: list[ast.AST]) -> list[Signal]:
    out: list[Signal] = []
    for fn in nodes:
        if not isinstance(fn, _FUNCS):
            continue
        a = fn.args
        positional = [*a.posonlyargs, *a.args]
        count = len(positional) + len(a.kwonlyargs) + bool(a.vararg) + bool(a.kwarg)
        if positional and positional[0].arg in ("self", "cls"):
            count -= 1
        severity = by_count(count, medium=10, high=14)
        if severity:
            out.append(
                Signal(
                    "excessive_params", count, severity, fn.lineno, f"{fn.name}({count} parâmetros)"
                )
            )
    return out


def _over_descriptive(name: str) -> bool:
    words = [w for w in name.split("_") if w]
    return len(words) >= 4 and len(name) >= 30 and not name.startswith(("test_", "__"))


def _names(nodes: list[ast.AST], ctx: Context) -> list[Signal]:
    if not ctx.small_project:
        return []
    found = [
        Hit(fn.lineno, fn.name)
        for fn in nodes
        if isinstance(fn, _FUNCS) and _over_descriptive(fn.name)
    ]
    return occurrences("over_descriptive_name", found, by_count(len(found), 1, 3, 6))


def _is_main_guard(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _main_boilerplate(tree: ast.Module, nodes: list[ast.AST]) -> list[Signal]:
    guard = next((n for n in tree.body if isinstance(n, ast.If) and _is_main_guard(n.test)), None)
    if guard is None:
        return []
    imported: set[str] = set()
    for n in nodes:
        if isinstance(n, ast.Import):
            imported.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    scopes = [guard, *(f for f in tree.body if isinstance(f, _FUNCS) and f.name == "main")]
    has_try = any(isinstance(n, ast.Try) for scope in scopes for n in ast.walk(scope))
    if {"argparse", "logging"} <= imported and has_try:
        hit = Hit(guard.lineno, "__main__ guard with argparse, logging and try/except")
        return occurrences("complete_main_boilerplate", [hit], "medium")
    return []


def _future(tree: ast.Module, ctx: Context) -> list[Signal]:
    if ctx.requires_python is None or ctx.requires_python < (3, 14):
        return []
    found = [
        Hit(n.lineno, "from __future__ import annotations")
        for n in tree.body
        if isinstance(n, ast.ImportFrom)
        and n.module == "__future__"
        and any(a.name == "annotations" for a in n.names)
    ]
    return occurrences("future_annotations_on_314", found, "low")


def _simple_case(case: ast.match_case) -> bool:
    p = case.pattern
    plain = isinstance(p, ast.MatchValue | ast.MatchSingleton)
    return case.guard is None and (plain or (isinstance(p, ast.MatchAs) and p.pattern is None))


def _match(nodes: list[ast.AST]) -> list[Signal]:
    found = [
        Hit(n.lineno, "match with 2 simple cases")
        for n in nodes
        if isinstance(n, ast.Match) and len(n.cases) == 2 and all(_simple_case(c) for c in n.cases)
    ]
    return occurrences("match_where_if_fits", found, by_count(len(found), 1, 3))


MAX_AST_BYTES = 500_000  # the AST is ~500x the source in memory on dense literals


def _python(source: str, lines: list[str], ctx: Context) -> tuple[list[Signal], list[str]]:
    comments = _py_comments(source, lines)
    signals = [*_comment_signals(comments), *_density(lines, comments)]
    if len(source) > MAX_AST_BYTES:
        return signals, [f"arquivo grande ({len(source)} caracteres); sinais de AST ignorados"]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # valid code with "\d" escapes
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return signals, [f"parse_error: {type(exc).__name__}; sinais de AST ignorados"]
    try:
        nodes = list(ast.walk(tree))
        signals += [
            *_obvious(nodes, lines, comments),
            *_docstring_echo(nodes),
            *_trivial_locals(nodes, lines),
            *_generic_except(nodes),
            *_params(nodes),
            *_names(nodes, ctx),
            *_main_boilerplate(tree, nodes),
            *_future(tree, ctx),
            *_match(nodes),
        ]
    except RecursionError:  # a valid but absurdly deep tree: keep the comment signals
        return signals, ["análise da AST interrompida (RecursionError); sinais de AST ignorados"]
    return signals, []


# --- TypeScript / JavaScript -------------------------------------------------------------------

# The lookbehinds matter: ``\b`` restarts a scan at every word boundary, so ``a$a$a$...`` or
# ``1.1.1...`` made these quadratic. A lookbehind only lets a run start once.
_LITERAL = (
    r"""(?:"[^"\\\n]{0,200}"|'[^'\\\n]{0,200}'|`[^`\\\n]{0,200}`"""
    r"""|(?<![\w$.])\d[\d_.]*+|\btrue\b|\bfalse\b)"""
)
_AS_CONST = re.compile(_LITERAL + r"\s+as\s+const\b")
_CHAIN = r"(?<![\w$])[\w$]++(?:\?\.[\w$]++(?:\([^()]*\))?){3,}"
_OPTIONAL = re.compile(_CHAIN + r"|\bthis\?\.")
_ARROW = re.compile(
    r"(?:[(,]|=\{)\s*(?:async\s+)?\([^()]*\)\s*:\s*(?:void|string|number|boolean)\s*=>"
)
_JSDOC = re.compile(
    r"@param\s+\{\s*(?:string|number|boolean|any|object|bigint|Array<\w+>)\s*\}\s+\[?[\w$]+\]?([^\n]*)"
)
_PRIMITIVE_LITERALS = {"string", "number", "true", "false", "template_string"}
_PRIMITIVE_TYPES = {"void", "string", "number", "boolean"}
_LITERAL_BASES = {
    "this",
    "string",
    "number",
    "array",
    "object",
    "template_string",
    "new_expression",
    "true",
    "false",
}
_CHAIN_NODES = {"member_expression", "subscript_expression", "call_expression"}


def _regex_hits(source: str, rx: Pattern[str]) -> list[Hit]:
    found: list[Hit] = []
    line, seen = 1, 0
    for m in rx.finditer(source):
        line += source.count("\n", seen, m.start())
        seen = m.start()
        found.append(Hit(line, " ".join(m.group(0).split())[:100]))
    return found


def _ts_signals(as_const: list[Hit], chains: list[Hit], arrows: list[Hit]) -> list[Signal]:
    return (
        occurrences("as_const_everywhere", as_const, by_count(len(as_const), 3, 6, 10))
        + occurrences("optional_chaining_overuse", chains, by_count(len(chains), 3, 6, 12))
        + occurrences("explicit_return_types_on_arrow", arrows, by_count(len(arrows), 1, 3, 6))
    )


def _ts_regex(source: str) -> list[Signal]:
    return _ts_signals(
        _regex_hits(source, _AS_CONST),
        _regex_hits(source, _OPTIONAL),
        _regex_hits(source, _ARROW),
    )


def _jsdoc(source: str, typed: bool) -> list[Signal]:
    """In TypeScript the type in ``@param {string}`` repeats the annotation. In JavaScript it is
    the only type information, so only a bare tag with no description counts."""
    found: list[Hit] = []
    line, seen = 1, 0
    for m in _JSDOC.finditer(source):
        line += source.count("\n", seen, m.start())
        seen = m.start()
        if typed or not m[1].strip(" -\t"):
            found.append(Hit(line, " ".join(m.group(0).split())[:100]))
    return occurrences("jsdoc_on_trivial_type", found, by_count(len(found), 1, 3, 6))


def tree_sitter_available() -> bool:
    """Both packages importable. Checked without importing them: the worker does the real load."""
    return all(
        importlib.util.find_spec(m) is not None for m in ("tree_sitter", "tree_sitter_typescript")
    )


# Everything from here to ``_ts_extract`` runs in the worker process (see ``isolate``): parsing
# is the part that can hang or balloon on hostile input, so it never runs in the caller.


@functools.cache
def _parser(language: str) -> Any:
    ts = importlib.import_module("tree_sitter")
    grammars = importlib.import_module("tree_sitter_typescript")
    grammar = (
        grammars.language_typescript() if language == "typescript" else grammars.language_tsx()
    )
    return ts.Parser(ts.Language(grammar))


def _node_hit(node: Any, data: bytes) -> list[Any]:
    """``[line, snippet]``. Sliced from the bytes: ``node.text`` would copy a whole subtree."""
    text = data[node.start_byte : node.start_byte + 400].decode("utf-8", "replace")
    return [node.start_point[0] + 1, " ".join(text.split())[:100]]


def _const_literals(nodes: list[Any], parents: dict[int, Any]) -> set[str]:
    """Names bound once to a literal: ``?.`` on them can never be nullish."""
    names: set[str] = set()
    for n in nodes:
        parent = parents.get(n.id)
        if n.type != "variable_declarator" or parent is None:
            continue
        name, value = n.child_by_field_name("name"), n.child_by_field_name("value")
        if (
            name is not None
            and value is not None
            and name.type == "identifier"
            and value.type in _LITERAL_BASES
            and parent.type == "lexical_declaration"
            and parent.children[0].type == "const"
        ):
            names.add(name.text.decode("utf-8", "replace"))
    return names


def _chain_base(node: Any) -> Any:
    return node.child_by_field_name("object") or node.child_by_field_name("function")


def _flagged_chains(nodes: list[Any], parents: dict[int, Any], data: bytes) -> list[list[Any]]:
    consts = _const_literals(nodes, parents)
    chain_nodes = [n for n in nodes if n.type in _CHAIN_NODES]
    inner = {
        b.id for n in chain_nodes if (b := _chain_base(n)) is not None and b.type in _CHAIN_NODES
    }
    found: list[list[Any]] = []
    for n in chain_nodes:
        if n.id in inner:  # only the outermost node of a chain speaks for it
            continue
        links, base = 0, n
        while base is not None and base.type in _CHAIN_NODES:
            links += any(c.type == "optional_chain" for c in base.children)
            base = _chain_base(base)
        trivial = base is not None and (
            base.type in _LITERAL_BASES
            or (base.type == "identifier" and base.text.decode("utf-8", "replace") in consts)
        )
        if links >= 3 or (links >= 1 and trivial):
            found.append(_node_hit(n, data))
    return found


def _is_inline_arrow_with_primitive_return(n: Any, parent: Any | None) -> bool:
    if n.type != "arrow_function" or parent is None:
        return False
    if parent.type not in ("arguments", "jsx_expression"):
        return False
    ret = next((c for c in n.children if c.type == "type_annotation"), None)
    return (
        ret is not None
        and ret.text.decode("utf-8", "replace").lstrip(": ").strip() in _PRIMITIVE_TYPES
    )


def _ts_extract(language: str, source: str) -> dict[str, list[list[Any]]]:
    """Worker entry point: parse and report ``[line, snippet]`` hits per signal (JSON-safe)."""
    data = source.encode("utf-8")
    nodes: list[Any] = []
    parents: dict[int, Any] = {}  # Node.parent is O(depth): quadratic on deeply nested code
    stack = [_parser(language).parse(data).root_node]
    while stack:
        node = stack.pop()
        nodes.append(node)
        for child in node.children:
            parents[child.id] = node
            stack.append(child)
    return {
        "as_const": [
            _node_hit(n, data)
            for n in nodes
            if n.type == "as_expression"
            and len(n.children) >= 3
            and n.children[-1].type == "const"
            and n.children[0].type in _PRIMITIVE_LITERALS
        ],
        "chains": _flagged_chains(nodes, parents, data),
        "arrows": [
            _node_hit(n, data)
            for n in nodes
            if _is_inline_arrow_with_primitive_return(n, parents.get(n.id))
        ],
    }


def _as_hits(pairs: list[list[Any]]) -> list[Hit]:
    return [Hit(line, snippet) for line, snippet in pairs]


def _typescript(
    source: str, lines: list[str], language: str, use_tree_sitter: bool
) -> tuple[list[Signal], list[str]]:
    body: list[Signal] | None = None
    notes: list[str] = []
    if not use_tree_sitter or not tree_sitter_available():
        notes = ["tree-sitter indisponível; análise por regex (menos precisa)"]
    else:
        try:
            found = isolate.call("stylometry.code:_ts_extract", [language, source], TS_TIMEOUT)
        except TimeoutError:
            notes = [
                f"tree-sitter excedeu {TS_TIMEOUT:g} s neste arquivo; análise por regex (menos precisa)"
            ]
        except (RuntimeError, OSError) as exc:  # IsolatedError is a RuntimeError
            notes = [f"tree-sitter falhou ({exc}); análise por regex (menos precisa)"]
        else:
            body = _ts_signals(
                _as_hits(found["as_const"]), _as_hits(found["chains"]), _as_hits(found["arrows"])
            )
    if body is None:
        body = _ts_regex(source)
    typed = language in ("typescript", "tsx")
    return [*body, *_jsdoc(source, typed), *_comment_signals(_ts_comments(lines))], notes


def analyze(
    source: str, language: str, ctx: Context | None = None, *, use_tree_sitter: bool = True
) -> Analysis:
    """Analyse one source file. ``language`` is ``python`` or one of ``TS_LANGUAGES``."""
    if language != PYTHON and language not in TS_LANGUAGES:
        raise ValueError(f"unsupported language: {language!r}")
    lines = split_lines(source)
    source = "\n".join(lines)  # one newline convention for ast, tokenize and the regexes
    if language == PYTHON:
        signals, notes = _python(source, lines, ctx or Context())
        comment_marks: tuple[str, ...] = ("#",)
    else:
        signals, notes = _typescript(source, lines, language, use_tree_sitter)
        comment_marks = ("//", "/*", "*")
    code = sum(1 for line in lines if line.strip() and not line.lstrip().startswith(comment_marks))
    confidence = "low" if code < 40 else "medium" if code < 200 else "high"
    if notes:  # a degraded analysis (parse error, regex fallback) never claims more than "low"
        confidence = cap_confidence(confidence, "low")
    signals.sort(key=lambda s: (s.line is None, s.line or 0, s.name))
    return Analysis(signals, score_signals(signals), confidence, tuple(notes))
