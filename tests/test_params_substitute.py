"""
Parameter Substitution Tests (SHE-89)

The position-aware `$ref` substitution pass that runs BEFORE Pydantic parsing.
Covers the reference grammar, the allow-list of legal positions, null-filter
pruning, and the diagnostic contract (collected, never raised inside the walk).
"""

from __future__ import annotations

import re

import pytest
import yaml

from shelves.params.loader import load_parameters
from shelves.params.positions import classify
from shelves.params.refs import interp_refs, unescape_dollars, whole_ref
from shelves.params.substitute import ParameterSet, substitute_parameters
from shelves.schema.chart_schema import parse_chart
from tests.conftest import load_yaml, params_fixture


def _params(**overrides) -> ParameterSet:
    return ParameterSet(load_parameters(params_fixture()), overrides=overrides or None)


def _sub(yaml_text: str, params: ParameterSet | None = None):
    return substitute_parameters(yaml.safe_load(yaml_text), params or _params())


# ─── refs.py ──────────────────────────────────────────────────────


class TestWholeRef:
    def test_exact_ref(self):
        assert whole_ref("$metric") == "metric"

    def test_underscore_and_digits(self):
        assert whole_ref("$top_n2") == "top_n2"

    def test_embedded_ref_is_not_whole(self):
        assert whole_ref("Top $metric") is None

    def test_escaped_dollar_is_not_a_ref(self):
        assert whole_ref("$$metric") is None

    def test_interpolation_form_is_not_a_whole_ref(self):
        assert whole_ref("${metric}") is None

    def test_non_string(self):
        assert whole_ref(10) is None
        assert whole_ref(None) is None

    def test_leading_digit_rejected(self):
        assert whole_ref("$1metric") is None


class TestInterpRefs:
    def test_single(self):
        assert interp_refs("Revenue — ${region}") == ["region"]

    def test_multiple_in_order_with_repeats(self):
        assert interp_refs("${a} then ${b} then ${a}") == ["a", "b", "a"]

    def test_none(self):
        assert interp_refs("no refs here") == []

    def test_bare_dollar_not_matched(self):
        assert interp_refs("Top $region") == []


class TestUnescapeDollars:
    def test_double_becomes_single(self):
        assert unescape_dollars("Costs $$100") == "Costs $100"

    def test_untouched_without_escape(self):
        assert unescape_dollars("plain text") == "plain text"

    def test_escaped_ref_survives_as_literal(self):
        assert unescape_dollars("$$metric") == "$metric"


# ─── positions.py ─────────────────────────────────────────────────


class TestClassify:
    @pytest.mark.parametrize(
        "path",
        [
            "rows",
            "cols",
            "rows[0].measure",
            "rows[2].layer[1].measure",
            "color",
            "color.field",
            "detail",
            "size",
            "facet.row",
            "sort.field",
            "tooltip[0]",
            "label.field",
            "kpi.value",
            "filters[0].field",
        ],
    )
    def test_field_slots(self, path):
        assert classify(path) == "field"

    @pytest.mark.parametrize(
        "path",
        ["filters[0].value", "filters[1].values[2]", "filters[0].range[1]"],
    )
    def test_literal_slots(self, path):
        assert classify(path) == "literal"

    @pytest.mark.parametrize(
        "path",
        ["sheet", "description", "axis.x.title", "axis.y.title", "kpi.title"],
    )
    def test_interpolation_slots(self, path):
        assert classify(path) == "interpolation"

    @pytest.mark.parametrize(
        "path",
        [
            "marks",
            "marks.type",
            "data",
            "version",
            "label.color",
            "label.size",
            "axis.x.grid",
            "facet.columns",
            "sort.order",
            "kpi.format",
            "filters[0].values",  # the list itself, not an element
            "rows[0].opacity",
            "unknown_future_field",
        ],
    )
    def test_forbidden_positions(self, path):
        """The allow-list is exhaustive — unlisted paths are forbidden."""
        assert classify(path) is None


# ─── ParameterSet ─────────────────────────────────────────────────


class TestParameterSet:
    def test_defaults_populate_values(self):
        ps = _params()
        assert ps.values["metric"] == "revenue"
        assert ps.values["top_n"] == 10
        assert ps.values["as_of"] is None

    def test_override_applies(self):
        ps = _params(metric="cost")
        assert ps.values["metric"] == "cost"

    def test_unknown_override_raises(self):
        with pytest.raises(ValueError, match="not a declared parameter"):
            _params(nope="x")

    def test_override_outside_literal_values_raises(self):
        with pytest.raises(ValueError, match="is not in values"):
            _params(status="archived")

    def test_override_outside_range_raises(self):
        with pytest.raises(ValueError, match="is outside the range"):
            _params(top_n=999)

    def test_empty_set(self):
        ps = ParameterSet.empty()
        assert ps.declared == {}
        assert ps.values == {}


# ─── Field slots ──────────────────────────────────────────────────


class TestFieldSlots:
    def test_field_param_fills_rows(self):
        result = _sub(load_yaml("param_field_swap.yaml"))
        assert result.diagnostics == []
        assert result.data == {
            "sheet": "Metric by Country",
            "data": "orders",
            "cols": "country",
            "rows": "revenue",
            "marks": "bar",
        }

    def test_swap_equals_handwritten(self):
        swapped = parse_chart(
            load_yaml("param_field_swap.yaml"),
            parameters=_params(metric="cost"),
        )
        handwritten = parse_chart(
            """
sheet: "Metric by Country"
data: orders
cols: country
rows: cost
marks: bar
"""
        )
        assert swapped.model_dump() == handwritten.model_dump()


# ─── Literal slots ────────────────────────────────────────────────


class TestLiteralSlots:
    def test_string_param_in_filter_eq(self):
        result = _sub(load_yaml("param_filter_value.yaml"))
        assert result.diagnostics == []
        assert result.data["filters"] == [{"field": "region", "operator": "eq", "value": "EMEA"}]

    def test_number_params_in_range(self):
        result = _sub(load_yaml("param_range_bounds.yaml"))
        assert result.diagnostics == []
        assert result.data["filters"] == [
            {"field": "margin_pct", "operator": "between", "range": [10, 90]}
        ]

    def test_range_values_keep_numeric_type(self):
        result = _sub(load_yaml("param_range_bounds.yaml"))
        lo, hi = result.data["filters"][0]["range"]
        assert isinstance(lo, int) and not isinstance(lo, str)
        assert isinstance(hi, int) and not isinstance(hi, str)

    def test_ref_in_list_element(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: revenue
marks: bar
filters:
  - field: region
    operator: in
    values:
      - $region
      - APAC
""")
        assert result.diagnostics == []
        assert result.data["filters"][0]["values"] == ["EMEA", "APAC"]


# ─── Interpolation ────────────────────────────────────────────────


class TestInterpolation:
    def test_sheet_and_description(self):
        result = _sub(load_yaml("param_title_interpolation.yaml"))
        assert result.diagnostics == []
        assert result.data["sheet"] == "Revenue — EMEA"
        assert result.data["description"] == "Filtered to EMEA, top 10"

    def test_number_renders_without_decimal(self):
        result = _sub("""
sheet: "Top ${top_n}"
data: orders
cols: country
rows: revenue
marks: bar
""")
        assert result.data["sheet"] == "Top 10"

    def test_null_renders_as_empty_string(self):
        result = _sub("""
sheet: "Region ${maybe_region}"
data: orders
cols: country
rows: revenue
marks: bar
""")
        assert result.data["sheet"] == "Region "

    def test_bare_ref_with_surrounding_text_is_left_alone(self):
        """Bare $name is whole-scalar only — keeps `$` usable in prose."""
        result = _sub("""
sheet: "Top $top_n"
data: orders
cols: country
rows: revenue
marks: bar
""")
        assert result.diagnostics == []
        assert result.data["sheet"] == "Top $top_n"

    def test_escaped_dollar(self):
        result = _sub("""
sheet: "Costs $$100"
data: orders
cols: country
rows: revenue
marks: bar
""")
        assert result.data["sheet"] == "Costs $100"


# ─── Null semantics ───────────────────────────────────────────────


class TestNullSemantics:
    def test_null_drops_filter(self):
        result = _sub(load_yaml("param_null_default.yaml"))
        assert result.diagnostics == []
        assert result.data["filters"] == [
            {"field": "country", "operator": "in", "values": ["US", "UK"]}
        ]

    def test_all_filters_dropped(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: revenue
marks: bar
filters:
  - field: region
    operator: eq
    value: $maybe_region
""")
        assert result.data["filters"] == []

    def test_null_filter_chart_still_parses(self):
        """The pruning exists so ShelfFilter's validator never sees a None."""
        spec = parse_chart(load_yaml("param_null_default.yaml"), parameters=_params())
        assert spec.filters is not None
        assert len(spec.filters) == 1
        assert spec.filters[0].field == "country"


# ─── No-op / backward compatibility ───────────────────────────────


class TestNoOp:
    def test_no_params_no_refs_returns_input_uncopied(self):
        raw = yaml.safe_load(load_yaml("simple_bar.yaml"))
        result = substitute_parameters(raw, ParameterSet.empty())
        assert result.data is raw
        assert result.diagnostics == []

    def test_existing_chart_parses_without_parameters_argument(self):
        spec = parse_chart(load_yaml("simple_bar.yaml"))
        assert spec.rows == "revenue"

    def test_unused_parameter_produces_no_diagnostic(self):
        """No dead-parameter lint — parameters are project-level."""
        result = _sub(load_yaml("simple_bar.yaml"))
        assert result.diagnostics == []


# ─── Errors ───────────────────────────────────────────────────────


class TestSubstitutionErrors:
    def test_e11_type_mismatch_at_field_slot(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: $top_n
marks: bar
""")
        assert [d.code for d in result.errors] == ["type_mismatch"]
        assert "cannot fill a field slot" in result.errors[0].message

    def test_e12_field_param_in_filter_value(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: revenue
marks: bar
filters:
  - field: region
    operator: eq
    value: $metric
""")
        assert [d.code for d in result.errors] == ["type_mismatch"]
        assert "cannot fill a filter value" in result.errors[0].message

    def test_e13_forbidden_position_mark(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: revenue
marks: $metric
""")
        assert [d.code for d in result.errors] == ["forbidden_position"]
        assert result.errors[0].path == "marks"

    def test_e14_forbidden_position_label_style(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: revenue
marks: bar
label:
  field: revenue
  color: $region
""")
        assert [d.code for d in result.errors] == ["forbidden_position"]
        assert result.errors[0].path == "label.color"

    def test_field_slot_rejects_interpolation(self):
        """A field slot needs an exact field name, not a rendered string."""
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: "${metric}"
marks: bar
""")
        assert [d.code for d in result.errors] == ["forbidden_position"]

    def test_whole_list_ref_is_forbidden(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: revenue
marks: bar
filters:
  - field: region
    operator: in
    values: $region
""")
        assert [d.code for d in result.errors] == ["forbidden_position"]

    def test_size_slot_rejects_number_param(self):
        result = _sub("""
sheet: "T"
data: orders
cols: country
rows: revenue
marks: circle
size: $top_n
""")
        assert [d.code for d in result.errors] == ["type_mismatch"]

    def test_e17_undeclared_ref_is_collected_not_raised(self):
        """The walk NEVER raises — a future template pass runs ahead of it."""
        result = substitute_parameters(
            yaml.safe_load("""
sheet: "T"
data: orders
cols: country
rows: $nope
marks: bar
"""),
            ParameterSet.empty(),
        )
        assert [d.code for d in result.errors] == ["undeclared_ref"]
        assert result.errors[0].name == "nope"
        assert result.data["rows"] == "$nope"

    def test_e17_parse_chart_raises(self):
        with pytest.raises(ValueError, match="not a declared parameter"):
            parse_chart("""
sheet: "T"
data: orders
cols: country
rows: $nope
marks: bar
""")

    def test_undeclared_ref_in_interpolation(self):
        result = _sub("""
sheet: "Hello ${nope}"
data: orders
cols: country
rows: revenue
marks: bar
""")
        assert [d.code for d in result.errors] == ["undeclared_ref"]

    def test_inline_parameters_block_rejected(self):
        with pytest.raises(ValueError, match=re.escape("models/parameters.yaml")):
            substitute_parameters(
                yaml.safe_load("""
sheet: "T"
data: orders
parameters:
  metric:
    type: string
    default: revenue
cols: country
rows: revenue
marks: bar
"""),
                ParameterSet.empty(),
            )

    def test_parse_chart_rejects_inline_parameters_block(self):
        with pytest.raises(ValueError, match=re.escape("models/parameters.yaml")):
            parse_chart("""
sheet: "T"
data: orders
parameters:
  metric:
    type: string
    default: revenue
cols: country
rows: revenue
marks: bar
""")
