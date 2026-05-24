"""
Encoding Property Cascade Helpers

Shared 3-level cascade functions used by both stacked.py and layers.py.
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import MarkSpec


def resolve_mark(
    layer_mark: MarkSpec | None,
    entry_mark: MarkSpec | None,
    top_level_mark: MarkSpec | None,
    measure_name: str,
) -> MarkSpec:
    """
    Resolve mark via 3-level cascade: layer > entry > top-level.
    Raises ValueError if all three are None.

    For 2-level callers (stacked.py), pass layer_mark=None.
    """
    if layer_mark is not None:
        return layer_mark
    if entry_mark is not None:
        return entry_mark
    if top_level_mark is not None:
        return top_level_mark
    raise ValueError(f"No mark defined for measure '{measure_name}'")


def resolve_property(
    layer_value: Any,
    entry_value: Any,
    top_level_value: Any,
) -> Any:
    """
    Generic 3-level cascade: layer > entry > top-level.
    Returns first non-None, or None if all None.

    Used for color and size. NOT used for:
      - mark (which raises on all-None)
      - detail (which has explicit-null semantics via model_fields_set)
      - opacity (which does not cascade)

    For 2-level callers (stacked.py), pass layer_value=None.
    """
    if layer_value is not None:
        return layer_value
    if entry_value is not None:
        return entry_value
    return top_level_value
