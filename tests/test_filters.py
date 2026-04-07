"""
Filter Tests

Tests filter parsing (schema validation) and translation (Vega-Lite transform output).
All test expectations are derived from the DSL reference (docs/guide/dsl-reference.md),
not from implementation details.

DSL reference says:
- Filters apply as Vega-Lite `transform` entries. Multiple filters are AND-ed.
- Operators: eq, neq, gt, lt, gte, lte use `value` (scalar)
- Operators: in, not_in use `values` (list)
- Operator: between uses `range` (2-element list)
- Cross-field usage is strictly forbidden (e.g. `values` with `eq` operator)
"""

import pytest
from pydantic import ValidationError

from shelves.schema.chart_schema import parse_chart
from tests.conftest import MODELS_DIR
from shelves.translator.translate import translate_chart


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_YAML = """\
sheet: "Filter Test"
data: orders
cols: country
rows: revenue
marks: bar
"""


def _make_yaml(filters_block: str) -> str:
    return BASE_YAML + filters_block


def _compile(yaml_str: str) -> dict:
    spec = parse_chart(yaml_str)
    return translate_chart(spec, models_dir=MODELS_DIR)


# ===========================================================================
# Schema validation — valid filter specs
# ===========================================================================


class TestFilterSchemaValid:
    """Each operator form from the DSL reference should parse without error."""

    def test_eq_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: country
    operator: eq
    value: "US"
""")
        )
        assert len(spec.filters) == 1
        assert spec.filters[0].operator == "eq"
        assert spec.filters[0].value == "US"

    def test_neq_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: country
    operator: neq
    value: "Other"
""")
        )
        assert spec.filters[0].operator == "neq"

    def test_gt_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: revenue
    operator: gt
    value: 1000
""")
        )
        assert spec.filters[0].operator == "gt"
        assert spec.filters[0].value == 1000

    def test_lt_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: revenue
    operator: lt
    value: 5000
""")
        )
        assert spec.filters[0].operator == "lt"

    def test_gte_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: revenue
    operator: gte
    value: 1000
""")
        )
        assert spec.filters[0].operator == "gte"

    def test_lte_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: revenue
    operator: lte
    value: 5000
""")
        )
        assert spec.filters[0].operator == "lte"

    def test_in_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: country
    operator: in
    values: ["US", "UK", "DE"]
""")
        )
        assert spec.filters[0].operator == "in"
        assert spec.filters[0].values == ["US", "UK", "DE"]

    def test_not_in_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: country
    operator: not_in
    values: ["Other"]
""")
        )
        assert spec.filters[0].operator == "not_in"
        assert spec.filters[0].values == ["Other"]

    def test_between_filter(self):
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: revenue
    operator: between
    range: [1000, 5000]
""")
        )
        assert spec.filters[0].operator == "between"
        assert spec.filters[0].range == [1000, 5000]

    def test_multiple_filters(self):
        """Multiple filters should all be parsed — they are AND-ed at translation."""
        spec = parse_chart(
            _make_yaml("""
filters:
  - field: country
    operator: in
    values: ["US", "UK"]
  - field: revenue
    operator: gte
    value: 1000
  - field: revenue
    operator: lt
    value: 10000
""")
        )
        assert len(spec.filters) == 3


# ===========================================================================
# Schema validation — invalid filter specs
# ===========================================================================


class TestFilterSchemaInvalid:
    """DSL reference strictly enforces operator → value field rules."""

    def test_rejects_unknown_operator(self):
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: country
    operator: contains
    value: "US"
""")
            )

    def test_rejects_values_with_eq(self):
        """eq requires `value`, not `values`."""
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: country
    operator: eq
    values: ["US"]
""")
            )

    def test_rejects_value_with_in(self):
        """in requires `values`, not `value`."""
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: country
    operator: in
    value: "US"
""")
            )

    def test_rejects_value_with_not_in(self):
        """not_in requires `values`, not `value`."""
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: country
    operator: not_in
    value: "US"
""")
            )

    def test_rejects_range_with_eq(self):
        """eq requires `value`, not `range`."""
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: revenue
    operator: eq
    range: [1000, 5000]
""")
            )

    def test_rejects_value_with_between(self):
        """between requires `range`, not `value`."""
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: revenue
    operator: between
    value: 1000
""")
            )

    def test_rejects_values_with_between(self):
        """between requires `range`, not `values`."""
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: revenue
    operator: between
    values: [1000, 5000]
""")
            )

    def test_rejects_range_with_in(self):
        """in requires `values`, not `range`."""
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: country
    operator: in
    range: [1, 10]
""")
            )

    def test_rejects_missing_field(self):
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - operator: eq
    value: "US"
""")
            )

    def test_rejects_missing_operator(self):
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
filters:
  - field: country
    value: "US"
""")
            )


# ===========================================================================
# Translation — Vega-Lite transform output
# ===========================================================================


class TestFilterTranslation:
    """Filters should compile to Vega-Lite `transform` entries."""

    def test_eq_becomes_filter_transform(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: country
    operator: eq
    value: "US"
""")
        )
        transforms = vl.get("transform", [])
        assert len(transforms) >= 1
        # Should produce a filter transform that keeps only "US"
        filt = transforms[0]["filter"]
        assert filt["field"] == "country"
        assert filt["equal"] == "US"

    def test_neq_becomes_filter_transform(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: country
    operator: neq
    value: "Other"
""")
        )
        transforms = vl.get("transform", [])
        filt = transforms[0]["filter"]
        # neq → Vega-Lite wraps not around an equal transform
        assert filt["not"] and "equal" not in filt
        assert filt["not"]["field"] == "country"
        assert filt["not"]["equal"] == "Other"

    def test_gte_becomes_filter_transform(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: revenue
    operator: gte
    value: 1000
""")
        )
        transforms = vl.get("transform", [])
        filt = transforms[0]["filter"]
        assert filt["field"] == "revenue"
        assert filt["gte"] == 1000

    def test_gt_becomes_filter_transform(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: revenue
    operator: gt
    value: 500
""")
        )
        transforms = vl.get("transform", [])
        filt = transforms[0]["filter"]
        assert filt["field"] == "revenue"
        assert filt["gt"] == 500

    def test_lt_becomes_filter_transform(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: revenue
    operator: lt
    value: 5000
""")
        )
        transforms = vl.get("transform", [])
        filt = transforms[0]["filter"]
        assert filt["field"] == "revenue"
        assert filt["lt"] == 5000

    def test_lte_becomes_filter_transform(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: revenue
    operator: lte
    value: 5000
""")
        )
        transforms = vl.get("transform", [])
        filt = transforms[0]["filter"]
        assert filt["field"] == "revenue"
        assert filt["lte"] == 5000

    def test_in_becomes_oneof_filter(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: country
    operator: in
    values: ["US", "UK", "DE"]
""")
        )
        transforms = vl.get("transform", [])
        filt = transforms[0]["filter"]
        assert filt["field"] == "country"
        assert filt["oneOf"] == ["US", "UK", "DE"]

    def test_not_in_excludes_values(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: country
    operator: not_in
    values: ["Other"]
""")
        )
        transforms = vl.get("transform", [])
        assert len(transforms) >= 1
        filt = transforms[0]["filter"]
        # check the oneOf transform is wrapped in a "not" structure
        assert filt["not"] and "oneOf" not in filt
        # not_in should produce a negated oneOf or equivalent exclusion
        assert filt["not"]["field"] == "country"
        assert filt["not"]["oneOf"] == ["Other"]

    def test_between_becomes_range_filter(self):
        vl = _compile(
            _make_yaml("""
filters:
  - field: revenue
    operator: between
    range: [1000, 5000]
""")
        )
        transforms = vl.get("transform", [])
        filt = transforms[0]["filter"]
        assert filt["field"] == "revenue"
        assert filt["range"] == [1000, 5000]

    def test_multiple_filters_all_appear_in_transforms(self):
        """Multiple filters are AND-ed — each becomes a separate transform entry."""
        vl = _compile(
            _make_yaml("""
filters:
  - field: country
    operator: in
    values: ["US", "UK"]
  - field: revenue
    operator: gte
    value: 1000
""")
        )
        transforms = vl.get("transform", [])
        # At least 2 filter transforms
        filter_transforms = [t for t in transforms if "filter" in t]
        assert len(filter_transforms) >= 2

    def test_no_filters_means_no_transform(self):
        """A chart with no filters should have no transform key (or empty)."""
        vl = _compile(BASE_YAML)
        transforms = vl.get("transform", [])
        assert len(transforms) == 0
