"""
Chart Field Extraction

Walks a ChartSpec to extract every referenced field name. This is pure domain
logic — no data-source dependency. Used by both the Cube query builder and the
DuckDB adapter to know which fields the chart actually uses.
"""

from __future__ import annotations

import warnings

from shelves.schema.chart_schema import (
    HEX_COLOR_RE,
    ChartSpec,
    ColorFieldMapping,
    FieldSort,
    MeasureEntry,
    RowColumnFacet,
    WrapFacet,
)


def collect_chart_fields(spec: ChartSpec) -> set[str]:
    """
    Extract the set of field names a chart actually references.

    Walks ALL field-bearing properties of ChartSpec:
      - rows, cols (string or MeasureEntry list — including layer entries)
      - color (string field or ColorFieldMapping)
      - detail
      - size (when it's a string field name, not a numeric literal)
      - tooltip (list of strings or TooltipField objects)
      - facet (RowColumnFacet.row, RowColumnFacet.column, WrapFacet.field)
      - sort (FieldSort.field — but NOT AxisSort, which references an axis not a field)
      - filters (ShelfFilter.field)
      - kpi (KPIBlock.value, KPIComparison.field)

    Tooltip disaggregation warning:
      Tooltip fields not already referenced by other chart properties are still
      collected (the user asked for them), but a warnings.warn() is emitted for
      each one explaining that including it will disaggregate the data — i.e., it
      behaves as if the field were added to 'detail'.

    Returns the set of field names.
    """
    fields: set[str] = set()

    def _add_shelf(shelf: str | list[MeasureEntry] | None) -> None:
        if shelf is None:
            return
        if isinstance(shelf, str):
            fields.add(shelf)
        else:
            for entry in shelf:
                fields.add(entry.measure)
                if (
                    entry.color
                    and isinstance(entry.color, str)
                    and not HEX_COLOR_RE.match(entry.color)
                ):
                    fields.add(entry.color)
                elif isinstance(entry.color, ColorFieldMapping):
                    fields.add(entry.color.field)
                if entry.detail:
                    fields.add(entry.detail)
                if isinstance(entry.size, str):
                    fields.add(entry.size)
                if entry.layer:
                    for layer in entry.layer:
                        fields.add(layer.measure)
                        if (
                            layer.color
                            and isinstance(layer.color, str)
                            and not HEX_COLOR_RE.match(layer.color)
                        ):
                            fields.add(layer.color)
                        elif isinstance(layer.color, ColorFieldMapping):
                            fields.add(layer.color.field)
                        if layer.detail:
                            fields.add(layer.detail)
                        if isinstance(layer.size, str):
                            fields.add(layer.size)

    _add_shelf(spec.rows)
    _add_shelf(spec.cols)

    if spec.color:
        if isinstance(spec.color, str) and not HEX_COLOR_RE.match(spec.color):
            fields.add(spec.color)
        elif isinstance(spec.color, ColorFieldMapping):
            fields.add(spec.color.field)

    if spec.detail:
        fields.add(spec.detail)

    if isinstance(spec.size, str):
        fields.add(spec.size)

    if spec.facet:
        if isinstance(spec.facet, WrapFacet):
            fields.add(spec.facet.field)
        elif isinstance(spec.facet, RowColumnFacet):
            if spec.facet.row:
                fields.add(spec.facet.row)
            if spec.facet.column:
                fields.add(spec.facet.column)

    if spec.sort and isinstance(spec.sort, FieldSort):
        fields.add(spec.sort.field)

    if spec.filters:
        for f in spec.filters:
            fields.add(f.field)

    if spec.kpi:
        fields.add(spec.kpi.value)
        if spec.kpi.comparison:
            fields.add(spec.kpi.comparison.field)

    if spec.tooltip:
        pre_tooltip_fields = set(fields)
        for t in spec.tooltip:
            field_name = t if isinstance(t, str) else t.field
            if field_name not in pre_tooltip_fields:
                warnings.warn(
                    f"Tooltip field '{field_name}' is not referenced by any other "
                    f"chart property (rows, cols, color, detail, facet, etc.). "
                    f"Including it in the data query will disaggregate the data "
                    f"— it behaves as if '{field_name}' were added to 'detail'.",
                    stacklevel=2,
                )
            fields.add(field_name)

    return fields
