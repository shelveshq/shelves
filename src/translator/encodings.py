"""
Encoding Channel Builders

Shared helpers used by all pattern compilers (single, stacked, layers).

Public functions:
  build_encodings(spec, resolver)  — full encoding dict for single-measure charts
  build_color(color, resolver)     — color encoding from DSL color spec
  build_tooltip(tooltip, resolver) — tooltip encoding list
  build_detail(detail, resolver)   — detail encoding
  build_size(size, resolver)       — size encoding
"""

from __future__ import annotations

from typing import Any, Union

from src.schema.chart_schema import (
    ChartSpec,
    ColorFieldMapping,
    ColorSpec,
    TooltipField,
    TooltipSpec,
    HEX_COLOR_RE,
)
from src.schema.field_types import DataBlockResolver


# ─── Full encoding builder (single-measure charts only) ──────────

def build_encodings(spec: ChartSpec, resolver: DataBlockResolver) -> dict[str, Any]:
    """Build the full encoding dict for a single-measure ChartSpec.

    Used by patterns/single.py. Multi-measure compilers use the
    individual helpers below instead.
    """
    enc: dict[str, Any] = {}

    # X (cols) — must be a string for single-measure path
    if spec.cols and isinstance(spec.cols, str):
        enc["x"] = {
            "field": spec.cols,
            "type": resolver.resolve(spec.cols),
        }
        _apply_axis_config(enc["x"], spec.axis.x if spec.axis else None)

    # Y (rows) — must be a string for single-measure path
    if spec.rows and isinstance(spec.rows, str):
        enc["y"] = {
            "field": spec.rows,
            "type": resolver.resolve(spec.rows),
        }
        _apply_axis_config(enc["y"], spec.axis.y if spec.axis else None)

    # Color
    if spec.color is not None:
        enc["color"] = build_color(spec.color, resolver)

    # Detail
    if spec.detail:
        enc["detail"] = build_detail(spec.detail, resolver)

    # Size
    if spec.size is not None:
        enc["size"] = build_size(spec.size, resolver)

    # Tooltip
    if spec.tooltip:
        enc["tooltip"] = build_tooltip(spec.tooltip, resolver)

    return enc


# ─── Individual channel builders (public, reusable) ──────────────

def build_color(
    color: ColorSpec,
    resolver: DataBlockResolver,
) -> dict[str, Any]:
    """Build a color encoding from a DSL color spec."""
    if isinstance(color, str) and HEX_COLOR_RE.match(color):
        return {"value": color}
    if isinstance(color, str):
        return {"field": color, "type": resolver.resolve(color)}
    # ColorFieldMapping
    return {
        "field": color.field,
        "type": color.type or resolver.resolve(color.field),
    }


def build_detail(
    detail: str,
    resolver: DataBlockResolver,
) -> dict[str, Any]:
    """Build a detail encoding."""
    return {"field": detail, "type": resolver.resolve(detail)}


def build_size(
    size: str | int | float,
    resolver: DataBlockResolver,
) -> dict[str, Any]:
    """Build a size encoding."""
    if isinstance(size, (int, float)):
        return {"value": size}
    return {"field": size, "type": resolver.resolve(size)}


def build_tooltip(
    tooltip: TooltipSpec,
    resolver: DataBlockResolver,
) -> list[dict[str, Any]]:
    """Build tooltip encoding list."""
    result = []
    for item in tooltip:
        if isinstance(item, str):
            result.append({"field": item, "type": resolver.resolve(item)})
        else:
            entry: dict[str, Any] = {
                "field": item.field,
                "type": resolver.resolve(item.field),
            }
            if item.format:
                entry["format"] = item.format
            result.append(entry)
    return result


# ─── Private helpers ──────────────────────────────────────────────

def _apply_axis_config(
    encoding_channel: dict[str, Any],
    axis_cfg: Any | None,
) -> None:
    """Merge axis config (title, format, grid) into an encoding channel."""
    if axis_cfg is None:
        return

    if axis_cfg.title:
        encoding_channel["title"] = axis_cfg.title

    axis_props: dict[str, Any] = {}
    if axis_cfg.format:
        axis_props["format"] = axis_cfg.format
    if axis_cfg.grid is not None:
        axis_props["grid"] = axis_cfg.grid

    if axis_props:
        encoding_channel["axis"] = axis_props
