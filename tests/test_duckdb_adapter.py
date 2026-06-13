"""
Tests for DuckDB query adapter — measure resolution, SQL generation, execution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shelves.data.duckdb_adapter import (
    DuckDBAdapter,
    DuckDBQueryError,
    build_sql,
    resolve_measure_expressions,
)
from shelves.models.loader import clear_model_cache, load_model
from shelves.models.resolver import ModelResolver
from shelves.models.schema import DataModel
from shelves.schema.chart_schema import parse_chart

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MODELS_DIR = FIXTURES_DIR / "models"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


@pytest.fixture
def duckdb_model():
    return load_model("duckdb_orders", models_dir=MODELS_DIR)


@pytest.fixture
def duckdb_resolver(duckdb_model):
    return ModelResolver(duckdb_model)


# ─── resolve_measure_expressions ─────────────────────────────────────


class TestResolveMeasureExpressions:
    def test_leaf_measures(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "measures": {
                    "revenue": {"label": "Revenue", "column": "revenue", "aggregation": "sum"},
                    "cost": {"label": "Cost", "column": "cost", "aggregation": "avg"},
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        exprs = resolve_measure_expressions(model)
        assert exprs == {
            "revenue": 'SUM("revenue")',
            "cost": 'AVG("cost")',
        }

    def test_count_distinct(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "measures": {
                    "users": {
                        "label": "Users",
                        "column": "user_id",
                        "aggregation": "count_distinct",
                    },
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        exprs = resolve_measure_expressions(model)
        assert exprs["users"] == 'COUNT(DISTINCT "user_id")'

    def test_calculation_simple(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "measures": {
                    "revenue": {"label": "Revenue", "column": "revenue", "aggregation": "sum"},
                    "cost": {"label": "Cost", "column": "cost", "aggregation": "sum"},
                    "profit": {"label": "Profit", "calculation": "{{ revenue }} - {{ cost }}"},
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        exprs = resolve_measure_expressions(model)
        assert exprs["profit"] == '(SUM("revenue")) - (SUM("cost"))'

    def test_calculation_nested(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "measures": {
                    "revenue": {"label": "Revenue", "column": "revenue", "aggregation": "sum"},
                    "cost": {"label": "Cost", "column": "cost", "aggregation": "sum"},
                    "profit": {"label": "Profit", "calculation": "{{ revenue }} - {{ cost }}"},
                    "margin": {"label": "Margin", "calculation": "{{ profit }} / {{ revenue }}"},
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        exprs = resolve_measure_expressions(model)
        assert exprs["margin"] == '((SUM("revenue")) - (SUM("cost"))) / (SUM("revenue"))'

    def test_calculation_raw_sql(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "measures": {
                    "complex": {"label": "Complex", "calculation": "SUM(price * quantity)"},
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        exprs = resolve_measure_expressions(model)
        assert exprs["complex"] == "SUM(price * quantity)"

    def test_column_without_aggregation(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "measures": {
                    "rev": {"label": "Revenue", "column": "revenue"},
                },
                "dimensions": {"d": {"label": "D"}},
            }
        )
        exprs = resolve_measure_expressions(model)
        assert exprs["rev"] == '"revenue"'


# ─── build_sql ────────────────────────────────────────────────────────


class TestBuildSql:
    def test_simple_bar(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert sql == (
            'SELECT "region" AS "region", SUM("revenue") AS "revenue"\n'
            "FROM read_csv_auto('/data/orders.csv')\n"
            'GROUP BY "region"'
        )

    def test_multi_field(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
            "color: country\ntooltip: [region, country, revenue, cost]\n"
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert sql == (
            'SELECT SUM("cost") AS "cost", "country" AS "country", '
            '"region" AS "region", SUM("revenue") AS "revenue"\n'
            "FROM read_csv_auto('/data/orders.csv')\n"
            'GROUP BY "country", "region"'
        )

    def test_dimension_only(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: country\nmarks: text\n'
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert sql == (
            'SELECT DISTINCT "country" AS "country", "region" AS "region"\n'
            "FROM read_csv_auto('/data/orders.csv')"
        )

    def test_grand_total(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Total Revenue"\ndata: duckdb_orders\n'
            'kpi:\n  value: revenue\n  format: "$,.0f"\n'
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert sql == (
            'SELECT SUM("revenue") AS "revenue"\nFROM read_csv_auto(\'/data/orders.csv\')'
        )

    def test_temporal_grain(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: order_date.month\n'
            "rows: revenue\nmarks: line\n"
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert sql == (
            'SELECT DATE_TRUNC(\'month\', "Order Date") AS "order_date", '
            'SUM("revenue") AS "revenue"\n'
            "FROM read_csv_auto('/data/orders.csv')\n"
            "GROUP BY DATE_TRUNC('month', \"Order Date\")"
        )

    def test_temporal_default_grain(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: order_date\nrows: revenue\nmarks: line\n'
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert "DATE_TRUNC('month', \"Order Date\")" in sql

    def test_calculated_dimension(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "source": {"type": "file", "path": "data/orders.csv"},
                "measures": {
                    "revenue": {"label": "Revenue", "column": "revenue", "aggregation": "sum"},
                },
                "dimensions": {
                    "fiscal_year": {
                        "label": "Fiscal Year",
                        "calculation": 'EXTRACT(YEAR FROM "Order Date")',
                    },
                },
            }
        )
        resolver = ModelResolver(model)
        spec = parse_chart('sheet: "Test"\ndata: t\ncols: fiscal_year\nrows: revenue\nmarks: bar\n')
        sql = build_sql("/data/orders.csv", model, spec, resolver)
        assert sql == (
            'SELECT EXTRACT(YEAR FROM "Order Date") AS "fiscal_year", '
            'SUM("revenue") AS "revenue"\n'
            "FROM read_csv_auto('/data/orders.csv')\n"
            'GROUP BY EXTRACT(YEAR FROM "Order Date")'
        )

    def test_calculated_measure(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: profit\nmarks: bar\n'
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert sql == (
            'SELECT (SUM("revenue")) - (SUM("cost")) AS "profit", '
            '"region" AS "region"\n'
            "FROM read_csv_auto('/data/orders.csv')\n"
            'GROUP BY "region"'
        )

    def test_filter_eq(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
            'filters:\n  - field: country\n    operator: eq\n    value: "US"\n'
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert "WHERE \"country\" = 'US'" in sql
        assert 'SUM("revenue") AS "revenue"' in sql

    def test_filter_in(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
            "filters:\n  - field: country\n    operator: in\n"
            '    values: ["US", "UK"]\n'
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert "WHERE \"country\" IN ('US', 'UK')" in sql

    def test_filter_between(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
            "filters:\n  - field: revenue\n    operator: between\n"
            "    range: [30000, 50000]\n"
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert 'WHERE "revenue" BETWEEN 30000 AND 50000' in sql

    def test_filter_multiple(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
            "filters:\n"
            '  - field: country\n    operator: eq\n    value: "US"\n'
            "  - field: revenue\n    operator: gte\n    value: 40000\n"
        )
        sql = build_sql("/data/orders.csv", duckdb_model, spec, duckdb_resolver)
        assert 'WHERE "country" = \'US\' AND "revenue" >= 40000' in sql

    def test_parquet_reader(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
        )
        sql = build_sql("/data/orders.parquet", duckdb_model, spec, duckdb_resolver)
        assert "FROM read_parquet('/data/orders.parquet')" in sql

    def test_json_reader(self, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
        )
        sql = build_sql("/data/orders.json", duckdb_model, spec, duckdb_resolver)
        assert "FROM read_json_auto('/data/orders.json')" in sql


# ─── DuckDB fetch (integration) ──────────────────────────────────────


class TestDuckDBFetch:
    @pytest.fixture
    def adapter(self):
        return DuckDBAdapter(base_dir=FIXTURES_DIR)

    def test_fetch_simple_bar(self, adapter, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
        )
        rows = adapter.fetch(duckdb_model, spec, duckdb_resolver)
        assert len(rows) == 3
        by_region = {r["region"]: r["revenue"] for r in rows}
        assert by_region["NA"] == 95000
        assert by_region["EU"] == 67000
        assert by_region["APAC"] == 58000

    def test_fetch_with_filter(self, adapter, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: revenue\nmarks: bar\n'
            'filters:\n  - field: country\n    operator: eq\n    value: "US"\n'
        )
        rows = adapter.fetch(duckdb_model, spec, duckdb_resolver)
        assert len(rows) == 1
        assert rows[0]["region"] == "NA"
        assert rows[0]["revenue"] == 95000

    def test_fetch_calculated_measure(self, adapter, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: profit\nmarks: bar\n'
        )
        rows = adapter.fetch(duckdb_model, spec, duckdb_resolver)
        by_region = {r["region"]: r["profit"] for r in rows}
        assert by_region["NA"] == 32000
        assert by_region["EU"] == 23000
        assert by_region["APAC"] == 19000

    def test_fetch_nested_calculation(self, adapter, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: margin\nmarks: bar\n'
        )
        rows = adapter.fetch(duckdb_model, spec, duckdb_resolver)
        by_region = {r["region"]: r["margin"] for r in rows}
        assert abs(by_region["NA"] - 32000 / 95000) < 0.0001
        assert abs(by_region["EU"] - 23000 / 67000) < 0.0001
        assert abs(by_region["APAC"] - 19000 / 58000) < 0.0001

    def test_fetch_grand_total(self, adapter, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Total Revenue"\ndata: duckdb_orders\n'
            'kpi:\n  value: revenue\n  format: "$,.0f"\n'
        )
        rows = adapter.fetch(duckdb_model, spec, duckdb_resolver)
        assert len(rows) == 1
        assert rows[0]["revenue"] == 220000

    def test_fetch_dimension_only(self, adapter, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: region\nrows: country\nmarks: text\n'
        )
        rows = adapter.fetch(duckdb_model, spec, duckdb_resolver)
        assert len(rows) == 3
        regions = {r["region"] for r in rows}
        assert regions == {"NA", "EU", "APAC"}

    def test_fetch_temporal_grain(self, adapter, duckdb_model, duckdb_resolver):
        spec = parse_chart(
            'sheet: "Test"\ndata: duckdb_orders\ncols: order_date.month\n'
            "rows: revenue\nmarks: line\n"
        )
        rows = adapter.fetch(duckdb_model, spec, duckdb_resolver)
        assert len(rows) == 2
        for row in rows:
            assert "order_date" in row
            assert "revenue" in row
        total = sum(r["revenue"] for r in rows)
        assert total == 220000


# ─── Errors ───────────────────────────────────────────────────────────


class TestDuckDBErrors:
    def test_file_not_found(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "source": {"type": "file", "path": "nonexistent.csv"},
                "measures": {"m": {"label": "M", "column": "x", "aggregation": "sum"}},
                "dimensions": {"d": {"label": "D"}},
            }
        )
        resolver = ModelResolver(model)
        spec = parse_chart('sheet: "T"\ndata: t\ncols: d\nrows: m\nmarks: bar\n')
        adapter = DuckDBAdapter(base_dir=FIXTURES_DIR)
        with pytest.raises(DuckDBQueryError, match="not found"):
            adapter.fetch(model, spec, resolver)

    def test_unsupported_extension(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "source": {"type": "file", "path": "data.xlsx"},
                "measures": {"m": {"label": "M", "column": "x", "aggregation": "sum"}},
                "dimensions": {"d": {"label": "D"}},
            }
        )
        resolver = ModelResolver(model)
        spec = parse_chart('sheet: "T"\ndata: t\ncols: d\nrows: m\nmarks: bar\n')
        with pytest.raises(DuckDBQueryError, match="Unsupported file extension"):
            build_sql("/path/data.xlsx", model, spec, resolver)

    def test_measure_unresolvable(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "source": {"type": "file", "path": "data.csv"},
                "measures": {"m": {"label": "M"}},
                "dimensions": {"d": {"label": "D"}},
            }
        )
        resolver = ModelResolver(model)
        spec = parse_chart('sheet: "T"\ndata: t\ncols: d\nrows: m\nmarks: bar\n')
        with pytest.raises(DuckDBQueryError, match="no column or calculation"):
            build_sql("/path/data.csv", model, spec, resolver)

    def test_not_file_source(self):
        model = DataModel.model_validate(
            {
                "model": "t",
                "label": "T",
                "source": {"type": "cube", "cube": "orders"},
                "measures": {"m": {"label": "M"}},
                "dimensions": {"d": {"label": "D"}},
            }
        )
        resolver = ModelResolver(model)
        spec = parse_chart('sheet: "T"\ndata: t\ncols: d\nrows: m\nmarks: bar\n')
        adapter = DuckDBAdapter(base_dir=FIXTURES_DIR)
        with pytest.raises(DuckDBQueryError):
            adapter.fetch(model, spec, resolver)


# ─── Adapter Registration ────────────────────────────────────────────


def test_file_adapter_registered():
    from shelves.data.sources import get_adapter

    adapter = get_adapter("file")
    assert isinstance(adapter, DuckDBAdapter)
