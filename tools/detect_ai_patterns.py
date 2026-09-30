#!/usr/bin/env python3
"""Detect stylometric "AI style" signals in prose and source code.

A personal-use review aid: it points at habits in what *you* wrote (em-dash tics, template
headings, obvious comments, ...) so you can rewrite them. It never says whether a text was
written by an AI: the output is ``signals``, a ``score`` from 0.0 to 1.0, a ``confidence`` and a
``disclaimer``. Deterministic: regexes, ``ast`` and counts, no model, no network.

Text: .md .txt .html .docx .pdf     Code: .py .ts .tsx .js .jsx
.docx/.pdf and tree-sitter (.ts/.tsx/.js/.jsx) need the optional ``formats`` dependency group;
without it those files are skipped with a warning (or, for TS/JS, analysed by regex).

Exit codes: 0 ran; 1 the path does not exist (or --output cannot be used); 2 nothing was analysed
(also argparse's usage error).
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import os
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stylometry import (
    DISCLAIMER,
    SEVERITIES,
    Analysis,
    Signal,
    cap_confidence,
    loaders,
    printable,
)
from stylometry import code as code_signals
from stylometry import text as text_signals

# Never descended into: dependency trees, caches and VCS metadata (scanning ``.venv`` from the
# repo root would take forever and report other people's code).
DEFAULT_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".code-review-graph",
        "dist",
        "build",
    }
)
TEST_DIRS = frozenset({"tests", "test", "__tests__"})
TEST_FILE_PATTERNS = (
    "test_*.py",
    "*_test.py",
    "conftest.py",
    "*.test.ts",
    "*.test.tsx",
    "*.test.js",
    "*.test.jsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*.spec.js",
    "*.spec.jsx",
)
SMALL_PROJECT_FILES = 50  # over_descriptive_name only applies up to this many code files
EXTRACTED = ("html", "docx", "pdf")  # formats whose line numbers refer to the extracted text
TOP_FILES = 10
LINES_PER_SIGNAL = 5


@dataclass(frozen=True)
class Options:
    only: str = "all"  # text | code | all
    ignore: tuple[str, ...] = ()
    exclude_tests: bool = False
    skip: Path | None = None  # resolved path that is never scanned (the report being written)


@dataclass(frozen=True)
class FileResult:
    path: str  # relative to the scan root, posix separators
    language: str
    kind: str
    score: float
    confidence: str
    signals: list[Signal]
    notes: list[str]


@dataclass
class Scan:
    files: dict[str, FileResult] = field(default_factory=dict)
    skipped: list[tuple[str, str]] = field(default_factory=list)


# --- finding files -----------------------------------------------------------------------------


def _ignored(rel: str, name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in patterns)


def iter_files(root: Path, options: Options) -> Iterator[Path]:
    """Files under ``root`` in a stable order. Symlinks and NTFS junctions are never followed."""
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        rel_dir = here.relative_to(root)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in DEFAULT_IGNORED_DIRS
            and not os.path.isjunction(here / d)  # walk() follows junctions; islink() is False
            and not _ignored((rel_dir / d).as_posix(), d, options.ignore)
            and not (options.exclude_tests and d in TEST_DIRS)
        )
        for name in sorted(filenames):
            path = here / name
            if path.is_symlink() or _ignored((rel_dir / name).as_posix(), name, options.ignore):
                continue
            if options.exclude_tests and any(fnmatch.fnmatch(name, p) for p in TEST_FILE_PATTERNS):
                continue
            if options.skip is not None and path.resolve() == options.skip:
                continue
            yield path


def _analyze(loaded: loaders.Loaded, ctx: code_signals.Context) -> Analysis:
    if loaded.kind == "text":
        return text_signals.analyze(loaded.text)
    return code_signals.analyze(loaded.text, loaded.language, ctx)


def scan(root: Path, options: Options) -> Scan:
    """Analyse every supported file under ``root`` (a file or a directory)."""
    root = root.resolve()
    base = root if root.is_dir() else root.parent
    candidates: list[tuple[Path, str]] = []
    for path in iter_files(root, options):
        fmt = loaders.format_of(path)
        if fmt is None or (options.only != "all" and fmt[0] != options.only):
            continue
        candidates.append((path, fmt[0]))
    candidates.sort(key=lambda c: c[0].relative_to(base).as_posix())  # one global, stable order
    small = sum(1 for _, kind in candidates if kind == "code") <= SMALL_PROJECT_FILES
    result = Scan()
    for path, _ in candidates:
        rel = path.relative_to(base).as_posix()
        loaded = loaders.load(path)
        if isinstance(loaded, loaders.UnsupportedFormat):
            result.skipped.append((rel, loaded.reason))
            print(f"aviso: {printable(rel)} pulado: {printable(loaded.reason)}", file=sys.stderr)
            continue
        ctx = code_signals.Context(
            small_project=small,
            requires_python=loaders.find_requires_python(path.parent)
            if loaded.language == "python"
            else None,
        )
        analysis = _analyze(loaded, ctx)
        notes = [*loaded.notes, *analysis.notes]
        if loaded.language in EXTRACTED:
            notes.append("linhas se referem ao texto extraído, não ao arquivo original")
        result.files[rel] = FileResult(
            rel,
            loaded.language,
            loaded.kind,
            analysis.score,
            cap_confidence(analysis.confidence, loaded.confidence_cap),
            analysis.signals,
            notes,
        )
    return result


# --- reports -----------------------------------------------------------------------------------


def listed(signals: list[Signal], min_severity: str) -> list[Signal]:
    """The signals a report shows. ``--min-severity`` hides; it never changes the score."""
    floor = SEVERITIES.index(min_severity)
    return [s for s in signals if SEVERITIES.index(s.severity) >= floor]


def by_signal(result: Scan, min_severity: str) -> dict[str, dict[str, Any]]:
    files: Counter[str] = Counter()
    worst: dict[str, int] = {}
    for f in result.files.values():
        names = {s.name for s in listed(f.signals, min_severity)}
        files.update(names)
        for s in listed(f.signals, min_severity):
            worst[s.name] = max(worst.get(s.name, 0), SEVERITIES.index(s.severity))
    return {
        name: {"files": files[name], "max_severity": SEVERITIES[worst[name]]}
        for name in sorted(files, key=lambda n: (-files[n], n))
    }


def render_json(result: Scan, min_severity: str) -> str:
    report = {
        "files_scanned": len(result.files),
        "by_format": dict(sorted(Counter(f.language for f in result.files.values()).items())),
        "by_signal": by_signal(result, min_severity),
        "scores": {
            f.path: {
                "format": f.language,
                "kind": f.kind,
                "score": f.score,
                "confidence": f.confidence,
                "signals": [s._asdict() for s in listed(f.signals, min_severity)],
                "notes": f.notes,
            }
            for f in result.files.values()
        },
        "skipped": [{"path": p, "reason": r} for p, r in result.skipped],
        "disclaimer": DISCLAIMER,
    }
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def _quote(text: str) -> str:
    return "`" + printable(text).replace("`", "'") + "`"


def render_md(result: Scan, min_severity: str) -> str:
    files = sorted(result.files.values(), key=lambda f: (-f.score, f.path))
    formats = ", ".join(f"{k} {v}" for k, v in sorted(Counter(f.language for f in files).items()))
    out = ["# Relatório estilométrico", "", f"> {DISCLAIMER}", ""]
    out.append(f"- Arquivos analisados: {len(files)}" + (f" ({formats})" if formats else ""))
    if result.skipped:
        out.append(f"- Arquivos pulados: {len(result.skipped)} (lista no fim)")
    if min_severity != "low":
        out.append(f"- Só sinais de severidade {min_severity} ou mais; o score usa todos")
    frequent = by_signal(result, min_severity)
    if frequent:
        out += ["", "## Sinais mais frequentes", "", "| Sinal | Arquivos | Severidade máxima |"]
        out.append("|---|---|---|")
        out += [f"| `{n}` | {i['files']} | {i['max_severity']} |" for n, i in frequent.items()]
    shown = [f for f in files if listed(f.signals, min_severity)][:TOP_FILES]
    out += ["", f"## Top {TOP_FILES} arquivos por score", ""]
    if not shown:
        out.append("Nenhum sinal no nível pedido.")
    for rank, f in enumerate(shown, 1):
        out += [f"### {rank}. {_quote(f.path)}", ""]
        out.append(f"Score {f.score:.2f} · confiança {f.confidence} · {f.language}")
        out.append("")
        groups: dict[str, list[Signal]] = {}
        for s in listed(f.signals, min_severity):
            groups.setdefault(s.name, []).append(s)
        for name, group in sorted(
            groups.items(), key=lambda kv: -SEVERITIES.index(kv[1][0].severity)
        ):
            where = [s for s in group if s.line is not None]
            detail = "; ".join(
                f"linha {s.line}: {_quote(s.snippet)}" for s in where[:LINES_PER_SIGNAL]
            )
            more = f" (+{len(where) - LINES_PER_SIGNAL})" if len(where) > LINES_PER_SIGNAL else ""
            if not where:  # a document-level metric has no line
                detail = f"documento: {_quote(group[0].snippet)}"
            out.append(
                f"- `{name}` ({group[0].severity}, valor {group[0].value:g}): {detail}{more}"
            )
        out += [f"- _{n}_" for n in f.notes]
        out.append("")
    if result.skipped:
        skipped = [f"- {_quote(p)}: {printable(r)}" for p, r in result.skipped]
        out += ["## Arquivos pulados", "", *skipped, ""]
    return "\n".join(out)


# --- command line ------------------------------------------------------------------------------


def _utf8_streams() -> None:
    """Snippets carry emoji and em dashes; Windows consoles default to cp1252 and would crash."""
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("path", help="file or directory (recursive)")
    p.add_argument("--format", choices=("json", "md"), default="json")
    p.add_argument("--only", choices=("text", "code", "all"), default="all")
    p.add_argument("--min-severity", choices=SEVERITIES, default="low")
    p.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip paths matching GLOB (repeatable); matched on the relative path and the name",
    )
    p.add_argument("--output", metavar="FILE", help="write the report here instead of stdout")
    p.add_argument("--exclude-tests", action="store_true", help="skip test files and folders")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _utf8_streams()
    root = Path(args.path)
    if not root.exists():
        print(f"erro: o caminho não existe: {root}", file=sys.stderr)
        return 1
    output = Path(args.output).resolve() if args.output else None
    if output is not None and output == root.resolve():
        print("erro: --output aponta para o próprio arquivo analisado", file=sys.stderr)
        return 1
    options = Options(args.only, tuple(args.ignore), args.exclude_tests, output)
    result = scan(root, options)
    render = render_md if args.format == "md" else render_json
    report = render(result, args.min_severity)
    if output is None:
        sys.stdout.write(report)
    else:
        try:
            output.write_bytes(report.encode("utf-8"))  # bytes: no newline translation
        except OSError as exc:
            print(f"erro: não foi possível escrever {output}: {exc.strerror}", file=sys.stderr)
            return 1
        print(f"relatório escrito em {output}", file=sys.stderr)
    return 0 if result.files else 2


if __name__ == "__main__":
    sys.exit(main())
