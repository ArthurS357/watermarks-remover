#!/usr/bin/env python3
"""Measure how far a rewrite moved the stylometric signals of a text or a source file.

``before`` and ``after`` are two files, or two directories paired by relative path. Both sides go
through ``detect_ai_patterns`` with the same thresholds, so the delta measures the rewrite and not
a change of ruler. ``delta = after - before``: negative is an improvement.

It never says who wrote anything: the report has scores, signal names, an ``effectiveness`` band
for the rewrite and the ``disclaimer``. With directories the top-level fields are the mean score
over the paired files, and a signal counts as present on a side when it fires in any of them.

Exit codes: 0 ran; 1 a path is missing, the two are not both files or both directories, or
--output cannot be used; 2 nothing was paired (also argparse's usage error).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import detect_ai_patterns as detect
from stylometry import (
    CATEGORY,
    CONFIDENCES,
    DISCLAIMER,
    SEVERITIES,
    WEIGHT,
    printable,
    score_signals,
)

TABLE_ROWS = 10

# bandit B105 reads a literal dict key containing "token" as a credential; this one is a metric.
_TTR = "type_token_ratio"

# One action per signal, used by the recommendation. Kept in step with CATEGORY by a test.
ADVICE = {
    "em_dash_density": "troque travessões por vírgula, ponto ou parênteses onde a pontuação simples serve",
    "not_just_but": 'afirme o ponto direto, sem o contraste "não é apenas X, é Y"',
    "delve_family": "troque o verbo de efeito (delve, dive in, vamos explorar) por uma frase que diga o que será mostrado",
    "worth_noting": 'corte a abertura ("vale notar", "importante ressaltar") e escreva o fato',
    "fast_paced_world": "apague a abertura genérica sobre o mundo de hoje e comece pelo assunto",
    "on_the_other_hand_cascade": 'reduza os "por outro lado" a um ou dois e deixe a ordem das frases fazer o contraste',
    "hedge_double": 'mantenha um só qualificador por afirmação ("talvez" ou "pode ser", não os dois)',
    "bold_lead_in": "tire o negrito de abertura dos itens ou reescreva a lista como prosa",
    "tricolon_uniform": "varie a quantidade de itens: um par aqui, quatro ali, um item sozinho",
    "template_heading": 'renomeie títulos do tipo "Por que..." e "O que..." para o conteúdo da seção',
    "emoji_heading": "tire o emoji dos títulos",
    "meta_commentary": 'corte "nesta seção" e "como vimos" e vá ao conteúdo',
    "paragraph_uniformity": "varie as frases por parágrafo: junte os curtos, quebre os longos onde o assunto muda",
    "sentence_uniformity": "alterne frases curtas e longas em vez de um comprimento só",
    "declarative_close": 'reescreva o "Não é X. É Y." como frase normal, sobretudo no último parágrafo',
    "here_is_why": 'responda direto, sem "aqui está por quê:"',
    "comparison_table_symmetry": "use a tabela só se as colunas diferirem de verdade em tamanho; do contrário, prosa",
    _TTR: "varie o vocabulário onde as mesmas palavras se repetem no começo do texto",
    "sentence_length_stddev": "deixe o comprimento das frases variar mais",
    "paragraph_length_stddev": "deixe o comprimento dos parágrafos variar mais",
    "em_dash_to_comma_ratio": "troque parte dos travessões por vírgulas",
    "docstring_echoes_name": "apague a docstring que repete o nome da função ou diga o que o nome não diz",
    "obvious_comment": "apague o comentário que repete a linha seguinte ou explique o porquê",
    "comment_density": "corte os comentários que narram o código e deixe os que explicam uma decisão",
    "type_hint_on_trivial_local": "tire a anotação de tipo de variável local com valor literal óbvio",
    "generic_try_except": "capture a exceção específica e trate-a, em vez de engolir tudo com pass",
    "excessive_params": "agrupe os parâmetros num objeto (dataclass) ou divida a função",
    "over_descriptive_name": "encurte nomes de quatro palavras ou mais para o que o contexto já diz",
    "complete_main_boilerplate": "reduza o __main__ a uma chamada; argparse, logging e try/except só se o script precisa",
    "future_annotations_on_314": "remova o import de __future__ annotations: o projeto exige Python 3.14 ou mais",
    "match_where_if_fits": "troque o match de dois casos simples por if/else",
    "as_const_everywhere": "tire o as const de literais primitivos que o compilador já infere",
    "optional_chaining_overuse": "tire o ?. de valores que não podem ser nulos",
    "jsdoc_on_trivial_type": "apague o @param de tipo trivial que o TypeScript já diz",
    "explicit_return_types_on_arrow": "tire o tipo de retorno explícito das arrows inline",
    "warning_comment": 'remova o "Note:" ou "Important:" sem risco real, ou torne o aviso específico',
    "todo_comment_style": "troque os TODO(autor): iguais por issues, ou apague os que já foram feitos",
}


def effectiveness(delta: float) -> str:
    """``delta < -0.30`` high; ``-0.30 <= delta < -0.10`` medium; anything else low."""
    delta = round(delta, 4)  # the raw difference of two scores carries float noise
    if delta < -0.30:
        return "high"
    return "medium" if delta < -0.10 else "low"


@dataclass(frozen=True)
class Side:
    """One file on one side of the comparison, after the ``--signals`` filter."""

    score: float
    confidence: str
    found: dict[str, tuple[str, float]]  # signal -> (worst severity, file total)


def side(result: detect.FileResult, only: frozenset[str] | None) -> Side:
    signals = [s for s in result.signals if only is None or s.name in only]
    found: dict[str, tuple[str, float]] = {}
    for s in signals:
        if s.name not in found or SEVERITIES.index(s.severity) > SEVERITIES.index(found[s.name][0]):
            found[s.name] = (s.severity, s.value)
    score = result.score if only is None else score_signals(signals)
    return Side(score, result.confidence, found)


def _summary(sides: Iterable[Side]) -> tuple[dict[str, str], dict[str, float], Counter[str]]:
    """Per signal: worst severity, largest value, and in how many files it fires."""
    severity: dict[str, str] = {}
    value: dict[str, float] = {}
    files: Counter[str] = Counter()
    for one in sides:
        for name, (level, total) in one.found.items():
            files[name] += 1
            if name not in severity or SEVERITIES.index(level) > SEVERITIES.index(severity[name]):
                severity[name] = level
            value[name] = max(value.get(name, 0), total)
    return severity, value, files


def _rank(names: Iterable[str], severity: dict[str, str]) -> list[str]:
    return sorted(names, key=lambda n: (-SEVERITIES.index(severity[n]), n))


def recommend(severity: dict[str, str], remaining: set[str]) -> str:
    """The worst signal still present after the rewrite (structural before lexical before metric
    when tied; one that survived before one the rewrite introduced) and what to do about it."""
    if not severity:
        return "Nenhum sinal restante."
    top = min(
        severity,
        key=lambda n: (-SEVERITIES.index(severity[n]), n not in remaining, -WEIGHT[CATEGORY[n]], n),
    )
    level = severity[top]
    lead = "" if level == "high" else "Sem sinal de severidade alta restante. "
    origin = "Ainda dispara" if top in remaining else "A reescrita introduziu"
    return f"{lead}{origin} `{top}` ({level}): {ADVICE[top]}."


def compare(pairs: Sequence[tuple[Side, Side]]) -> dict[str, Any]:
    """The report fields for one pair, or for the mean over several."""
    before = round(sum(b.score for b, _ in pairs) / len(pairs), 4)
    after = round(sum(a.score for _, a in pairs) / len(pairs), 4)
    delta = round(after - before, 4)
    sev_b, val_b, files_b = _summary(b for b, _ in pairs)
    sev_a, val_a, files_a = _summary(a for _, a in pairs)
    remaining = sev_b.keys() & sev_a.keys()
    return {
        "before_score": before,
        "after_score": after,
        "delta": delta,
        "signals_before": _rank(sev_b, sev_b),
        "signals_after": _rank(sev_a, sev_a),
        "signals_remaining": _rank(remaining, sev_a),
        "signals_eliminated": _rank(sev_b.keys() - sev_a.keys(), sev_b),
        "effectiveness": effectiveness(delta),
        "recommendation": recommend(sev_a, set(remaining)),
        "signals_introduced": _rank(sev_a.keys() - sev_b.keys(), sev_a),
        "signal_deltas": {
            name: {
                "files_before": files_b[name],
                "files_after": files_a[name],
                "severity_before": sev_b.get(name),
                "severity_after": sev_a.get(name),
                "value_before": val_b.get(name, 0),
                "value_after": val_a.get(name, 0),
            }
            for name in sorted(sev_b.keys() | sev_a.keys())
        },
        # a comparison is only as sure as the weakest of its samples
        "confidence": min((x.confidence for pair in pairs for x in pair), key=CONFIDENCES.index),
    }


# --- reports -----------------------------------------------------------------------------------


def render_md(report: dict[str, Any]) -> str:
    out = ["# Medição de efetividade", "", f"> {DISCLAIMER}", ""]
    out.append(
        f"- Score: {report['before_score']:.2f} → {report['after_score']:.2f} "
        f"(delta {report['delta']:+.2f})"
    )
    out.append(f"- Efetividade: **{report['effectiveness']}** · confiança {report['confidence']}")
    if "signals_filter" in report:
        out.append("- Só estes sinais: " + ", ".join(f"`{n}`" for n in report["signals_filter"]))
    for label, key in (
        ("Eliminados", "signals_eliminated"),
        ("Restantes", "signals_remaining"),
        ("Introduzidos", "signals_introduced"),
    ):
        names = ", ".join(f"`{n}`" for n in report[key]) or "nenhum"
        out.append(f"- {label} ({len(report[key])}): {names}")
    out += ["", f"**Recomendação:** {report['recommendation']}", ""]
    if report.get("files"):
        rows = sorted(report["files"].items(), key=lambda kv: (-kv[1]["delta"], kv[0]))
        out += ["## Arquivos (os menos melhorados primeiro)", ""]
        out += ["| Arquivo | Antes | Depois | Delta | Efetividade |", "|---|---|---|---|---|"]
        out += [
            f"| {detect.quote(path)} | {f['before_score']:.2f} | {f['after_score']:.2f} "
            f"| {f['delta']:+.2f} | {f['effectiveness']} |"
            for path, f in rows[:TABLE_ROWS]
        ]
        if len(rows) > TABLE_ROWS:
            out += ["", f"(+{len(rows) - TABLE_ROWS}) arquivos fora da tabela; estão no JSON"]
        out.append("")
    for title, key in (
        ("Sem par: só antes", "unmatched_before"),
        ("Sem par: só depois", "unmatched_after"),
    ):
        if report.get(key):
            out += [f"## {title}", "", *(f"- {detect.quote(p)}" for p in report[key]), ""]
    if report["skipped"]:
        out += ["## Arquivos pulados", ""]
        out += [
            f"- {detect.quote(s['path'])} ({s['side']}): {printable(s['reason'])}"
            for s in report["skipped"]
        ]
        out.append("")
    return "\n".join(out)


# --- command line ------------------------------------------------------------------------------


def _signal_names(text: str) -> frozenset[str]:
    names = {n.strip() for n in text.split(",") if n.strip()}
    if not names:
        raise argparse.ArgumentTypeError("informe ao menos um sinal")
    if unknown := sorted(names - CATEGORY.keys()):
        raise argparse.ArgumentTypeError(f"sinal desconhecido: {', '.join(unknown)}")
    return frozenset(names)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("before", help="the original: a file or a directory")
    p.add_argument("after", help="the rewrite: a file, or a directory with the same relative names")
    p.add_argument("--format", choices=("json", "md"), default="json")
    p.add_argument(
        "--signals",
        type=_signal_names,
        metavar="CSV",
        help="measure only these signals (names as in the detection report); the score is "
        "recomputed from them",
    )
    p.add_argument("--output", metavar="FILE", help="write the report here instead of stdout")
    return p


def _pair_up(
    before: detect.Scan, after: detect.Scan, only: frozenset[str] | None, directories: bool
) -> dict[str, tuple[Side, Side]]:
    """Matched files as ``{name in after: (before side, after side)}``."""
    if directories:
        matched = [(n, n) for n in sorted(before.files.keys() & after.files.keys())]
    elif before.files and after.files:  # two files pair whatever their names are
        matched = [(next(iter(before.files)), next(iter(after.files)))]
    else:
        matched = []
    return {a: (side(before.files[b], only), side(after.files[a], only)) for b, a in matched}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    detect.utf8_streams()
    before_root, after_root = Path(args.before), Path(args.after)
    for root in (before_root, after_root):
        if not root.exists():
            print(f"erro: o caminho não existe: {root}", file=sys.stderr)
            return 1
    directories = before_root.is_dir()
    if directories != after_root.is_dir():
        print("erro: os dois caminhos devem ser ambos arquivo ou ambos pasta", file=sys.stderr)
        return 1
    output = Path(args.output).resolve() if args.output else None
    if output in (before_root.resolve(), after_root.resolve()):
        print("erro: --output aponta para um dos arquivos comparados", file=sys.stderr)
        return 1
    options = detect.Options(skip=output, warn=False)  # the warnings below say which side
    before, after = detect.scan(before_root, options), detect.scan(after_root, options)
    skipped = [
        {"side": name, "path": rel, "reason": reason}
        for name, scanned in (("before", before), ("after", after))
        for rel, reason in scanned.skipped
    ]
    for entry in skipped:
        label = "antes" if entry["side"] == "before" else "depois"
        path, reason = printable(entry["path"]), printable(entry["reason"])
        print(f"aviso ({label}): {path} pulado: {reason}", file=sys.stderr)
    pairs = _pair_up(before, after, args.signals, directories)
    if not pairs:
        print("erro: nenhum arquivo pareado para comparar", file=sys.stderr)
        return 2
    report: dict[str, Any] = {
        "mode": "directory" if directories else "file",
        **compare(list(pairs.values())),
    }
    if args.signals is not None:
        report["signals_filter"] = sorted(args.signals)
    if directories:
        skipped_before = {p for p, _ in before.skipped}
        skipped_after = {p for p, _ in after.skipped}
        report["files"] = {name: compare([pair]) for name, pair in pairs.items()}
        report["unmatched_before"] = sorted(
            n for n in before.files if n not in after.files and n not in skipped_after
        )
        report["unmatched_after"] = sorted(
            n for n in after.files if n not in before.files and n not in skipped_before
        )
    report["skipped"] = skipped
    report["disclaimer"] = DISCLAIMER
    text = (
        render_md(report)
        if args.format == "md"
        else json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    if output is None:
        sys.stdout.write(text)
        return 0
    try:
        output.write_bytes(text.encode("utf-8"))  # bytes: no newline translation
    except OSError as exc:
        print(f"erro: não foi possível escrever {output}: {exc.strerror}", file=sys.stderr)
        return 1
    print(f"relatório escrito em {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
