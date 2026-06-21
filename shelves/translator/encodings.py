"""
Encoding Channel Builders

Shared helpers used by all pattern compilers (single, stacked, layers).

Public functions:
  build_field_encoding(field_ref, resolver) — base field + type + timeUnit
  build_encodings(spec, resolver)  — full encoding dict for single-measure charts
  build_color(color, resolver)     — color encoding from DSL color spec
  build_tooltip(tooltip, resolver) — tooltip encoding list
  build_detail(detail, resolver)   — detail encoding
  build_size(size, resolver)       — size encoding
"""

from __future__ import annotations

from typing import Any

from shelves.schema.chart_schema import (
    HEX_COLOR_RE,
    AxisChannelConfig,
    ChartSpec,
    ColorSpec,
    TooltipSpec,
)
from shelves.schema.field_types import FieldTypeResolver

# ─── Core field encoding helper ───────────────────────────────────


def build_field_encoding(field_ref: str, resolver: FieldTypeResolver) -> dict[str, Any]:
    """
    Build a field encoding dict from a field reference and resolver.

    Handles dot notation: resolves base field, type, timeUnit, and auto-format
    via the ModelResolver.

    Returns: {"field": "order_date", "type": "temporal", "timeUnit": "yearmonth"}
    """
    enc: dict[str, Any] = {
        "field": resolver.resolve_base_field(field_ref),
        "type": resolver.resolve(field_ref),
    }
    time_unit = resolver.resolve_time_unit(field_ref)
    if time_unit is not None:
        enc["timeUnit"] = time_unit
    return enc


# ─── Full encoding builder (single-measure charts only) ──────────


def build_encodings(spec: ChartSpec, resolver: FieldTypeResolver) -> dict[str, Any]:
    """Build the full encoding dict for a single-measure ChartSpec.

    Used by patterns/single.py. Multi-measure compilers use the
    individual helpers below instead.
    """
    enc: dict[str, Any] = {}

    # X (cols) — must be a string for single-measure path
    if spec.cols and isinstance(spec.cols, str):
        enc["x"] = build_field_encoding(spec.cols, resolver)
        _apply_channel_axis(enc["x"], spec.cols, spec.axis.x if spec.axis else None, resolver, "x")

    # Y (rows) — must be a string for single-measure path
    if spec.rows and isinstance(spec.rows, str):
        enc["y"] = build_field_encoding(spec.rows, resolver)
        _apply_channel_axis(enc["y"], spec.rows, spec.axis.y if spec.axis else None, resolver, "y")

    # Color — with legend title auto-injection
    if spec.color is not None:
        enc["color"] = build_color(spec.color, resolver)

    # Detail
    if spec.detail:
        enc["detail"] = build_detail(spec.detail, resolver)

    # Size
    if spec.size is not None:
        enc["size"] = build_size(spec.size, resolver)

    # Tooltip — with auto-labels and auto-formats
    if spec.tooltip:
        enc["tooltip"] = build_tooltip(spec.tooltip, resolver)

    return enc


# ─── Individual channel builders (public, reusable) ──────────────


def build_color(
    color: ColorSpec,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """Build a color encoding from a DSL color spec. Auto-injects legend title from model."""
    if isinstance(color, str) and HEX_COLOR_RE.match(color):
        return {"value": color}
    if isinstance(color, str):
        enc = build_field_encoding(color, resolver)
        # Auto-inject legend title from model label
        enc["legend"] = {"title": resolver.resolve_label(color)}
        return enc
    # ColorFieldMapping — use build_field_encoding for timeUnit support
    result = build_field_encoding(color.field, resolver)
    if color.type:
        result["type"] = color.type
    # Auto-inject legend title
    result["legend"] = {"title": resolver.resolve_label(color.field)}
    return result


def build_detail(
    detail: str,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """Build a detail encoding."""
    return build_field_encoding(detail, resolver)


def build_size(
    size: str | int | float,
    resolver: FieldTypeResolver,
) -> dict[str, Any]:
    """Build a size encoding."""
    if isinstance(size, (int, float)):
        return {"value": size}
    return build_field_encoding(size, resolver)


def build_tooltip(
    tooltip: TooltipSpec,
    resolver: FieldTypeResolver,
) -> list[dict[str, Any]]:
    """Build tooltip encoding list with auto-injected titles and formats from model."""
    result = []
    for item in tooltip:
        if isinstance(item, str):
            entry = build_field_encoding(item, resolver)
            # Auto-inject title from model label
            entry["title"] = resolver.resolve_label(item)
            # Auto-inject format from model
            fmt = resolver.resolve_format(item)
            if fmt is not None:
                entry["format"] = fmt
            result.append(entry)
        else:
            entry = build_field_encoding(item.field, resolver)
            # Auto-inject title from model label
            entry["title"] = resolver.resolve_label(item.field)
            # Explicit tooltip format overrides model format
            if item.format:
                entry["format"] = item.format
            else:
                fmt = resolver.resolve_format(item.field)
                if fmt is not None:
                    entry["format"] = fmt
            result.append(entry)
    return result


# ─── Private helpers ──────────────────────────────────────────────


def _apply_channel_axis(
    encoding_channel: dict[str, Any],
    field_ref: str,
    raw_cfg: bool | AxisChannelConfig | None,
    resolver: FieldTypeResolver,
    channel: str,
) -> None:
    """Resolve one axis channel: granular config, bool shorthand, or default.

    - raw_cfg is False             → encoding_channel["axis"] = None; skip auto-inject
    - raw_cfg is True or None      → run auto-inject with no overrides
    - raw_cfg is AxisChannelConfig → apply granular toggles, then auto-inject
    """
    # Whole-axis-off shorthand: drop the axis entirely, skip auto-injection.
    if raw_cfg is False:
        encoding_channel["axis"] = None
        return

    # True normalizes to "no config" (show with theme defaults); a config
    # object stays as-is for granular toggles.
    cfg = raw_cfg if isinstance(raw_cfg, AxisChannelConfig) else None

    # Granular toggles first, then auto-inject so the model format merges into
    # the same axis dict.
    _apply_axis_config(encoding_channel, cfg)
    _auto_inject_from_model(encoding_channel, field_ref, resolver, cfg, channel=channel)


def _apply_axis_config(
    encoding_channel: dict[str, Any],
    axis_cfg: AxisChannelConfig | None,
) -> None:
    """Merge a granular axis config (title + boolean toggles) into an encoding
    channel. Caller is responsible for the bool-shorthand case (axis off / on);
    this function only ever receives an AxisChannelConfig or None.

    Mutates encoding_channel in place. None → no-op.
    """
    if axis_cfg is None:
        return

    if axis_cfg.title:
        encoding_channel["title"] = axis_cfg.title

    axis_props: dict[str, Any] = {}
    if axis_cfg.format:
        axis_props["format"] = axis_cfg.format
    if axis_cfg.grid is not None:
        axis_props["grid"] = axis_cfg.grid
    if axis_cfg.ruler is not None:
        axis_props["domain"] = axis_cfg.ruler  # ruler → domain
    if axis_cfg.ticks is not None:
        axis_props["ticks"] = axis_cfg.ticks
    if axis_cfg.labels is not None:
        axis_props["labels"] = axis_cfg.labels

    if axis_props:
        encoding_channel["axis"] = axis_props


def _auto_inject_from_model(
    encoding_channel: dict[str, Any],
    field_ref: str,
    resolver: FieldTypeResolver,
    axis_cfg: Any | None,
    channel: str,
) -> None:
    """
    Auto-inject title and format from the model into an encoding channel dict.

    Injection rules (each skipped if chart spec already sets it):
      1. title ← resolver.resolve_label(field_ref)
         Skipped if axis_cfg.title is set.
      2. axis.format ← resolver.resolve_format(field_ref)
         Skipped if axis_cfg.format is set.
         (This is the existing _auto_inject_format logic.)

    Grid (and the other axis-line toggles) are NOT injected here — their
    defaults live in the theme (config.axisX / config.axisY). The ``channel``
    parameter documents which axis this is for callers' sake.

    Mutates encoding_channel in place.
    """
    # Step 1: Auto-inject title
    if axis_cfg is None or not axis_cfg.title:
        label = resolver.resolve_label(field_ref)
        encoding_channel["title"] = label

    # Step 2: Auto-inject format (existing logic from _auto_inject_format)
    if axis_cfg is None or not axis_cfg.format:
        model_format = resolver.resolve_format(field_ref)
        if model_format is not None:
            axis_props = encoding_channel.get("axis", {})
            axis_props["format"] = model_format
            encoding_channel["axis"] = axis_props
