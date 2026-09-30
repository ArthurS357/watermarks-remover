#!/usr/bin/env python3
"""Rewrite the prose habits that ``detect_ai_patterns`` flags, deterministically and conservatively.

Eight rewrites, each gated by the detector (a signal it does not see is never touched): bold
lead-ins, dense em dashes, template and emoji headings, doubled hedges, "delve into", "it's worth
noting that" and "in today's fast-paced world,". Names, numbers, hashes, inline code, URLs, paths,
quoted strings, identifiers, fenced code and tables are masked first and never altered. Sentence
rhythm, vocabulary and code signals are out of scope: they need a rewrite, not a substitution.
Running it on its own output changes nothing.

It reads one .md or .txt file. Default: the naturalized text on stdout. ``--diff-only``
prints the unified diff and writes nothing (review this first: a retitled heading can break a link
from another file). ``--in-place`` writes the file by replacement, keeping its BOM and line endings.
``--format json|md`` prints a report: signals and score before and after, every edit, what was masked.

The score is ``detect_ai_patterns``'s. It is indicative, not a verdict.

Exit codes: 0 ran and changed something; 1 the path does not exist, is not a file, or --output /
--in-place could not write; 2 unsupported input (extension, not UTF-8, over 1 MB) and argparse's
usage error; 3 nothing applicable (the text comes out unchanged).
"""

from __future__ import annotations

import argparse
import codecs
import difflib
import fnmatch
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import detect_ai_patterns as detect
from measure_skill_effectiveness import effectiveness
from stylometry import (
    CONFIDENCES,
    DISCLAIMER,
    SEVERITIES,
    Analysis,
    clean,
    loaders,
    printable,
    split_lines,
)
from stylometry import naturalize as engine

SUPPORTED = ("markdown", "text")  # the loaders' names for .md and .txt
MAX_EDITS = 500  # edits listed in a report; the total is always reported
MAX_SPANS = 100
TABLE_ROWS = 30
CONTEXT = 25  # characters of context around a change in a report row


@dataclass(frozen=True)
class Source:
    path: Path
    text: str
    bom: bool

    def encode(self, text: str) -> bytes:
        return (codecs.BOM_UTF8 if self.bom else b"") + text.encode("utf-8")


def read_source(path: Path) -> Source | str:
    """The file decoded as UTF-8, or the reason it cannot be handled (exit 2)."""
    fmt = loaders.format_of(path)
    if fmt is None or fmt[1] not in SUPPORTED:
        return f"formato não suportado: {path.suffix or '(sem extensão)'} (só .md e .txt)"
    try:
        with path.open("rb") as handle:  # the real cap: the size can change after stat()
            data = handle.read(loaders.MAX_TEXT_BYTES + 1)
    except OSError as exc:
        return f"erro de leitura: {exc.strerror or type(exc).__name__}"
    if len(data) > loaders.MAX_TEXT_BYTES:
        return f"arquivo maior que o limite ({loaders.MAX_TEXT_BYTES} bytes)"
    bom = data.startswith(codecs.BOM_UTF8)
    try:
        text = data.removeprefix(codecs.BOM_UTF8).decode("utf-8")
    except UnicodeDecodeError:
        return "o arquivo não é UTF-8 válido"
    if "\x00" in text:
        return "conteúdo binário"
    return Source(path, text, bom)


# --- reports -----------------------------------------------------------------------------------


def unified_diff(before: str, after: str, name: str) -> str:
    """A unified diff for a human: control characters other than tab become ``?``, so a file
    carrying an escape sequence cannot drive the terminal."""
    lines = difflib.unified_diff(
        split_lines(before),
        split_lines(after),
        fromfile=name,
        tofile=f"{name} (naturalizado)",
        lineterm="",
    )
    safe = [
        "".join("?" if unicodedata.category(c) == "Cc" and c != "\t" else c for c in line)
        for line in lines
    ]
    return "\n".join(safe) + "\n" if safe else ""


def _ranked(analysis: Analysis) -> list[str]:
    worst: dict[str, int] = {}
    for s in analysis.signals:
        worst[s.name] = max(worst.get(s.name, 0), SEVERITIES.index(s.severity))
    return sorted(worst, key=lambda n: (-worst[n], n))


def _changed(before: str, after: str) -> tuple[str, str]:
    """The differing middle of two lines, with some context, so a long line shows its change."""
    shortest = min(len(before), len(after))
    head = next((i for i in range(shortest) if before[i] != after[i]), shortest)
    tail = next(
        (j for j in range(shortest - head) if before[-1 - j] != after[-1 - j]), shortest - head
    )
    start = max(0, head - CONTEXT)
    return before[start : len(before) - tail + CONTEXT], after[start : len(after) - tail + CONTEXT]


def build_report(
    source: Source, result: engine.Result, mode: str, notes: Sequence[str]
) -> dict[str, Any]:
    delta = round(result.after.score - result.before.score, 4)
    edits = []
    for edit in result.transforms[:MAX_EDITS]:
        old, new = _changed(edit.before, edit.after)
        edits.append(
            {"signal": edit.signal, "line": edit.line, "before": clean(old), "after": clean(new)}
        )
    spans = [{"kind": s.kind, "line": s.line, "text": s.text} for s in result.preserved[:MAX_SPANS]]
    confidence = min(result.before.confidence, result.after.confidence, key=CONFIDENCES.index)
    return {
        "file": printable(str(source.path)),
        "mode": mode,
        "signals_before": _ranked(result.before),
        "signals_after": _ranked(result.after),
        "score_before": result.before.score,
        "score_after": result.after.score,
        "delta": delta,
        "effectiveness": effectiveness(delta),
        "transforms": edits,
        "transforms_total": len(result.transforms),
        "preserved_spans": spans,
        "preserved_total": len(result.preserved),
        "confidence": confidence,
        "notes": list(notes),
        "diff": unified_diff(source.text, result.text, source.path.name),
        "disclaimer": DISCLAIMER,
    }


def _fence(body: str) -> str:
    """A code fence longer than any backtick run in ``body``."""
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    return "`" * max(3, longest + 1)


def _cell(text: str) -> str:
    """``text`` quoted for a markdown table cell: a pipe would split the cell, even in code."""
    return detect.quote(text).replace("|", chr(92) + "|")


def render_md(report: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for edit in report["transforms"]:
        counts[edit["signal"]] = counts.get(edit["signal"], 0) + 1
    by_signal = ", ".join(f"{name} {n}" for name, n in sorted(counts.items())) or "nenhuma"
    out = ["# Naturalização", "", f"> {DISCLAIMER}", ""]
    out.append(f"- Arquivo: {detect.quote(report['file'])} ({report['mode']})")
    out.append(
        f"- Score: {report['score_before']:.2f} → {report['score_after']:.2f} "
        f"(delta {report['delta']:+.2f}) · efetividade **{report['effectiveness']}** · "
        f"confiança {report['confidence']}"
    )
    out.append(f"- Transformações: {report['transforms_total']} ({by_signal})")
    for label, key in (("Sinais antes", "signals_before"), ("Sinais depois", "signals_after")):
        out.append(f"- {label}: " + (", ".join(f"`{n}`" for n in report[key]) or "nenhum"))
    out += [f"- _{n}_" for n in report["notes"]]
    if report["transforms"]:
        out += [
            "",
            "## Transformações",
            "",
            "| Sinal | Linha | Antes | Depois |",
            "|---|---|---|---|",
        ]
        out += [
            f"| `{e['signal']}` | {e['line']} | {_cell(e['before'])} | {_cell(e['after'])} |"
            for e in report["transforms"][:TABLE_ROWS]
        ]
        if len(report["transforms"]) > TABLE_ROWS:
            out.append(
                f"\n(+{report['transforms_total'] - TABLE_ROWS}) fora da tabela; estão no diff"
            )
    if report["diff"]:
        fence = _fence(report["diff"])
        out += ["", "## Diff", "", f"{fence}diff", report["diff"].rstrip("\n"), fence]
    return "\n".join(out) + "\n"


# --- command line ------------------------------------------------------------------------------


def _signal_names(text: str) -> frozenset[str]:
    names = {n.strip() for n in text.split(",") if n.strip()}
    if not names:
        raise argparse.ArgumentTypeError("informe ao menos um sinal")
    if unknown := sorted(names - set(engine.TRANSFORMS)):
        raise argparse.ArgumentTypeError(
            f"sinal sem transformação: {', '.join(unknown)} (disponíveis: {', '.join(engine.TRANSFORMS)})"
        )
    return frozenset(names)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("path", help="a .md or .txt file")
    p.add_argument("--format", choices=("text", "md", "json"), default="text")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--diff-only", action="store_true", help="print the diff, write nothing")
    mode.add_argument(
        "--in-place", action="store_true", help="overwrite the file (default: stdout)"
    )
    p.add_argument(
        "--signals",
        type=_signal_names,
        metavar="CSV",
        help=f"only these rewrites ({', '.join(engine.TRANSFORMS)})",
    )
    p.add_argument(
        "--preserve",
        action="append",
        default=[],
        metavar="GLOB",
        help="never touch a file whose path matches GLOB, or a line that matches it (repeatable)",
    )
    p.add_argument("--output", metavar="FILE", help="write the result here instead of stdout")
    return p


def write_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` in one step, keeping its permissions."""
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as tmp:
            tmp.write(data)
        shutil.copymode(path, name)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _payload(
    args: argparse.Namespace, source: Source, result: engine.Result, report: dict[str, Any]
) -> bytes:
    if args.format == "json":
        return (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.format == "md":
        return render_md(report).encode("utf-8")
    if args.diff_only:
        return str(report["diff"]).encode("utf-8")
    return source.encode(result.text)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    detect.utf8_streams()
    path = Path(args.path)
    if not path.exists():
        print(f"erro: o caminho não existe: {path}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"erro: não é um arquivo: {path}", file=sys.stderr)
        return 1
    source = read_source(path)
    if isinstance(source, str):
        print(f"erro: {printable(source)}", file=sys.stderr)
        return 2
    output = Path(args.output).resolve() if args.output else None
    if output is not None and output == path.resolve():
        print("erro: --output aponta para o próprio arquivo", file=sys.stderr)
        return 1
    notes: list[str] = []
    skip = any(
        fnmatch.fnmatchcase(p, g) for g in args.preserve for p in (path.as_posix(), path.name)
    )
    if skip:
        notes.append("arquivo preservado por --preserve")
    try:
        result = engine.naturalize(
            source.text, signals=() if skip else args.signals, preserve=args.preserve
        )
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    mode = "diff-only" if args.diff_only else "in-place" if args.in_place else "stdout"
    report = build_report(source, result, mode, notes)
    data = _payload(args, source, result, report)
    try:
        if args.in_place and result.changed:
            write_atomically(path.resolve(), source.encode(result.text))
            print(f"escrito em {path} ({len(result.transforms)} transformações)", file=sys.stderr)
        if output is not None:
            output.write_bytes(data)
            print(f"resultado escrito em {output}", file=sys.stderr)
        elif not (args.in_place and args.format == "text"):
            sys.stdout.flush()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except OSError as exc:
        print(f"erro: não foi possível escrever: {exc.strerror}", file=sys.stderr)
        return 1
    return 0 if result.changed else 3


if __name__ == "__main__":
    sys.exit(main())
