"""
Facet Tests

Dedicated tests for facet wrapping logic.
"""

from src.schema.chart_schema import parse_chart
from src.translator.translate import translate_chart
from tests.conftest import load_yaml


def compile_fixture(name: str) -> dict:
    spec = parse_chart(load_yaml(name))
    return translate_chart(spec)


class TestFaceting:
    def test_row_facet_wraps_spec(self):
        vl = compile_fixture("facet_row.yaml")
        assert "facet" in vl
        assert vl["facet"]["row"]["field"] == "region"
        assert "spec" in vl
        assert vl["spec"]["mark"] == "bar"
        assert vl["spec"]["encoding"]["x"]["field"] == "country"

    def test_row_facet_resolve(self):
        vl = compile_fixture("facet_row.yaml")
        assert vl["resolve"]["scale"]["y"] == "independent"

    def test_wrap_facet(self):
        vl = compile_fixture("facet_wrap.yaml")
        assert vl["facet"]["field"] == "country"
        assert vl["columns"] == 4
        assert vl["facet"]["sort"] == {"order": "descending"}
        assert vl["spec"]["mark"] == "line"

    def test_non_faceted_has_no_wrapper(self):
        vl = compile_fixture("simple_bar.yaml")
        assert "facet" not in vl
        assert "spec" not in vl
        assert vl["mark"] == "bar"
