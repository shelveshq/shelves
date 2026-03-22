"""
Facet Tests

Dedicated tests for facet wrapping logic.
"""

from tests.conftest import compile_fixture


class TestFaceting:
    def test_row_facet_wraps_spec(self):
        vl = compile_fixture("facet_row.yaml")
        assert "facet" in vl
        assert vl["facet"]["row"]["field"] == "region"
        assert "spec" in vl
        assert vl["spec"]["mark"] == "bar"
        assert vl["spec"]["encoding"]["x"]["field"] == "country"

        # NEW: auto-injected titles inside faceted spec
        assert vl["spec"]["encoding"]["x"]["title"] == "Country"
        assert vl["spec"]["encoding"]["y"]["title"] == "Revenue"
        assert vl["spec"]["encoding"]["y"]["axis"]["format"] == "$,.0f"

    def test_row_facet_resolve(self):
        vl = compile_fixture("facet_row.yaml")
        assert vl["resolve"]["scale"]["y"] == "independent"

    def test_wrap_facet(self):
        vl = compile_fixture("facet_wrap.yaml")
        assert vl["facet"]["field"] == "country"
        assert vl["columns"] == 4
        assert vl["facet"]["sort"] == {"order": "descending"}
        assert vl["spec"]["mark"] == "line"

        # NEW: temporal auto-inject inside faceted spec
        assert vl["spec"]["encoding"]["x"]["title"] == "Month"
        assert vl["spec"]["encoding"]["x"]["timeUnit"] == "yearmonth"
        assert vl["spec"]["encoding"]["x"]["axis"]["format"] == "%b %Y"
        assert vl["spec"]["encoding"]["y"]["title"] == "Revenue"

    def test_non_faceted_has_no_wrapper(self):
        vl = compile_fixture("simple_bar.yaml")
        assert "facet" not in vl
        assert "spec" not in vl
        assert vl["mark"] == "bar"
