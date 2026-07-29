"""
Parameter Substitution in Model Manifest Calculations (SHE-94)

Tests that `${name}` references in measure and dimension `calculation` fields
are substituted with resolved parameter values at query time, not at model
load time. DuckDB/file sources only — Cube sources raise if a calculation
contains a `${name}` reference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shelves.models.loader import clear_model_cache, load_model
from shelves.models.resolver import ModelResolver
from shelves.params.refs import INTERP_RE
from shelves.params.substitute import ParameterSet, substitute_calculation
from shelves.schema.chart_schema import parse_chart

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MODELS_DIR = FIXTURES_DIR / "models"
DATA_DIR = FIXTURES_DIR / "data"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def _ps(grain: str = "month", period: str = "year") -> ParameterSet:
    """Build a ParameterSet with grain + period params for testing."""
    from shelves.params.schema import ParametersBlock, StringParameter

    block: ParametersBlock = {
        "grain": StringParameter(
            type="string",
            default="month",
            label="Grain",
            values=["day", "week", "month", "quarter", "year"],
        ),
        "period": StringParameter(
            type="string",
            default="year",
            label="Period",
            values=["month", "quarter", "year"],
        ),
    }
    overrides = {}
    if grain != "month":
        overrides["grain"] = grain
    if period != "year":
        overrides["period"] = period
    return ParameterSet(block, overrides=overrides or None)


# ─── INTERP_RE in calculations ─────────────────────────────────────


class TestCalcParamRegex:
    def test_braced_param(self):
        assert INTERP_RE.findall("DATE_TRUNC('${grain}', col)") == ["grain"]

    def test_multiple_occurrences(self):
        assert INTERP_RE.findall("${grain} and ${grain}") == ["grain", "grain"]

    def test_different_params(self):
        assert INTERP_RE.findall("${grain} and ${period}") == ["grain", "period"]

    def test_no_params(self):
        assert INTERP_RE.findall("{{ revenue }} - {{ cost }}") == []

    def test_underscore_and_digits(self):
        assert INTERP_RE.findall("${top_n2}") == ["top_n2"]

    def test_leading_digit_rejected(self):
        assert INTERP_RE.findall("${1metric}") == []

    def test_bare_dollar_not_matched(self):
        assert INTERP_RE.findall("$grain") == []


# ─── substitute_calculation ──────────────────────────────────────────


class TestSubstituteCalculation:
    def test_single_param(self):
        calc = (
            'SUM("revenue") FILTER (WHERE "Order Date" >= DATE_TRUNC(\'${grain}\', CURRENT_DATE))'
        )
        result = substitute_calculation(calc, _ps(), context="measure 'sales_current'")
        assert "DATE_TRUNC('month', CURRENT_DATE)" in result
        assert "${grain}" not in result

    def test_multiple_same_param(self):
        calc = "DATE_TRUNC('${grain}', col) - INTERVAL '1 ${grain}'"
        result = substitute_calculation(calc, _ps(), context="measure 'sales_prior'")
        assert result == "DATE_TRUNC('month', col) - INTERVAL '1 month'"

    def test_different_params(self):
        calc = "DATE_TRUNC('${grain}', col) / DATE_PART('${period}', CURRENT_DATE)"
        result = substitute_calculation(calc, _ps(), context="measure 'mixed'")
        assert "DATE_TRUNC('month', col)" in result
        assert "DATE_PART('year', CURRENT_DATE)" in result

    def test_no_dollar_fast_path(self):
        calc = "{{ revenue }} - {{ cost }}"
        result = substitute_calculation(calc, _ps(), context="measure 'profit'")
        assert result == calc

    def test_mixed_ref_and_param(self):
        calc = "{{ revenue }} / DATE_PART('${period}', CURRENT_DATE)"
        result = substitute_calculation(calc, _ps(), context="measure 'revenue_by_period'")
        assert "{{ revenue }}" in result
        assert "DATE_PART('year', CURRENT_DATE)" in result

    def test_override_param(self):
        calc = "DATE_TRUNC('${grain}', CURRENT_DATE)"
        result = substitute_calculation(calc, _ps(grain="week"), context="measure 'x'")
        assert result == "DATE_TRUNC('week', CURRENT_DATE)"

    def test_escaped_dollar(self):
        calc = "$${literal} stays"
        result = substitute_calculation(calc, _ps(), context="measure 'x'")
        assert result == "${literal} stays"

    def test_undeclared_param_raises(self):
        calc = "DATE_TRUNC('${undeclared}', col)"
        with pytest.raises(ValueError, match=r"undeclared.*not a declared parameter"):
            substitute_calculation(calc, _ps(), context="measure 'x'")

    def test_undeclared_message_lists_declared(self):
        calc = "DATE_TRUNC('${nope}', col)"
        with pytest.raises(ValueError, match="Declared:"):
            substitute_calculation(calc, _ps(), context="measure 'x'")

    def test_null_param_raises(self):
        from shelves.params.schema import ParametersBlock, StringParameter

        block: ParametersBlock = {
            "nullable": StringParameter(type="string", default=None, label="N"),
        }
        ps = ParameterSet(block)
        calc = "DATE_TRUNC('${nullable}', col)"
        with pytest.raises(ValueError, match="resolves to null"):
            substitute_calculation(calc, ps, context="measure 'x'")


# ─── SQL literal safety ──────────────────────────────────────────────


class TestSafeSqlLiteral:
    def test_string_value_passes_through(self):
        from shelves.params.schema import ParametersBlock, StringParameter

        block: ParametersBlock = {
            "region": StringParameter(type="string", default="EMEA", label="Region"),
        }
        ps = ParameterSet(block)
        result = substitute_calculation("WHERE region = '${region}'", ps, context="measure 'x'")
        assert result == "WHERE region = 'EMEA'"

    def test_string_with_single_quotes_escaped(self):
        from shelves.params.schema import ParametersBlock, StringParameter

        block: ParametersBlock = {
            "name": StringParameter(type="string", default="O'Brien", label="Name"),
        }
        ps = ParameterSet(block)
        result = substitute_calculation("WHERE name = '${name}'", ps, context="dim 'x'")
        assert result == "WHERE name = 'O''Brien'"

    def test_malicious_sql_is_escaped(self):
        from shelves.params.schema import ParametersBlock, StringParameter

        block: ParametersBlock = {
            "val": StringParameter(type="string", default="x", label="V"),
        }
        ps = ParameterSet(block, overrides={"val": "'; DROP TABLE t; --"})
        result = substitute_calculation("WHERE col = '${val}'", ps, context="measure 'x'")
        assert result == "WHERE col = '''; DROP TABLE t; --'"

    def test_number_value_not_quoted(self):
        from shelves.params.schema import NumberParameter, ParametersBlock

        block: ParametersBlock = {
            "top_n": NumberParameter(type="number", default=10, label="Top N"),
        }
        ps = ParameterSet(block)
        result = substitute_calculation("LIMIT ${top_n}", ps, context="measure 'x'")
        assert result == "LIMIT 10"

    def test_date_value_iso_format(self):
        import datetime as dt

        from shelves.params.schema import DateParameter, ParametersBlock

        block: ParametersBlock = {
            "as_of": DateParameter(type="date", default=dt.date(2025, 1, 15), label="As Of"),
        }
        ps = ParameterSet(block)
        result = substitute_calculation("WHERE d >= '${as_of}'", ps, context="measure 'x'")
        assert result == "WHERE d >= '2025-01-15'"


# ─── DuckDB adapter integration ─────────────────────────────────────


class TestDuckDBParameterizedCalc:
    @pytest.fixture
    def model(self):
        return load_model("parameterized_calc", models_dir=MODELS_DIR)

    @pytest.fixture
    def resolver(self, model):
        return ModelResolver(model)

    def test_resolve_measure_expressions_with_params(self, model):
        from shelves.data.duckdb_adapter import resolve_measure_expressions

        exprs = resolve_measure_expressions(model, parameters=_ps())
        assert "'month'" in exprs["sales_current"]
        assert "${grain}" not in exprs["sales_current"]

    def test_resolve_measure_multiple_params(self, model):
        from shelves.data.duckdb_adapter import resolve_measure_expressions

        exprs = resolve_measure_expressions(model, parameters=_ps())
        assert exprs["sales_prior"].count("month") == 2
        assert "${grain}" not in exprs["sales_prior"]

    def test_resolve_measure_mixed_ref_and_param(self, model):
        from shelves.data.duckdb_adapter import resolve_measure_expressions

        exprs = resolve_measure_expressions(model, parameters=_ps())
        assert 'SUM("revenue")' in exprs["revenue_by_period"]
        assert "'year'" in exprs["revenue_by_period"]

    def test_resolve_measure_no_param_unchanged(self, model):
        from shelves.data.duckdb_adapter import resolve_measure_expressions

        exprs = resolve_measure_expressions(model, parameters=_ps())
        assert "${" not in exprs["profit"]

    def test_resolve_measure_override(self, model):
        from shelves.data.duckdb_adapter import resolve_measure_expressions

        exprs = resolve_measure_expressions(model, parameters=_ps(grain="week"))
        assert "'week'" in exprs["sales_current"]

    def test_build_sql_dimension_calc_with_param(self, model, resolver):
        from shelves.data.duckdb_adapter import build_sql

        chart_spec = parse_chart("""
sheet: "T"
data: parameterized_calc
cols: order_period
rows: revenue
marks: bar
""")
        sql = build_sql("data/orders.csv", model, chart_spec, resolver, parameters=_ps())
        assert "'month'" in sql
        assert "${grain}" not in sql

    def test_build_sql_dimension_no_param(self, model, resolver):
        from shelves.data.duckdb_adapter import build_sql

        chart_spec = parse_chart("""
sheet: "T"
data: parameterized_calc
cols: region
rows: revenue
marks: bar
""")
        sql = build_sql("data/orders.csv", model, chart_spec, resolver, parameters=_ps())
        assert "${" not in sql

    def test_no_param_in_non_calculation_fields(self, model):
        """column, label, format fields are never substituted."""
        assert model.measures["revenue"].column == "revenue"
        assert model.measures["revenue"].label == "Revenue"


# ─── Cube source validation ─────────────────────────────────────────


class TestCubeSourceValidation:
    def test_cube_source_with_param_in_measure_calc_raises(self):
        from shelves.data.bind import _check_no_param_in_cube_calcs
        from shelves.models.schema import DataModel

        model = DataModel.model_validate(
            {
                "model": "cube_param",
                "label": "Cube Param",
                "source": {"type": "cube", "cube": "orders"},
                "measures": {
                    "sales": {
                        "label": "Sales",
                        "calculation": "SUM(col) FILTER (WHERE d >= DATE_TRUNC('${grain}', NOW()))",
                    },
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        with pytest.raises(
            ValueError, match="Parameterized calculations are only supported on file sources"
        ):
            _check_no_param_in_cube_calcs(model)

    def test_cube_source_with_param_in_dim_calc_raises(self):
        from shelves.data.bind import _check_no_param_in_cube_calcs
        from shelves.models.schema import DataModel

        model = DataModel.model_validate(
            {
                "model": "cube_param",
                "label": "Cube Param",
                "source": {"type": "cube", "cube": "orders"},
                "measures": {
                    "sales": {"label": "Sales", "column": "revenue", "aggregation": "sum"},
                },
                "dimensions": {
                    "d": {"label": "D", "calculation": "DATE_TRUNC('${grain}', col)"},
                },
            }
        )
        with pytest.raises(ValueError, match="Parameterized calculations are only supported"):
            _check_no_param_in_cube_calcs(model)

    def test_cube_source_without_param_is_fine(self):
        from shelves.data.bind import _check_no_param_in_cube_calcs
        from shelves.models.schema import DataModel

        model = DataModel.model_validate(
            {
                "model": "cube_ok",
                "label": "Cube OK",
                "source": {"type": "cube", "cube": "orders"},
                "measures": {
                    "sales": {"label": "Sales", "column": "revenue", "aggregation": "sum"},
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        _check_no_param_in_cube_calcs(model)  # should not raise


# ─── resolve_model_data threading ────────────────────────────────────


class TestResolveModelDataParameters:
    def test_parameters_thread_to_fetch(self):
        """resolve_model_data with parameters produces data without ${}-refs in SQL."""
        from shelves.pipeline import resolve_model_data

        chart_spec = parse_chart("""
sheet: "T"
data: parameterized_calc
cols: region
rows: sales_current
marks: bar
""")
        vl_spec = {"mark": "bar"}
        result = resolve_model_data(
            vl_spec,
            chart_spec,
            models_dir=MODELS_DIR,
            data_base_dir=DATA_DIR.parent,
            parameters=_ps(),
        )
        assert "data" in result
        assert "values" in result["data"]

    def test_empty_params_with_parameterized_model_raises(self):
        """If a model calculation has ${grain} but ParameterSet is empty, error."""
        from shelves.pipeline import resolve_model_data

        chart_spec = parse_chart("""
sheet: "T"
data: parameterized_calc
cols: region
rows: sales_current
marks: bar
""")
        vl_spec = {"mark": "bar"}
        with pytest.raises(ValueError, match="not a declared parameter"):
            resolve_model_data(
                vl_spec,
                chart_spec,
                models_dir=MODELS_DIR,
                data_base_dir=DATA_DIR.parent,
                parameters=ParameterSet.empty(),
            )
