#!/usr/bin/env python3
"""Build and measure a personal corpus: texts you wrote (human/) against texts a model wrote (ai/).

``init`` creates the two folders, ``check`` counts what is in them, and ``compare`` scores every
file with ``detect_ai_patterns`` and says, with a number, whether that detector separates the two
sides well enough to stay deterministic or whether a learned model is worth investigating. The
corpus is private and never versioned: it lives outside the repository (default ``<temp>/corpus``)
and ``init`` refuses a folder inside it. Procedure and how to read the result: docs/CORPUS.md.

Exit codes: 0 ran; 1 the corpus is missing, too small (fewer than 10 files in a folder), degenerate
(no variance in either folder) or cannot be created; 2 usage error (argparse).
"""

from __future__ import annotations

import argparse
import contextlib
import math
import statistics
import sys
import tempfile
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from detect_ai_patterns import Options, iter_files, scan, utf8_streams
from stylometry import DISCLAIMER, printable

ROOT = Path(__file__).resolve().parents[1]
LONG_PATH = chr(92) * 2 + "?" + chr(92)  # the Windows extended-length prefix, which resolve() keeps
SIDES = ("human", "ai")
MIN_PER_SIDE = 10  # below this a standard deviation is not worth printing
STABLE_PER_SIDE = 30  # below this d and AUC swing a lot from one sample to the next
D_SUFFICIENT = 0.8  # Cohen's "large"
D_MARGINAL = 0.5  # Cohen's "medium"
Z95 = 1.96
SUFFICIENT, INCONCLUSIVE, ML = "determinístico suficiente", "inconclusivo", "ML justificado"

README = """\
# Corpus pessoal

human/  textos que VOCÊ escreveu, sem ajuda de modelo (e-mails, notas, relatórios, posts).
ai/     textos que um modelo escreveu para você (cole a saída sem editar).

- No mínimo 10 arquivos em cada pasta; 30 ou mais para o resultado ficar estável.
- .md, .txt ou .html (.docx e .pdf só com o grupo `formats` instalado). Código não conta.
- Mesmo assunto e tamanho parecido nos dois lados, senão o detector mede tema e não estilo.
- Nada daqui entra no git.

Depois, com tools/build_corpus.py: `check` confere o corpus e `compare` mede.
"""


class Side(NamedTuple):
    scores: list[float]  # ascending
    skipped: int  # a supported format that could not be read
    ignored: int  # another extension, or code: the detector does not score it here


def default_dir() -> Path:
    return Path(tempfile.gettempdir()) / "corpus"


def inside_repo(path: Path) -> bool:
    """``resolve()`` keeps a long-path prefix on Windows, which would hide the repo from
    ``is_relative_to``."""
    return Path(str(path.resolve()).removeprefix(LONG_PATH)).is_relative_to(ROOT)


def quoted(path: Path) -> str:
    return f'"{printable(str(path))}"'


def measure(corpus: Path, side: str) -> Side:
    root, options = corpus / side, Options(only="text", warn=False)
    result = scan(root, options)
    seen = sum(1 for _ in iter_files(root.resolve(), options))
    scored, skipped = len(result.files), len(result.skipped)
    return Side(sorted(f.score for f in result.files.values()), skipped, seen - scored - skipped)


def cohens_d(human: Sequence[float], ai: Sequence[float]) -> float | None:
    """Mean of ``ai`` minus mean of ``human``, over the pooled standard deviation. Two or more
    values per side. ``None`` when neither side varies: there is no spread to measure against."""
    n1, n2 = len(human), len(ai)
    pooled_var = ((n1 - 1) * statistics.variance(human) + (n2 - 1) * statistics.variance(ai)) / (
        n1 + n2 - 2
    )
    if pooled_var == 0:
        return None
    return (statistics.fmean(ai) - statistics.fmean(human)) / math.sqrt(pooled_var)


def interval(d: float, n1: int, n2: int) -> tuple[float, float]:
    """Approximate 95% interval of ``d`` (Hedges and Olkin's standard error)."""
    se = math.sqrt((n1 + n2) / (n1 * n2) + d * d / (2 * (n1 + n2)))
    return d - Z95 * se, d + Z95 * se


def auc(human: Sequence[float], ai: Iterable[float]) -> float:
    """Chance that a random ai text outscores a random human one; a tie counts half. ``human``
    must be sorted."""
    ai = list(ai)
    wins = sum((bisect_left(human, s) + bisect_right(human, s)) / 2 for s in ai)
    return wins / (len(human) * len(ai))


def band(d: float) -> str:
    return SUFFICIENT if d >= D_SUFFICIENT else INCONCLUSIVE if d >= D_MARGINAL else ML


def verdict(d: float, n1: int, n2: int) -> tuple[str, str]:
    """The recommendation and its reading. The label is the band the whole 95% interval of ``d``
    falls in; an interval that crosses a threshold is inconclusive, however the point lands."""
    low, high = (band(x) for x in interval(d, n1, n2))
    if low != high:
        return (
            INCONCLUSIVE,
            "o intervalo de confiança de d cruza um limiar: com mais arquivos o rótulo pode mudar.",
        )
    if low == SUFFICIENT:
        return SUFFICIENT, "o detector atual separa os dois lados."
    if low == INCONCLUSIVE:
        return INCONCLUSIVE, "separa, mas com sobreposição: recalibre limiares antes de ML."
    note = "o detector atual quase não separa os dois lados."
    if d < 0:
        note = "o texto de IA pontua abaixo do humano: confira se as pastas não estão trocadas."
    return ML, note + " Vale investigar, mas um corpus pessoal é pequeno para treinar."


def describe(name: str, side: Side) -> str:
    extra = f", {side.skipped} pulado(s)" if side.skipped else ""
    extra += f", {side.ignored} ignorado(s) (outra extensão ou código)" if side.ignored else ""
    if not side.scores:
        return f"{name}: 0 arquivos{extra}"
    s = side.scores
    spread = f"mín {s[0]:.3f}, mediana {statistics.median(s):.3f}, máx {s[-1]:.3f}"
    return f"{name}: {len(s)} arquivos ({spread}){extra}"


def check(corpus: Path, sides: dict[str, Side]) -> int:
    print(f"corpus: {printable(str(corpus))}")
    short = {
        n: MIN_PER_SIDE - len(s.scores) for n, s in sides.items() if len(s.scores) < MIN_PER_SIDE
    }
    for name, side in sides.items():
        print(describe(name, side))
    for name, need in short.items():
        print(
            f"erro: faltam {need} arquivo(s) em {name} (mínimo {MIN_PER_SIDE} por pasta)",
            file=sys.stderr,
        )
    return 1 if short else 0


def compare(corpus: Path, sides: dict[str, Side]) -> int:
    if code := check(corpus, sides):
        return code
    human, ai = sides["human"].scores, sides["ai"].scores
    d = cohens_d(human, ai)
    if d is None:
        print(
            "erro: corpus degenerado: todos os arquivos de cada pasta têm o mesmo score "
            "(cópias do mesmo texto?). Sem variância não há d nem AUC que valham.",
            file=sys.stderr,
        )
        return 1
    label, note = verdict(d, len(human), len(ai))
    low, high = interval(d, len(human), len(ai))
    means = [
        f"{name} {statistics.fmean(s):.3f} (dp {statistics.stdev(s):.3f})"
        for name, s in (("human", human), ("ai", ai))
    ]
    print("médias: " + " · ".join(means))
    print(f"Cohen's d: {d:+.3f} (ai menos human, desvio agrupado)")
    print(f"IC 95% de d: [{low:+.2f}, {high:+.2f}]")
    print(f"AUC: {auc(human, ai):.2f} (chance de um ai pontuar acima de um human; 0.50 = acaso)")
    print(f"recomendação: {label}\n{note}")
    if min(len(human), len(ai)) < STABLE_PER_SIDE:
        print(f"aviso: com menos de {STABLE_PER_SIDE} arquivos por pasta o intervalo é largo.")
    print(DISCLAIMER)
    return 0


def init(corpus: Path) -> int:
    if inside_repo(corpus):
        print(f"erro: o corpus não é versionado; use uma pasta fora de {ROOT}", file=sys.stderr)
        return 1
    try:
        for side in SIDES:
            (corpus / side).mkdir(parents=True, exist_ok=True)
        # "x": fail if it exists, so a README the user wrote (or a dangling link) is never touched
        with (
            contextlib.suppress(FileExistsError),
            (corpus / "README.md").open("x", encoding="utf-8") as handle,
        ):
            handle.write(README)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        print(f"erro: não foi possível criar {printable(str(corpus))}: {reason}", file=sys.stderr)
        return 1
    print(f"corpus pronto em {printable(str(corpus))}")
    print(f"Coloque os textos em human/ e ai/ e rode: build_corpus.py check --dir {quoted(corpus)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("init", "check", "compare"))
    parser.add_argument("--dir", type=Path, help="corpus folder (default: <temp>/corpus)")
    args = parser.parse_args(argv)
    utf8_streams()
    corpus: Path = args.dir or default_dir()
    if args.command == "init":
        return init(corpus)
    missing = [side for side in SIDES if not (corpus / side).is_dir()]
    if missing:
        print(
            f"erro: faltam as pastas {', '.join(missing)} em {printable(str(corpus))}; "
            f"rode: build_corpus.py init --dir {quoted(corpus)}",
            file=sys.stderr,
        )
        return 1
    sides = {side: measure(corpus, side) for side in SIDES}
    return (check if args.command == "check" else compare)(corpus, sides)


if __name__ == "__main__":
    sys.exit(main())
