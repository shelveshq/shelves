"""
Layer Compiler (Phase 1a — NOT YET IMPLEMENTED)

Handles MeasureEntry objects that have a `layer` property.
Called by stacked.py when it detects layers in any entry.

─── Two entry points ──────────────────────────────────────────

1. compile_layer_entry(entry, shared_enc, spec, resolver)
   Single MeasureEntry with layers → Vega-Lite `layer` array.
   Used when rows has exactly one entry with layers (no stacking).

2. compile_stacked_with_layers(spec, entries, shared_field, ...)
   Multiple MeasureEntry objects, some with layers → Vega-Lite
   `vconcat` where each child is either a simple spec or a layer spec.

─── Layer compilation logic ───────────────────────────────────

Given a MeasureEntry with layers:

  - measure: revenue
    mark: bar
    color: country
    layer:
      - measure: arpu
        mark: {type: line, style: dashed}
        color: "#666666"
    axis: independent

Produces:

  {
    "layer": [
      {
        "mark": "bar",
        "encoding": {
          "x": <shared>,
          "y": {"field": "revenue", "type": "quantitative"},
          "color": {"field": "country", "type": "nominal"}
        }
      },
      {
        "mark": {"type": "line", "strokeDash": [6, 4]},
        "encoding": {
          "x": <shared>,
          "y": {"field": "arpu", "type": "quantitative"},
          "color": {"value": "#666666"}
        }
      }
    ],
    "resolve": {"scale": {"y": "independent"}}
  }

─── Inheritance ───────────────────────────────────────────────

For each layer entry, resolve mark/color/detail/size by:
  1. Layer's own value (if set)
  2. Parent MeasureEntry's value (if set)
  3. Top-level spec value (marks/color/detail/size)
  4. Error if nothing resolves (mark is required somewhere)

─── Facet interaction ─────────────────────────────────────────

facet.py wraps whatever inner spec it receives. A layer spec
{layer: [...], resolve: {...}} wraps identically to a simple
{mark: ..., encoding: ...}. No changes needed in facet.py.
"""

from __future__ import annotations

from typing import Any


def compile_stacked_with_layers(
    spec, entries, shared_field, shared_axis, measure_axis, concat_key, resolver
) -> dict[str, Any]:
    """Phase 1a — not yet implemented."""
    raise NotImplementedError(
        "Layer compilation is Phase 1a. "
        "Multi-measure entries with `layer` are parsed but not yet compiled. "
        "Remove `layer` from your measure entries for Phase 1, or implement "
        "this function to enable Phase 1a."
    )


def compile_layer_entry(entry, shared_enc, spec, resolver) -> dict[str, Any]:
    """Phase 1a — not yet implemented."""
    raise NotImplementedError("Layer compilation is Phase 1a. See module docstring for design.")
