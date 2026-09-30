"""Tests for tools/stylometry/code.py (Python via ast, TS/JS via tree-sitter or regex)."""

from __future__ import annotations

import importlib
import json
import sys
import textwrap
import time
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stylometry import CATEGORY, SEVERITIES
from stylometry import code as sc

FIXTURES = ROOT / "tests" / "fixtures" / "stylometry"

PYTHON_SIGNALS = {
    "docstring_echoes_name",
    "obvious_comment",
    "comment_density",
    "type_hint_on_trivial_local",
    "generic_try_except",
    "excessive_params",
    "over_descriptive_name",
    "complete_main_boilerplate",
    "future_annotations_on_314",
    "match_where_if_fits",
    "warning_comment",
    "todo_comment_style",
}
TS_SIGNALS = {
    "as_const_everywhere",
    "optional_chaining_overuse",
    "jsdoc_on_trivial_type",
    "explicit_return_types_on_arrow",
    "warning_comment",
    "todo_comment_style",
}


def _in_process(target, args, timeout):
    """Stand-in for ``isolate.call``: same JSON round trip, same target, no child process.

    The real worker is exercised by the tests that ask for the ``real_worker`` fixture (and by
    test_stylometry_isolate.py); everything else runs the worker's code here so that it is fast
    and visible to coverage, which does not follow into a spawned process.
    """
    module, _, name = target.partition(":")
    function = getattr(importlib.import_module(module), name)
    return json.loads(json.dumps(function(*json.loads(json.dumps(args)))))


@pytest.fixture
def real_worker():
    return None


@pytest.fixture(autouse=True)
def _worker_code_in_process(request, monkeypatch):
    if "real_worker" not in request.fixturenames:
        monkeypatch.setattr(sc.isolate, "call", _in_process)


needs_tree_sitter = pytest.mark.skipif(
    not sc.tree_sitter_available(), reason="tree-sitter not installed (pip install --group formats)"
)
ENGINES = [
    pytest.param(False, id="regex"),
    pytest.param(True, id="tree-sitter", marks=needs_tree_sitter),
]


def src(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def analyze(source, language="python", ctx=None, engine=False):
    # The library default is quiet for context-dependent signals; most cases here want them on.
    ctx = ctx or sc.Context(small_project=True)
    return sc.analyze(source, language, ctx, use_tree_sitter=engine)


def names(source, language="python", ctx=None, engine=False):
    return {s.name for s in analyze(source, language, ctx, engine).signals}


def worst(source, name, language="python", ctx=None, engine=False):
    found = [s for s in analyze(source, language, ctx, engine).signals if s.name == name]
    return max((s.severity for s in found), key=SEVERITIES.index) if found else None


def params(n: int) -> str:
    return ", ".join(f"p{i}" for i in range(n))


# --- Python: (signal, must fire, near-miss that must stay quiet) ---------------------------------

PY_CASES = [
    (
        "docstring_echoes_name",
        'def get_user():\n    """Gets the user."""\n    return 1\n',
        'def get_user():\n    """Return the user, raising KeyError when the id is unknown."""\n    return 1\n',
    ),
    (
        "obvious_comment",
        "# Initialize the counter\ncounter = 0\n",
        "# Retry because the API is flaky\ncounter = 0\n",
    ),
    (
        "obvious_comment",
        "# Import the parser\nimport argparse\n",
        '# Initialize the table\ntable = {\n    "a": 1,\n}\n',
    ),
    (
        "comment_density",
        "".join(f"x{i} = {i}\n" for i in range(40)) + "".join(f"# keep {i}\n" for i in range(10)),
        "".join(f"x{i} = {i}\n" for i in range(40)) + "# keep\n# keep\n",
    ),
    (
        "type_hint_on_trivial_local",
        "def f():\n    x: int = 0\n    return x\n",
        "x: int = 0\n\n\nclass A:\n    y: int = 0\n\n\ndef g():\n    z: int = compute()\n    return z\n",
    ),
    (
        "generic_try_except",
        "try:\n    risky()\nexcept Exception:\n    pass\n",
        "try:\n    risky()\nexcept ValueError:\n    pass\n\ntry:\n    risky()\nexcept Exception as exc:\n    log(exc)\n",
    ),
    (
        "excessive_params",
        f"def f({params(10)}):\n    pass\n",
        f"def f({params(9)}):\n    pass\n",
    ),
    (
        "excessive_params",
        f"class A:\n    def m(self, {params(10)}):\n        pass\n",
        f"class A:\n    def m(self, {params(9)}):\n        pass\n",
    ),
    (
        "over_descriptive_name",
        "def handle_user_authentication_request():\n    pass\n",
        "def handle_login():\n    pass\n\n\ndef test_handle_user_authentication_request_when_expired():\n    pass\n",
    ),
    (
        "complete_main_boilerplate",
        src(
            """
            import argparse
            import logging

            def main():
                pass

            if __name__ == "__main__":
                logging.basicConfig(level=logging.INFO)
                argparse.ArgumentParser()
                try:
                    main()
                except Exception:
                    logging.exception("failed")
            """
        ),
        src(
            """
            import argparse

            def main():
                pass

            if __name__ == "__main__":
                argparse.ArgumentParser()
                try:
                    main()
                except Exception:
                    raise
            """
        ),
    ),
    (
        "match_where_if_fits",
        'match cmd:\n    case "go":\n        run()\n    case _:\n        stop()\n',
        'match cmd:\n    case "go":\n        run()\n    case "stop":\n        stop()\n    case _:\n        pass\n\n'
        "match point:\n    case [x, y]:\n        run()\n    case _:\n        stop()\n",
    ),
    (
        "warning_comment",
        "# Note: the list is sorted\nitems = []\n",
        "# Note: never call this without the lock\nitems = []\n\n# Notes live in the docs\n",
    ),
    (
        "todo_comment_style",
        "# TODO(ana): a\n# TODO(ana): b\n# TODO(ana): c\n",
        "# TODO(ana): a\n# TODO(ana): b\n",
    ),
    (
        "todo_comment_style",
        "# TODO(ana): a\n# TODO(ana): b\n# TODO(ana): c\n",
        "# TODO(ana): a\n# TODO(ana): b\n# TODO(ana): c\n# TODO fix this\n",
    ),
]

# future_annotations_on_314 needs the project's requires-python, so it has its own test below.


def test_python_catalogue_is_complete_and_categorised():
    covered = {c[0] for c in PY_CASES} | {"future_annotations_on_314"}
    assert covered == PYTHON_SIGNALS
    assert set(CATEGORY) >= PYTHON_SIGNALS | TS_SIGNALS


@pytest.mark.parametrize(
    ("name", "positive"), [c[:2] for c in PY_CASES], ids=[c[0] for c in PY_CASES]
)
def test_python_fires_on_positive(name, positive):
    assert name in names(positive)


@pytest.mark.parametrize(
    ("name", "negative"), [(c[0], c[2]) for c in PY_CASES], ids=[c[0] for c in PY_CASES]
)
def test_python_quiet_on_near_miss(name, negative):
    assert name not in names(negative)


def test_future_annotations_only_fires_with_a_314_floor():
    source = "from __future__ import annotations\n\nx = 1\n"
    assert "future_annotations_on_314" in names(source, ctx=sc.Context(requires_python=(3, 14)))
    assert "future_annotations_on_314" in names(source, ctx=sc.Context(requires_python=(3, 15)))
    assert "future_annotations_on_314" not in names(source, ctx=sc.Context(requires_python=(3, 12)))
    assert "future_annotations_on_314" not in names(source)
    assert "future_annotations_on_314" not in names(
        "x = 1\n", ctx=sc.Context(requires_python=(3, 14))
    )


def test_over_descriptive_name_needs_a_small_project():
    source = "def handle_user_authentication_request():\n    pass\n"
    assert "over_descriptive_name" in names(source, ctx=sc.Context(small_project=True))
    assert "over_descriptive_name" not in names(source, ctx=sc.Context(small_project=False))


# name -> (builder(k) -> source, [(k, expected worst severity)])
PY_TIERS = {
    "obvious_comment": (
        lambda k: "# Initialize x\nx = 0\n" * k,
        [(1, "low"), (3, "medium"), (6, "high")],
    ),
    "type_hint_on_trivial_local": (
        lambda k: "def f():\n" + "".join(f"    v{i}: int = {i}\n" for i in range(k)),
        [(1, "low"), (3, "medium"), (6, "high")],
    ),
    "generic_try_except": (
        lambda k: "try:\n    f()\nexcept Exception:\n    pass\n" * k,
        [(1, "medium"), (3, "high")],
    ),
    "excessive_params": (
        lambda k: f"def f({params(k)}):\n    pass\n",
        [(9, None), (10, "medium"), (13, "medium"), (14, "high")],
    ),
    "over_descriptive_name": (
        lambda k: "".join(
            f"def handle_user_authentication_request_{i}():\n    pass\n" for i in range(k)
        ),
        [(1, "low"), (3, "medium"), (6, "high")],
    ),
    "warning_comment": (
        lambda k: "# Note: the list is sorted\n" * k,
        [(1, "low"), (3, "medium"), (6, "high")],
    ),
    "todo_comment_style": (
        lambda k: "# TODO(ana): x\n" * k,
        [(2, None), (3, "low"), (6, "medium")],
    ),
    "match_where_if_fits": (
        lambda k: 'match c:\n    case "a":\n        f()\n    case _:\n        g()\n' * k,
        [(1, "low"), (3, "medium")],
    ),
    "comment_density": (
        lambda k: "".join(f"x{i} = {i}\n" for i in range(40)) + "# keep\n" * k,
        [(5, None), (6, "low"), (8, "medium"), (10, "high")],
    ),
}


@pytest.mark.parametrize(
    ("name", "k", "expected"),
    [(n, k, sev) for n, (_, tiers) in PY_TIERS.items() for k, sev in tiers],
)
def test_python_severity_follows_the_count(name, k, expected):
    build = PY_TIERS[name][0]
    assert worst(build(k), name) == expected


def test_docstring_echo_tiers():
    names_ = ["get_user", "set_value", "load_config", "save_file", "read_data", "make_item"]
    doc = {
        "get_user": "Gets the user.",
        "set_value": "Sets the value.",
        "load_config": "Loads the config.",
        "save_file": "Saves the file.",
        "read_data": "Reads the data.",
        "make_item": "Makes the item.",
    }

    def build(k):
        return "".join(f'def {n}():\n    """{doc[n]}"""\n' for n in names_[:k])

    assert [worst(build(k), "docstring_echoes_name") for k in (1, 3, 6)] == [
        "low",
        "medium",
        "high",
    ]


def test_docstring_echo_ignores_multiline_docstrings_and_dunders():
    multi = 'def get_user():\n    """Gets the user.\n\n    More detail follows here.\n    """\n'
    assert "docstring_echoes_name" not in names(multi)
    assert "docstring_echoes_name" not in names('def __init__():\n    """Init."""\n')


def test_excessive_params_counts_varargs_and_keyword_only():
    source = "def f(a, b, c, d, e, *args, f1, g, h, **kwargs):\n    pass\n"
    [signal] = [s for s in analyze(source).signals if s.name == "excessive_params"]
    assert signal.value == 10
    assert signal.line == 1


def test_comment_density_ignores_directives_and_short_files():
    code = "".join(f"x{i} = {i}\n" for i in range(40))
    directives = "#!/usr/bin/env python\n# noqa: E501\n# type: ignore\n# pragma: no cover\n" * 3
    assert "comment_density" not in names(directives + code)
    short = "".join(f"x{i} = {i}\n# keep\n" for i in range(10))
    assert "comment_density" not in names(short)


def test_comment_markers_inside_strings_are_not_comments():
    source = 'text = """\n# Note: the list is sorted\n# TODO(ana): a\n"""\n' * 4
    assert not names(source) & {"warning_comment", "todo_comment_style"}


def test_syntax_error_keeps_comment_signals_and_reports_a_note():
    analysis = analyze("# Note: the list is sorted\ndef (:\n")
    assert {s.name for s in analysis.signals} == {"warning_comment"}
    assert any("parse_error" in n for n in analysis.notes)
    assert analysis.confidence == "low"


def test_unparseable_inputs_do_not_raise():
    for source in ("(" * 100_000, "x = 1\x00\n", "def f(:\n" * 50, '"""unterminated'):
        assert isinstance(analyze(source).score, float)


def test_empty_source_is_silent():
    analysis = analyze("")
    assert analysis.signals == []
    assert analysis.score == 0.0
    assert analysis.confidence == "low"


@pytest.mark.parametrize(("lines", "expected"), [(10, "low"), (80, "medium"), (300, "high")])
def test_python_confidence_follows_code_size(lines, expected):
    assert analyze("x = 1\n" * lines).confidence == expected


def test_obvious_comment_looks_past_blank_and_comment_lines():
    source = "# Initialize x\n\n# and then some\nx = 0\n"
    assert "obvious_comment" in names(source)


def test_trivial_local_covers_empty_containers_but_not_calls():
    empty = "def f():\n    a: dict = {}\n    b: list = []\n    c: tuple = ()\n    return a, b, c\n"
    assert worst(empty, "type_hint_on_trivial_local") == "medium"
    filled = "def f():\n    a: dict = {'k': 1}\n    b: list = [1]\n    return a, b\n"
    assert "type_hint_on_trivial_local" not in names(filled)


def test_unsupported_language_is_rejected():
    with pytest.raises(ValueError, match="unsupported language"):
        analyze("fn main() {}", "rust")


def test_missing_tree_sitter_degrades_to_regex(monkeypatch):
    monkeypatch.setattr(sc.importlib.util, "find_spec", lambda name: None)
    assert sc.tree_sitter_available() is False
    analysis = sc.analyze("const a = 1;\n", "typescript")
    assert any("indisponível" in n and "regex" in n for n in analysis.notes)
    assert analysis.confidence == "low"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (TimeoutError("excedeu 10 s"), "excedeu"),
        (sc.isolate.IsolatedError("ImportError: No module named 'tree_sitter'"), "falhou"),
        (OSError("pipe broke"), "falhou"),
    ],
    ids=["timeout", "worker-error", "os-error"],
)
def test_a_failing_worker_degrades_to_regex_with_the_reason(monkeypatch, failure, expected):
    def boom(*args):
        raise failure

    monkeypatch.setattr(sc, "tree_sitter_available", lambda: True)
    monkeypatch.setattr(sc.isolate, "call", boom)
    source = 'const a = "x" as const;\nconst b = 1 as const;\nconst c = true as const;\n'
    analysis = sc.analyze(source, "typescript")
    assert any(expected in n and "regex" in n for n in analysis.notes)
    assert "as_const_everywhere" in {s.name for s in analysis.signals}  # the regex path still ran
    assert analysis.confidence == "low"


# --- regressions from the hostile-input review (each one was reproduced before the fix) ----------


def timed(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, time.perf_counter() - start


def test_library_default_context_is_quiet():
    source = "def handle_user_authentication_request():\n    pass\n"
    assert "over_descriptive_name" not in {s.name for s in sc.analyze(source, "python").signals}


def test_wall_of_comments_is_linear():
    # 8000 consecutive "obvious" comments took 12 s when every one rescanned the ones after it.
    _, seconds = timed(analyze, "#get\n" * 8000)
    assert seconds < 3


@pytest.mark.parametrize(
    ("language", "blob", "engine"),
    [
        ("typescript", "a$" * 10_000, False),  # _CHAIN: 5.7 s at this size before the fix
        ("typescript", "1." * 25_000, False),  # _LITERAL digits: 7 s
        ("python", "# " + "TODO(" * 10_000 + "\n", False),  # _TODO_SHAPED: 4 s
    ],
    ids=["chain", "literal", "todo"],
)
def test_quadratic_regexes_stay_linear(language, blob, engine):
    _, seconds = timed(analyze, blob, language, engine=engine)
    assert seconds < 3


def test_deep_annotation_on_a_valid_file_does_not_raise():
    source = "def f():\n    x: a" + ".a" * 600 + " = 1\n"  # ast.unparse recursed on this
    analysis = analyze(source)
    assert "type_hint_on_trivial_local" in {s.name for s in analysis.signals}
    assert len(next(s for s in analysis.signals if s.snippet).snippet) <= 100


def test_recursion_error_after_a_good_parse_keeps_the_comment_signals(monkeypatch):
    def too_deep(*args):
        raise RecursionError

    monkeypatch.setattr(sc, "_obvious", too_deep)
    analysis = analyze("# Note: the list is sorted\nx = 1\n")
    assert {s.name for s in analysis.signals} == {"warning_comment"}
    assert any("RecursionError" in n for n in analysis.notes)


def test_huge_python_skips_the_ast_but_keeps_comment_signals():
    source = "x = [" + "1," * 300_000 + "]\n# Note: the list is sorted\n"
    analysis, seconds = timed(analyze, source)
    assert {s.name for s in analysis.signals} == {"warning_comment"}
    assert any("AST" in n for n in analysis.notes)
    assert analysis.confidence == "low"
    assert seconds < 5


def test_valid_code_with_invalid_escapes_does_not_warn():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        analyze("pattern = '\\d+'\n")
    assert not [w for w in caught if issubclass(w.category, SyntaxWarning)]


def test_directive_prefixes_do_not_swallow_real_comments():
    code = "".join(f"x{i} = {i}\n" for i in range(40))
    assert "comment_density" in names(code + "# Pragmatic choice: keep it\n" * 10)
    assert "comment_density" in names(code + "# type: the kind of thing we store\n" * 10)
    assert "comment_density" not in names(code + "# pragma: no cover\n" * 10)
    assert "comment_density" not in names(code + "# type: ignore\n" * 10)


def test_obvious_comment_ignores_long_and_explanatory_comments():
    for comment in (
        "# Set to 0 because the vendor API rejects None since v2.3",
        "# Return early: nothing to do here",
        "# Import inside the function (see #412)",
        "# Initialize the counter before the long loop starts running",
    ):
        assert "obvious_comment" not in names(f"{comment}\nx = 0\n"), comment


def test_snippets_never_carry_control_characters():
    analysis = analyze("# Note: \x1b]0;pwned\x07\x1b[2J clear the screen\nx = 1\n")
    assert analysis.signals
    assert all(
        not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in s.snippet) for s in analysis.signals
    )


def test_python_fixtures_score_apart():
    ai = analyze((FIXTURES / "code_ai_like.py").read_text(encoding="utf-8"))
    human = analyze((FIXTURES / "code_human_like.py").read_text(encoding="utf-8"))
    assert ai.score >= 0.6
    assert human.score <= 0.1
    found = {s.name for s in ai.signals}
    assert found >= PYTHON_SIGNALS - {"future_annotations_on_314", "comment_density"}
    assert not {s.name for s in human.signals}


def test_python_line_numbers_and_shape():
    source = "x = 1\n\n# Initialize y\ny = 2\n"
    [signal] = [s for s in analyze(source).signals if s.name == "obvious_comment"]
    assert (signal.line, signal.snippet) == (3, "# Initialize y")


@pytest.mark.parametrize(
    "blob",
    ["x = 1\n" * 200_000, "# Note: a\n" * 100_000, "[" * 50_000, "a = (" * 20_000],
    ids=["many-lines", "many-comments", "open-brackets", "open-parens"],
)
def test_python_pathological_input_stays_fast(blob):
    start = time.perf_counter()
    analyze(blob)
    assert time.perf_counter() - start < 20


# --- TypeScript / JavaScript: same expectations on both engines -----------------------------------

TS_CASES = [
    (
        "as_const_everywhere",
        'const a = "x" as const;\nconst b = 1 as const;\nconst c = true as const;\n',
        'const a = ["a", "b"] as const;\nconst b = { k: 1 } as const;\nconst c = ["c"] as const;\n'
        'const d = "x" as const;\nconst e = 1 as const;\n',
    ),
    (
        "optional_chaining_overuse",
        "const a = x?.y?.z?.w;\nconst b = p?.q?.r?.s;\nconst c = m?.n?.o?.p;\n",
        "const a = x?.y;\nconst b = p?.q;\nconst c = m?.n;\nconst d = x?.y?.z?.w;\n",
    ),
    (
        "optional_chaining_overuse",
        "this?.a;\nthis?.b;\nthis?.c;\n",
        "this.a;\nthis.b;\nthis.c;\n",
    ),
    (
        "jsdoc_on_trivial_type",
        "/**\n * @param {string} name\n */\nfunction greet(name: string) {}\n",
        "/**\n * @param name the user name\n */\nfunction greet(name: string) {}\n",
    ),
    (
        "explicit_return_types_on_arrow",
        "arr.map((x): string => x);\n",
        "arr.map((x) => x);\nconst cb = (): void => {};\nconst f = async (): Promise<void> => {};\n",
    ),
    (
        "warning_comment",
        "// Important: check this\nconst a = 1;\n",
        "// Important: never reuse this token\nconst a = 1;\nconst url = 'http://x.test/Note: a';\n",
    ),
    (
        "todo_comment_style",
        "// TODO(ana): a\n// TODO(ana): b\n// TODO(ana): c\n",
        "// TODO(ana): a\n// TODO(ana): b\n// TODO fix\n// TODO(ana): c\n",
    ),
]


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(
    ("name", "positive"), [c[:2] for c in TS_CASES], ids=[c[0] for c in TS_CASES]
)
def test_ts_fires_on_positive(name, positive, engine):
    assert name in names(positive, "typescript", engine=engine)


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(
    ("name", "negative"), [(c[0], c[2]) for c in TS_CASES], ids=[c[0] for c in TS_CASES]
)
def test_ts_quiet_on_near_miss(name, negative, engine):
    assert name not in names(negative, "typescript", engine=engine)


def test_ts_catalogue_is_complete():
    assert {c[0] for c in TS_CASES} == TS_SIGNALS


def test_jsdoc_types_are_redundant_in_ts_but_normal_in_js():
    documented = "/**\n * @param {string} name - the user name\n */\nfunction greet(name) {}\n"
    bare = "/**\n * @param {string} name\n */\nfunction greet(name) {}\n"
    assert "jsdoc_on_trivial_type" in names(documented, "typescript")
    assert "jsdoc_on_trivial_type" not in names(documented, "javascript")
    assert "jsdoc_on_trivial_type" in names(bare, "javascript")


TS_TIERS = {
    "as_const_everywhere": (
        lambda k: "".join(f'const a{i} = "x" as const;\n' for i in range(k)),
        [(2, None), (3, "low"), (6, "medium"), (10, "high")],
    ),
    "optional_chaining_overuse": (
        lambda k: "".join(f"const a{i} = x?.y?.z?.w;\n" for i in range(k)),
        [(2, None), (3, "low"), (6, "medium"), (12, "high")],
    ),
    "jsdoc_on_trivial_type": (
        lambda k: "".join(
            f"/**\n * @param {{string}} name\n */\nfunction f{i}(name: string) {{}}\n"
            for i in range(k)
        ),
        [(1, "low"), (3, "medium"), (6, "high")],
    ),
    "explicit_return_types_on_arrow": (
        lambda k: "".join(f"arr.map((x): string => x + {i});\n" for i in range(k)),
        [(1, "low"), (3, "medium"), (6, "high")],
    ),
}


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(
    ("name", "k", "expected"),
    [(n, k, sev) for n, (_, tiers) in TS_TIERS.items() for k, sev in tiers],
)
def test_ts_severity_follows_the_count(name, k, expected, engine):
    build = TS_TIERS[name][0]
    assert worst(build(k), name, "typescript", engine=engine) == expected


@needs_tree_sitter
def test_tree_sitter_path_is_actually_used_and_reports_no_fallback_note():
    analysis = analyze("const a = 1;\n" * 300, "tsx", engine=True)
    assert analysis.notes == ()
    assert analysis.confidence == "high"


def test_regex_fallback_caps_confidence_and_says_so():
    analysis = analyze("const a = 1;\n" * 300, "tsx", engine=False)
    assert analysis.confidence == "low"
    assert any("regex" in n for n in analysis.notes)


@needs_tree_sitter
def test_tree_sitter_ignores_as_const_in_strings_and_comments():
    source = (
        'const s = "1 as const 2 as const 3 as const";\n// 1 as const, 2 as const, 3 as const\n'
    )
    assert "as_const_everywhere" not in names(source, "typescript", engine=True)


@needs_tree_sitter
def test_tree_sitter_flags_optional_chain_on_const_literals_only():
    flagged = "const obj = { k: 1 };\n" + "obj?.k;\n" * 3
    assert "optional_chaining_overuse" in names(flagged, "typescript", engine=True)
    unknown = "function f(obj: { k: number } | null) {\n" + "  obj?.k;\n" * 3 + "}\n"
    assert "optional_chaining_overuse" not in names(unknown, "typescript", engine=True)


@needs_tree_sitter
def test_tree_sitter_arrow_return_type_needs_an_inline_callback():
    declared = (
        "const a = (): void => {};\nconst b = (): string => 'x';\nconst c = (): number => 1;\n"
    )
    inline = "<button onClick={(): void => go()} />;\n"
    assert "explicit_return_types_on_arrow" not in names(declared, "tsx", engine=True)
    assert "explicit_return_types_on_arrow" in names(inline, "tsx", engine=True)


@pytest.mark.parametrize("engine", ENGINES)
def test_tsx_fixture_fires_the_typescript_signals(engine):
    ai = analyze((FIXTURES / "code_ai_like.tsx").read_text(encoding="utf-8"), "tsx", engine=engine)
    assert {s.name for s in ai.signals} >= TS_SIGNALS
    assert ai.score >= 0.3


@pytest.mark.parametrize("engine", ENGINES)
def test_plain_typescript_is_silent(engine):
    human = src(
        """
        export function total(prices: number[]): number {
          return prices.reduce((sum, p) => sum + p, 0);
        }
        """
    )
    assert analyze(human, "typescript", engine=engine).signals == []


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(
    "blob",
    ["?." * 100_000, "as const " * 100_000, '"x" as const;' * 50_000, "(): void => " * 50_000],
    ids=["optional", "as-const", "literals", "arrows"],
)
def test_ts_pathological_input_stays_fast(blob, engine):
    start = time.perf_counter()
    analyze(blob, "typescript", engine=engine)
    assert time.perf_counter() - start < 20


# --- tree-sitter worker: the hang and the quadratic nesting found in review ------------------------

# 21 bytes that send the TSX scanner into an infinite loop that never releases the GIL.
TSX_HANG = "<>{:t.``<T>>[):d'a'x`"


@needs_tree_sitter
def test_a_tree_sitter_hang_is_killed_and_falls_back_to_regex(real_worker, monkeypatch):
    monkeypatch.setattr(sc, "TS_TIMEOUT", 3.0)
    analysis, seconds = timed(sc.analyze, TSX_HANG, "tsx")
    assert any("excedeu" in n and "regex" in n for n in analysis.notes)
    assert analysis.confidence == "low"
    assert seconds < 20
    # the worker was killed, and the next call gets a fresh one that works
    ok = sc.analyze('const a = "x" as const;\n' * 3, "tsx")
    assert ok.notes == ()
    assert "as_const_everywhere" in {s.name for s in ok.signals}


@needs_tree_sitter
def test_the_real_worker_matches_the_in_process_result(real_worker):
    source = (FIXTURES / "code_ai_like.tsx").read_text(encoding="utf-8")
    via_worker = sc.analyze(source, "tsx")
    via_regex = sc.analyze(source, "tsx", use_tree_sitter=False)
    assert via_worker.notes == ()
    assert {s.name for s in via_worker.signals} == {s.name for s in via_regex.signals}


@needs_tree_sitter
def test_deeply_nested_arrows_are_not_quadratic():
    # Node.parent is O(depth): 4000 nested arrows took 11 s, and 8000 took 44 s.
    depth = 4000
    source = "f(" + "(a): void => f(" * depth + "1" + ")" * (depth + 1) + ";\n"
    analysis, seconds = timed(sc.analyze, source, "tsx")
    assert analysis.notes == ()
    assert "explicit_return_types_on_arrow" in {s.name for s in analysis.signals}
    assert seconds < 8


@needs_tree_sitter
def test_node_snippets_come_from_bytes_and_survive_multibyte_text():
    source = 'const s = "ação" as const;\nconst t = "é" as const;\nconst u = "ü" as const;\n'
    hits = sc._ts_extract("typescript", source)["as_const"]
    by_line = dict(hits)  # the DFS order is an implementation detail; analyze() sorts by line
    assert sorted(by_line) == [1, 2, 3]
    assert by_line[1].startswith('"ação" as const')  # starts at the expression, not the line
