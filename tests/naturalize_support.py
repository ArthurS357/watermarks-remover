"""Shared helpers of the naturalizer tests: the fixtures, and the padding that opens each gate."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from stylometry import Analysis
from stylometry import naturalize as nat

CASES = ROOT / "tests" / "fixtures" / "stylometry" / "naturalize"


def read(case: str, name: str = "before.md") -> str:
    return (CASES / case / name).read_bytes().decode("utf-8")


def total(analysis: Analysis, name: str) -> float:
    """How many times the detector counts ``name`` (0 when it is quiet)."""
    return max((s.value for s in analysis.signals if s.name == name), default=0)


def names(analysis: Analysis) -> set[str]:
    return {s.name for s in analysis.signals}


def out(text: str, **kwargs) -> str:
    return nat.naturalize(text, **kwargs).text


# Three lead-ins without a dash open the bold_lead_in gate; three dashes open the dash gate.
BOLD_PAD = "- **Um**: a\n- **Dois**: b\n- **Três**: c\n"
DASH_PAD = "Um — dois. Três — quatro. Cinco — seis.\n\n"
# Opens the worth_noting, delve_family, hedge_double and dash gates at once, for the tests whose
# point is that protected text survives a run in which every transformation is live.
OPEN = DASH_PAD + "Vale notar que sim. We delve into it. Pode ser que talvez caia.\n\n"


def bold(line: str) -> str:
    # a blank line first: right after a list item the line would be a lazy continuation of it
    return out(BOLD_PAD + "\n" + line + "\n").splitlines()[4]


def dash(line: str) -> str:
    return out(DASH_PAD + line + "\n").splitlines()[2]


def probe(line: str, **kwargs) -> str:
    """One line through the naturalizer. Every signal except the two that need padding has a
    gate of one occurrence, so the line opens its own gate."""
    return out(line + "\n", **kwargs).rstrip("\n")


def kept(span: str, before: str | None = None) -> None:
    """The naturalizer rewrites the line around ``span`` and leaves ``span`` byte for byte."""
    line = before or f"Vale notar que {span} e {span} — fim."
    result = out(OPEN + line + "\n")
    assert result.count(span) == line.count(span)
    assert "Vale notar" not in result  # the line was worked on, so this is not a vacuous pass
