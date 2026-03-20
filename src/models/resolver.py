"""
Model-Aware Field Resolver

Resolves field types, labels, format strings, time units, and sort defaults
from a loaded DataModel. Satisfies the FieldTypeResolver protocol.

Key feature: dot-notation field references (e.g. "order_date.month") where
the suffix is a temporal grain, not a sub-field. Dot notation is ONLY valid
for temporal dimensions — using it on measures, nominal dimensions, or formula
fields raises a ValueError.
"""

from __future__ import annotations

import re

from src.models.schema import (
    DataModel,
    MeasureDefinition,
    NominalDimensionDefinition,
    TemporalDimensionDefinition,
)
from src.schema.field_types import VegaLiteType

# Grain → Vega-Lite timeUnit mapping
GRAIN_TO_TIME_UNIT: dict[str, str] = {
    "day": "yearmonthdate",
    "week": "yearweek",
    "month": "yearmonth",
    "quarter": "yearquarter",
    "year": "year",
}


def _humanize_field_name(name: str) -> str:
    """
    Convert a snake_case field name to a human-readable label.
    Used as fallback for formula fields that have no model definition.

    'total_revenue' → 'Total Revenue'
    'arpu' → 'Arpu'
    """
    return re.sub(r"_", " ", name).title()


class ModelResolver:
    """
    Resolves field metadata from a DataModel manifest.

    Satisfies the FieldTypeResolver protocol via the resolve() method.

    Supports dot-notation field references for temporal grains:
      "order_date"       → uses defaultGrain from model
      "order_date.month" → explicit month grain

    Dot notation is ONLY valid for temporal dimensions. Using it on measures,
    nominal dimensions, or formula fields raises a ValueError.

    Constructor args:
        model: A loaded DataModel instance.
        formulas: Optional dict of formula field names. Formula fields
                  are treated as quantitative. Values are ignored for now
                  (future: formula expressions).
    """

    def __init__(
        self,
        model: DataModel,
        formulas: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        self._formulas = formulas or {}

    # ─── Private helpers ──────────────────────────────────────

    def _parse_field_ref(self, field_ref: str) -> tuple[str, str | None]:
        """
        Split a field reference into (base_field, grain_or_none).

        "revenue"          → ("revenue", None)
        "order_date"       → ("order_date", None)
        "order_date.month" → ("order_date", "month")

        Only splits on the FIRST dot. The grain suffix is only meaningful
        for temporal dimensions — _lookup validates this.
        """
        if "." in field_ref:
            base, grain = field_ref.split(".", 1)
            return base, grain
        return field_ref, None

    def _get_measure(self, name: str) -> MeasureDefinition | None:
        return self._model.measures.get(name)

    def _get_dimension(self, name: str):
        return self._model.dimensions.get(name)

    def _lookup(self, field_ref: str):
        """
        Look up a field ref, returning (definition, grain_or_none).

        Raises ValueError if:
          - The field is not found in the model and is not a formula.
          - Dot notation is used on a non-temporal field (measure, nominal dim,
            or formula). Dot notation is only valid for temporal dimensions.
        """
        base, grain = self._parse_field_ref(field_ref)

        measure = self._get_measure(base)
        if measure is not None:
            if grain is not None:
                raise ValueError(
                    f'Dot notation is not valid for measure "{base}". '
                    f'Grain suffixes (e.g. ".month") are only valid for temporal dimensions.'
                )
            return measure, grain

        dimension = self._get_dimension(base)
        if dimension is not None:
            if grain is not None and not isinstance(dimension, TemporalDimensionDefinition):
                raise ValueError(
                    f'Dot notation is not valid for {dimension.type} dimension "{base}". '
                    f'Grain suffixes (e.g. ".month") are only valid for temporal dimensions.'
                )
            if grain is not None and isinstance(dimension, TemporalDimensionDefinition):
                if grain not in dimension.grains:
                    raise ValueError(
                        f'Grain "{grain}" is not supported for temporal field "{base}". '
                        f"Available grains: {dimension.grains}"
                    )
            return dimension, grain

        if base in self._formulas:
            if grain is not None:
                raise ValueError(
                    f'Dot notation is not valid for formula field "{base}". '
                    f'Grain suffixes (e.g. ".month") are only valid for temporal dimensions.'
                )
            return None, grain  # formula: no definition object

        available_measures = sorted(self._model.measures.keys())
        available_dims = sorted(self._model.dimensions.keys())
        raise ValueError(
            f'Field "{base}" not found in model "{self._model.model}". '
            f"Available: measures={available_measures}, "
            f"dimensions={available_dims}"
        )

    # ─── Public API ───────────────────────────────────────────

    def resolve_type(self, field_ref: str) -> VegaLiteType:
        """
        Resolve a field reference to a Vega-Lite type.

        - Measures → "quantitative"
        - Formula fields → "quantitative"
        - Temporal dimensions (with or without grain) → "temporal"
        - Nominal dimensions → "nominal"
        - Ordinal dimensions → "ordinal"
        """
        defn, _grain = self._lookup(field_ref)

        if defn is None:
            # Formula field
            return "quantitative"

        if isinstance(defn, MeasureDefinition):
            return "quantitative"

        if isinstance(defn, TemporalDimensionDefinition):
            return "temporal"

        if isinstance(defn, NominalDimensionDefinition):
            return defn.type  # "nominal" or "ordinal"

        raise ValueError(f"Unexpected definition type for field: {field_ref}")

    def resolve(self, field_name: str) -> VegaLiteType:
        """
        Protocol-compatible alias for resolve_type.

        Satisfies the FieldTypeResolver protocol:
            def resolve(self, field_name: str) -> VegaLiteType
        """
        return self.resolve_type(field_name)

    def resolve_label(self, field_ref: str) -> str:
        """
        Resolve a field reference to a human-readable label.

        Returns the model's label for measures and dimensions.
        Falls back to _humanize_field_name for formula fields.
        """
        defn, _grain = self._lookup(field_ref)

        if defn is None:
            # Formula field
            base, _ = self._parse_field_ref(field_ref)
            return _humanize_field_name(base)

        return defn.label

    def resolve_format(self, field_ref: str) -> str | None:
        """
        Resolve a field reference to a D3 format string (or None).

        - Measures: returns measure.format (e.g. "$,.0f")
        - Temporal dimensions with grain: returns the per-grain format
          from the format map. Uses explicit grain if dot-notation,
          otherwise defaultGrain.
        - Nominal dimensions / formulas: returns None
        """
        defn, grain = self._lookup(field_ref)

        if defn is None:
            return None  # formula

        if isinstance(defn, MeasureDefinition):
            return defn.format

        if isinstance(defn, TemporalDimensionDefinition):
            if defn.format is None:
                return None
            effective_grain = grain if grain else defn.defaultGrain
            return defn.format.get(effective_grain)

        return None  # nominal

    def resolve_time_unit(self, field_ref: str) -> str | None:
        """
        Resolve a field reference to a Vega-Lite timeUnit (or None).

        Only temporal dimensions produce a timeUnit. Uses explicit grain
        from dot notation if present, otherwise defaultGrain.

        Grain → VL timeUnit mapping:
            day     → yearmonthdate
            week    → yearweek
            month   → yearmonth
            quarter → yearquarter
            year    → year
        """
        defn, grain = self._lookup(field_ref)

        if not isinstance(defn, TemporalDimensionDefinition):
            return None

        effective_grain = grain if grain else defn.defaultGrain
        return GRAIN_TO_TIME_UNIT.get(effective_grain)

    def resolve_base_field(self, field_ref: str) -> str:
        """
        Strip grain suffix from dot notation, returning the base field name.

        "order_date.month" → "order_date"
        "revenue"          → "revenue"
        """
        base, _ = self._parse_field_ref(field_ref)
        return base

    def resolve_default_sort(self, field_ref: str) -> str | None:
        """
        Resolve a field's defaultSort value (or None).

        Returns "ascending" or "descending" if the model defines a default,
        None otherwise.
        """
        defn, _grain = self._lookup(field_ref)

        if defn is None:
            return None  # formula

        if isinstance(defn, (MeasureDefinition, NominalDimensionDefinition)):
            return defn.defaultSort

        return None  # temporal dims don't have defaultSort

    def resolve_sort_order(self, field_ref: str) -> list[str] | None:
        """
        Resolve a nominal dimension's explicit sort order (or None).

        Only NominalDimensionDefinition has sortOrder.
        Returns None for measures, temporal dims, and formulas.
        """
        defn, _grain = self._lookup(field_ref)

        if isinstance(defn, NominalDimensionDefinition):
            return defn.sortOrder

        return None

    def is_measure(self, field_ref: str) -> bool:
        """True if the base field is a model measure or a formula."""
        base, _ = self._parse_field_ref(field_ref)
        return base in self._model.measures or base in self._formulas

    def is_dimension(self, field_ref: str) -> bool:
        """True if the base field is a model dimension."""
        base, _ = self._parse_field_ref(field_ref)
        return base in self._model.dimensions
