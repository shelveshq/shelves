"""
Translator Tests

Tests the full YAML -> Vega-Lite compilation pipeline.
Each fixture YAML produces a deterministic Vega-Lite dict.
"""

from src.schema.chart_schema import parse_chart
from src.translator.translate import translate_chart
from tests.conftest import load_yaml


def compile_fixture(name: str) -> dict:
    spec = parse_chart(load_yaml(name))
    return translate_chart(spec)


class TestSingleMarkCharts:
    def test_simple_bar(self):
        vl = compile_fixture("simple_bar.yaml")
        assert vl["mark"] == "bar"
        assert vl["encoding"]["x"]["field"] == "country"
        assert vl["encoding"]["y"]["field"] == "revenue"
        assert vl["encoding"]["y"]["type"] == "quantitative"
        assert vl["encoding"]["color"]["field"] == "country"

    def test_grouped_bar(self):
        vl = compile_fixture("grouped_bar.yaml")
        assert vl["encoding"]["color"]["field"] == "product"

    def test_line_chart_temporal_x(self):
        vl = compile_fixture("line_chart.yaml")
        assert vl["encoding"]["x"]["type"] == "temporal"
        assert vl["mark"] == "line"

    def test_multi_line(self):
        vl = compile_fixture("multi_line.yaml")
        assert vl["mark"] == "line"
        assert vl["encoding"]["color"]["field"] == "country"

    def test_scatter(self):
        vl = compile_fixture("scatter.yaml")
        assert vl["mark"] == "circle"
        assert vl["encoding"]["x"]["type"] == "quantitative"
        assert vl["encoding"]["y"]["type"] == "quantitative"
        assert vl["encoding"]["size"]["field"] == "revenue"

    def test_heatmap(self):
        vl = compile_fixture("heatmap.yaml")
        assert vl["mark"] == "rect"
        assert vl["encoding"]["color"]["type"] == "quantitative"


class TestSort:
    def test_sort_on_x_encoding(self):
        vl = compile_fixture("simple_bar.yaml")
        assert vl["encoding"]["x"]["sort"] == {
            "field": "revenue",
            "order": "descending",
        }


class TestSchemaPresent:
    def test_has_vega_lite_schema(self):
        vl = compile_fixture("simple_bar.yaml")
        assert "$schema" in vl
        assert "vega-lite" in vl["$schema"]
