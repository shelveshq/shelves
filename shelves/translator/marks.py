"""
Mark Resolver

Converts the DSL marks value into a Vega-Lite mark definition.

Input shapes (Phase 1):
  "bar"                                → "bar"
  MarkObject(type="line", style="dashed") → {"type": "line", "strokeDash": [6, 4]}
  MarkObject(type="line", point=True)     → {"type": "line", "point": True}

Phase 1b adds: list of marks for dual axis (handled in patterns/dual_axis.py)
"""

from __future__ import annotations

from typing import Any, Union

from shelves.schema.chart_schema import MarkObject, MarkType

DASH_PATTERNS: dict[str, list[int]] = {
    "dashed": [6, 4],
    "dotted": [2, 2],
}


def build_mark(marks: Union[MarkType, MarkObject]) -> str | dict[str, Any]:
    """Convert a DSL mark spec to a Vega-Lite mark value."""

    # String shorthand: "bar" → "bar"
    if isinstance(marks, str):
        return marks

    # MarkObject → build dict
    result: dict[str, Any] = {"type": marks.type}

    if marks.style and marks.style in DASH_PATTERNS:
        result["strokeDash"] = DASH_PATTERNS[marks.style]

    if marks.point is not None:
        result["point"] = marks.point

    if marks.opacity is not None:
        result["opacity"] = marks.opacity

    # If only `type` key, return string shorthand for cleaner output
    if len(result) == 1:
        return result["type"]

    return result
