"""Source-code signals for Python (``ast`` + ``tokenize``) and TypeScript/JavaScript.

TS/JS use tree-sitter when ``tree-sitter`` and ``tree-sitter-typescript`` are installed (the
``formats`` dependency group) and fall back to regexes otherwise: less precise, so the result
carries a note and the confidence is capped at ``low``. Python needs only the standard library.
Every regex is anchored or possessive, so a hostile 1 MB file costs one scan, not a stall.
"""

from __future__ import annotations

import ast
import functools
import importlib
import io
import re
import tokenize
from dataclasses import dataclass
from re import Pattern
from typing import Any, NamedTuple

from . import (
    Analysis,
    Hit,
    Signal,
    by_count,
    cap_confidence,
    metric,
    occurrences,
    score_signals,
    split_lines,
)

PYTHON = "python"
TS_LANGUAGES = ("typescript", "tsx", "javascript", "jsx")
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Context:
    """Facts one file cannot tell. When a fact is absent, the signal that needs it stays quiet
    instead of guessing."""

    small_project: bool = True  # over_descriptive_name only makes sense in a small code base
    requires_python: tuple[int, int] | None = None  # floor from the nearest pyproject.toml


# --- comments (shared by every language) -------------------------------------------------------


class Comment(NamedTuple):
    line: int
    raw: str
    full_line: bool

    @property
    def body(self) -> str:
        return self.raw.lstrip("#/").strip()


_DIRECTIVE = re.compile(
    r"(?:!|noqa|type:|pragma|pylint|fmt:|ruff:|mypy:|pyright:|isort:|flake8|-\*-|(?:vim?|coding)[:=])",
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
_TODO_SHAPED = re.compile(r"\bTODO\([^)\s]+\)\s*:")
_OBVIOUS = re.compile(
    r"(?:initiali[sz]e|set|import|define|create|return|increment|call|get|add)\b", re.IGNORECASE
)


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
    found: list[Hit] = []
    for c in comments:
        if not (c.full_line and _OBVIOUS.match(c.body)):
            continue
        nxt = c.line + 1
        while nxt <= len(lines) and (
            not lines[nxt - 1].strip() or lines[nxt - 1].lstrip()[0] == "#"
        ):
            nxt += 1
        stmt = stmts.get(nxt)
        if isinstance(stmt, _SIMPLE) and stmt.end_lineno == stmt.lineno:
            found.append(Hit(c.line, c.raw[:100]))
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


def _is_literal(value: ast.expr) -> bool:
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Dict):
        return not value.keys
    return isinstance(value, ast.List | ast.Set | ast.Tuple) and not value.elts


def _trivial_locals(nodes: list[ast.AST]) -> list[Signal]:
    found: dict[tuple[int, int], Hit] = {}
    for fn in nodes:
        if not isinstance(fn, _FUNCS):
            continue
        for n in ast.walk(fn):
            if (
                isinstance(n, ast.AnnAssign)
                and isinstance(n.target, ast.Name)
                and n.value is not None
                and _is_literal(n.value)
            ):
                found[(n.lineno, n.col_offset)] = Hit(n.lineno, ast.unparse(n)[:100])
    hits = [found[k] for k in sorted(found)]
    return occurrences("type_hint_on_trivial_local", hits, by_count(len(hits), 1, 3, 6))


def _generic_except(nodes: list[ast.AST]) -> list[Signal]:
    found = [
        Hit(n.lineno, f"except {ast.unparse(n.type) if n.type else ''}: pass".replace(" :", ":"))
        for n in nodes
        if isinstance(n, ast.ExceptHandler)
        and (n.type is None or (isinstance(n.type, ast.Name) and n.type.id in _BROAD))
        and all(isinstance(s, ast.Pass) for s in n.body)
    ]
    return occurrences("generic_try_except", found, by_count(len(found), medium=1, high=3))


_BROAD = {"Exception", "BaseException"}


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


def _python(source: str, lines: list[str], ctx: Context) -> tuple[list[Signal], list[str]]:
    comments = _py_comments(source, lines)
    signals = [*_comment_signals(comments), *_density(lines, comments)]
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return signals, [f"parse_error: {type(exc).__name__}; sinais de AST ignorados"]
    nodes = list(ast.walk(tree))
    signals += [
        *_obvious(nodes, lines, comments),
        *_docstring_echo(nodes),
        *_trivial_locals(nodes),
        *_generic_except(nodes),
        *_params(nodes),
        *_names(nodes, ctx),
        *_main_boilerplate(tree, nodes),
        *_future(tree, ctx),
        *_match(nodes),
    ]
    return signals, []


# --- TypeScript / JavaScript -------------------------------------------------------------------

_LITERAL = (
    r"""(?:"[^"\\\n]{0,200}"|'[^'\\\n]{0,200}'|`[^`\\\n]{0,200}`|\b\d[\d_.]*+|\btrue\b|\bfalse\b)"""
)
_AS_CONST = re.compile(_LITERAL + r"\s+as\s+const\b")
_CHAIN = r"\b[\w$]++(?:\?\.[\w$]++(?:\([^()]*\))?){3,}"
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


@functools.cache
def _parser(language: str) -> Any | None:
    try:
        ts = importlib.import_module("tree_sitter")
        grammars = importlib.import_module("tree_sitter_typescript")
        grammar = (
            grammars.language_typescript() if language == "typescript" else grammars.language_tsx()
        )
        return ts.Parser(ts.Language(grammar))
    except (ImportError, AttributeError, TypeError, ValueError, OSError):
        return None


def tree_sitter_available() -> bool:
    return _parser("tsx") is not None


def _node_hit(node: Any) -> Hit:
    text = node.text.decode("utf-8", "replace")
    return Hit(node.start_point[0] + 1, " ".join(text.split())[:100])


def _const_literals(nodes: list[Any]) -> set[str]:
    """Names bound once to a literal: ``?.`` on them can never be nullish."""
    names: set[str] = set()
    for n in nodes:
        if n.type != "variable_declarator" or n.parent is None:
            continue
        name, value = n.child_by_field_name("name"), n.child_by_field_name("value")
        if (
            name is not None
            and value is not None
            and name.type == "identifier"
            and value.type in _LITERAL_BASES
            and n.parent.type == "lexical_declaration"
            and n.parent.children[0].type == "const"
        ):
            names.add(name.text.decode("utf-8", "replace"))
    return names


def _chain_base(node: Any) -> Any:
    return node.child_by_field_name("object") or node.child_by_field_name("function")


def _flagged_chains(nodes: list[Any]) -> list[Hit]:
    consts = _const_literals(nodes)
    chain_nodes = [n for n in nodes if n.type in _CHAIN_NODES]
    inner = {
        b.id for n in chain_nodes if (b := _chain_base(n)) is not None and b.type in _CHAIN_NODES
    }
    found: list[Hit] = []
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
            found.append(_node_hit(n))
    return found


def _ts_tree(parser: Any, source: str) -> list[Signal]:
    nodes: list[Any] = []
    stack = [parser.parse(source.encode("utf-8")).root_node]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(node.children)
    as_const = [
        _node_hit(n)
        for n in nodes
        if n.type == "as_expression"
        and len(n.children) >= 3
        and n.children[-1].type == "const"
        and n.children[0].type in _PRIMITIVE_LITERALS
    ]
    arrows = []
    for n in nodes:
        if n.type == "arrow_function" and n.parent is not None:
            if n.parent.type not in ("arguments", "jsx_expression"):
                continue
            ret = next((c for c in n.children if c.type == "type_annotation"), None)
            if (
                ret is not None
                and ret.text.decode("utf-8", "replace").lstrip(": ").strip() in _PRIMITIVE_TYPES
            ):
                arrows.append(_node_hit(n))
    return _ts_signals(as_const, _flagged_chains(nodes), arrows)


def _typescript(
    source: str, lines: list[str], language: str, use_tree_sitter: bool
) -> tuple[list[Signal], list[str]]:
    parser = _parser(language) if use_tree_sitter else None
    if parser is None:
        body, notes = (
            _ts_regex(source),
            ["tree-sitter indisponível; análise por regex (menos precisa)"],
        )
    else:
        body, notes = _ts_tree(parser, source), []
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
