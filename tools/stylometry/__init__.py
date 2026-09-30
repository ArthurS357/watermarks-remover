"""Deterministic stylometric signals for prose and source code.

No model and no network: every signal is a regex, an ``ast`` walk or a count over the
document structure. The catalogue, weights and thresholds are documented in ``docs/TODO.md``
(round R10) and are deliberately uncalibrated against a corpus. This is a personal-use review
aid: a score is a prompt to reread your own text, not a verdict about anyone.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import NamedTuple

DISCLAIMER = (
    "Score é indicativo, não veredito. Falsos positivos esperados em texto técnico "
    "disciplinado e em código com convenções fortes. Uso pessoal — não use para acusar "
    "terceiros."
)

SEVERITIES = ("low", "medium", "high")
CONFIDENCES = ("low", "medium", "high")

# Score = 1 - exp(-total / SATURATION), total = sum(weight[category] * strength[worst severity
# of each signal]). A smooth saturation, not a probability and not a clipped sum: a clipped sum
# hits 1.0 on a heavily loaded file and then cannot see a partial rewrite (delta 0). Four medium
# structural signals score ~0.48. See docs/TODO.md (R10) for the rationale.
STRENGTH = {"low": 0.33, "medium": 0.66, "high": 1.0}
WEIGHT = {"structural": 2.0, "lexical": 1.0, "metric": 0.5}
SATURATION = 8.0

# A hostile or generated file can match a pattern tens of thousands of times; the report keeps
# this many locations per signal and the total in ``Signal.value``.
MAX_OCCURRENCES = 100

CATEGORY: dict[str, str] = {
    **dict.fromkeys(
        (
            "em_dash_density",
            "not_just_but",
            "delve_family",
            "worth_noting",
            "fast_paced_world",
            "on_the_other_hand_cascade",
            "hedge_double",
            "obvious_comment",
            "warning_comment",
            "todo_comment_style",
        ),
        "lexical",
    ),
    **dict.fromkeys(
        (
            "bold_lead_in",
            "tricolon_uniform",
            "template_heading",
            "emoji_heading",
            "meta_commentary",
            "paragraph_uniformity",
            "sentence_uniformity",
            "declarative_close",
            "here_is_why",
            "comparison_table_symmetry",
            "docstring_echoes_name",
            "type_hint_on_trivial_local",
            "generic_try_except",
            "excessive_params",
            "over_descriptive_name",
            "complete_main_boilerplate",
            "future_annotations_on_314",
            "match_where_if_fits",
            "as_const_everywhere",
            "optional_chaining_overuse",
            "jsdoc_on_trivial_type",
            "explicit_return_types_on_arrow",
        ),
        "structural",
    ),
    **dict.fromkeys(
        (
            "type_token_ratio",
            "sentence_length_stddev",
            "paragraph_length_stddev",
            "em_dash_to_comma_ratio",
            "comment_density",
        ),
        "metric",
    ),
}


class Signal(NamedTuple):
    """One finding. Occurrence signals repeat ``value`` (the file total) on every hit and
    carry that hit's ``line``; document-level metrics have ``line=None``."""

    name: str
    value: float
    severity: str
    line: int | None
    snippet: str


class Hit(NamedTuple):
    line: int
    snippet: str
    pos: int = 0


class Analysis(NamedTuple):
    signals: list[Signal]
    score: float
    confidence: str


def by_count(
    n: float, low: float | None = None, medium: float | None = None, high: float | None = None
) -> str | None:
    """Highest severity whose threshold ``n`` reaches; ``None`` below every threshold."""
    for severity, threshold in (("high", high), ("medium", medium), ("low", low)):
        if threshold is not None and n >= threshold:
            return severity
    return None


def by_below(
    x: float, low: float | None = None, medium: float | None = None, high: float | None = None
) -> str | None:
    """Like :func:`by_count` for metrics where a *smaller* value is the suspicious one."""
    for severity, threshold in (("high", high), ("medium", medium), ("low", low)):
        if threshold is not None and x < threshold:
            return severity
    return None


def occurrences(name: str, hits: Sequence[Hit], severity: str | None) -> list[Signal]:
    """One ``Signal`` per hit, all sharing the severity decided from the total count. Only the
    first ``MAX_OCCURRENCES`` are kept; ``value`` still carries the real total."""
    if severity is None:
        return []
    return [Signal(name, len(hits), severity, h.line, h.snippet) for h in hits[:MAX_OCCURRENCES]]


def score_signals(signals: Iterable[Signal]) -> float:
    worst: dict[str, int] = {}
    for s in signals:
        worst[s.name] = max(worst.get(s.name, 0), SEVERITIES.index(s.severity))
    total = sum(WEIGHT[CATEGORY[n]] * STRENGTH[SEVERITIES[i]] for n, i in worst.items())
    return round(1 - math.exp(-total / SATURATION), 4)


def cap_confidence(confidence: str, ceiling: str) -> str:
    return min(confidence, ceiling, key=CONFIDENCES.index)
