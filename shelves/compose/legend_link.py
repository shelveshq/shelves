"""
Legend → scale linking and in-sheet legend suppression (SHE-10).

Pure helpers consumed by compose_dashboard. Operates on already-compiled
Vega-Lite encoding dicts + a FieldTypeResolver per sheet. Knows nothing about
HTML or the layout tree, and surfaces warnings as a returned list of strings so
each caller (compose, studio) can decide how to present them.
"""

from __future__ import annotations

from shelves.schema.field_types import FieldTypeResolver
from shelves.schema.layout_schema import LegendComponent
from shelves.translator.layout_styles import LegendLink

# Channels whose single-view Vega scale name equals the channel name and which
# render a legend. `shape` is forward-compat: the chart DSL has no shape channel
# today, so it never appears in a compiled encoding.
LEGEND_CHANNELS: tuple[str, ...] = ("color", "size", "shape")


def legend_producing_channels(encoding: dict) -> list[str]:
    """Channels in `encoding` that render a legend: a LEGEND_CHANNELS entry whose
    value is a field encoding (`{"field": ...}`), not a constant (`{"value": ...}`).
    Preserves LEGEND_CHANNELS order."""
    return [
        ch
        for ch in LEGEND_CHANNELS
        if isinstance(encoding.get(ch), dict) and "field" in encoding[ch]
    ]


def find_legend_scale(field_base: str, encoding: dict, resolver: FieldTypeResolver) -> str | None:
    """Return the scale name (== channel name for single-view) that encodes
    `field_base`, or None if no legend channel encodes it. First match wins in
    LEGEND_CHANNELS order. Compares base fields on both sides so dot-notation
    grains match."""
    for ch in LEGEND_CHANNELS:
        enc = encoding.get(ch)
        if (
            isinstance(enc, dict)
            and "field" in enc
            and resolver.resolve_base_field(enc["field"]) == field_base
        ):
            return ch
    return None


def single_view_encoding(vl: dict, sheet_name: str, source: str) -> dict:
    """Return the top-level `encoding` dict of a single-view spec.

    Raises ValueError('... not supported yet ...') when `vl` is compound
    (layered/dual-axis/multi-measure/facet) — those have no top-level encoding,
    i.e. multiple scales per channel, which is out of scope."""
    enc = vl.get("encoding")
    if not isinstance(enc, dict):
        raise ValueError(
            f"Independent legends are not supported yet for sheet {sheet_name!r} "
            f"(source {source!r}): layered/multi-view charts have multiple "
            f"scales per channel."
        )
    return enc


def suppress_in_sheet_legend(encoding: dict, channel: str) -> None:
    """Patch `encoding[channel]["legend"] = None` (compile-then-patch). No-op if
    the channel isn't a field encoding. Mutates in place."""
    enc = encoding.get(channel)
    if isinstance(enc, dict):
        enc["legend"] = None


def resolve_legend_links(
    legends: list[LegendComponent],
    sheets: dict[str, str],  # sheet name -> chart link path
    chart_vls: dict[str, dict],  # sheet name -> compiled VL (MUTATED: suppression)
    resolvers: dict[str, FieldTypeResolver],  # sheet name -> resolver
) -> tuple[dict[tuple[str, str], LegendLink], list[str]]:
    """Resolve every legend to its sheet's scale, suppress in-sheet legends, and
    collect warnings.

    Returns (links, warnings):
      - links: {(legend.source, legend.field): LegendLink(sheet_id, scale)}
      - warnings: human-readable messages for legend-producing channels that have
        no linked legend element (caller decides how to surface them).

    Raises ValueError on: a source that matches no sheet; a field not encoded on
    any legend channel; a legend pointing at a compound/layered sheet.
    """
    # Step 1: invert sheets to link -> first sheet name (two sheets may share a
    # link; bind to the first by discovery order).
    link_to_sheet: dict[str, str] = {}
    for name, link in sheets.items():
        link_to_sheet.setdefault(link, name)

    # Step 2: resolve each legend.
    links: dict[tuple[str, str], LegendLink] = {}
    linked: dict[str, set[str]] = {}
    for legend in legends:
        name = link_to_sheet.get(legend.source)
        if name is None:
            raise ValueError(
                f"Legend references source {legend.source!r} but no sheet in the "
                f"dashboard links to it."
            )
        resolver = resolvers[name]
        enc = single_view_encoding(chart_vls[name], name, legend.source)
        base = resolver.resolve_base_field(legend.field)
        scale = find_legend_scale(base, enc, resolver)
        if scale is None:
            raise ValueError(
                f"Legend field {legend.field!r} is not encoded as a "
                f"color/size/shape channel on sheet {name!r} "
                f"(source {legend.source!r})."
            )
        # Title: explicit element override, else the field's model label (SHE-11).
        # An explicit `title: ""` is meaningful (suppress the heading), so only
        # fall back when title is unset (None) — not merely falsy.
        title = legend.title if legend.title is not None else resolver.resolve_label(legend.field)
        links[(legend.source, legend.field)] = LegendLink(
            sheet_id=f"sheet-{name}", scale=scale, title=title
        )
        linked.setdefault(name, set()).add(scale)

    # Step 3: ALWAYS-suppress + warn over every single-view sheet.
    warnings_out: list[str] = []
    for name, vl in chart_vls.items():
        enc = vl.get("encoding")
        if not isinstance(enc, dict):
            continue  # compound: out of scope
        for channel in legend_producing_channels(enc):
            suppress_in_sheet_legend(enc, channel)
            if channel not in linked.get(name, set()):
                warnings_out.append(
                    f"Sheet {name!r} has a legend-producing {channel!r} encoding "
                    f"but no dashboard legend links to it; its in-sheet legend is "
                    f"suppressed."
                )
    return links, warnings_out
