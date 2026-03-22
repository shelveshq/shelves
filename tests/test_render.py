"""
Render Tests

Tests for theme merging, data binding, HTML rendering,
and the full YAML -> HTML pipeline.
"""

import json

from src.render.to_html import render_html
from src.theme.merge import merge_theme, load_default_theme
from src.data.bind import bind_data
from src.schema.chart_schema import parse_chart
from src.translator.translate import translate_chart
from tests.conftest import load_yaml, load_data, MODELS_DIR


# ─── HTML Rendering ──────────────────────────────────────────────


class TestRenderHTML:
    def test_produces_valid_html(self):
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "mark": "bar",
            "encoding": {
                "x": {"field": "country", "type": "nominal"},
                "y": {"field": "revenue", "type": "quantitative"},
            },
        }
        html = render_html(spec, title="Test Chart")
        assert "<!DOCTYPE html>" in html
        assert "vegaEmbed" in html
        assert '"mark": "bar"' in html
        assert "<title>Test Chart</title>" in html

    def test_includes_cdn_scripts(self):
        html = render_html({"mark": "point"})
        assert "cdn.jsdelivr.net/npm/vega@5" in html
        assert "cdn.jsdelivr.net/npm/vega-lite@6" in html
        assert "cdn.jsdelivr.net/npm/vega-embed@6" in html

    def test_default_title_when_none(self):
        html = render_html({"mark": "bar"})
        assert "<title>Charter -- Chart Preview</title>" in html

    def test_title_from_spec(self):
        html = render_html({"mark": "bar", "title": "From Spec"})
        assert "<title>From Spec</title>" in html

    def test_title_escaping(self):
        html = render_html({"mark": "bar"}, title='<script>alert("xss")</script>')
        title_section = html.split("<title>")[1].split("</title>")[0]
        assert "<script>" not in title_section
        assert "&lt;" in title_section


# ─── Theme Merge ─────────────────────────────────────────────────


class TestThemeMerge:
    def test_default_theme_loads(self):
        theme = load_default_theme()
        assert isinstance(theme, dict)
        assert "background" in theme
        assert "range" in theme
        assert len(theme["range"]["category"]) == 8

    def test_theme_adds_config(self):
        spec = {"mark": "bar", "encoding": {}}
        result = merge_theme(spec)
        assert "config" in result
        assert result["config"]["background"] == "#ffffff"

    def test_spec_config_overrides_theme(self):
        spec = {"mark": "bar", "config": {"background": "#000000"}}
        result = merge_theme(spec)
        assert result["config"]["background"] == "#000000"

    def test_does_not_mutate_input(self):
        spec = {"mark": "bar"}
        original = dict(spec)
        merge_theme(spec)
        assert spec == original

    def test_custom_theme(self):
        spec = {"mark": "bar"}
        custom = {"background": "#222", "padding": 0}
        result = merge_theme(spec, theme=custom)
        assert result["config"]["background"] == "#222"
        assert result["config"]["padding"] == 0

    def test_color_palette(self):
        theme = load_default_theme()
        assert theme["range"]["category"][0] == "#4A90D9"


# ─── Data Binding ────────────────────────────────────────────────


class TestDataBinding:
    def test_bind_data_adds_values(self):
        spec = {"mark": "bar", "encoding": {}}
        rows = [{"country": "US", "revenue": 100}]
        result = bind_data(spec, rows)
        assert result["data"]["values"] == rows
        assert result["data"]["values"][0]["country"] == "US"

    def test_bind_data_does_not_mutate(self):
        spec = {"mark": "bar"}
        original_keys = set(spec.keys())
        bind_data(spec, [{"x": 1}])
        assert set(spec.keys()) == original_keys

    def test_bind_data_faceted(self):
        spec = {"facet": {"row": {"field": "region"}}, "spec": {"mark": "bar"}}
        result = bind_data(spec, [{"region": "NA", "revenue": 100}])
        assert "data" in result
        assert result["data"]["values"][0]["region"] == "NA"
        assert "data" not in result["spec"]

    def test_bind_empty_data(self):
        spec = {"mark": "bar"}
        result = bind_data(spec, [])
        assert result["data"]["values"] == []


# ─── Full Pipeline ───────────────────────────────────────────────


class TestEndToEnd:
    def test_full_pipeline_simple_bar(self):
        yaml_str = load_yaml("simple_bar.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        vl = merge_theme(vl)
        rows = json.loads(load_data("orders.json"))
        vl = bind_data(vl, rows)
        html_str = render_html(vl, title=spec.sheet)

        assert "<!DOCTYPE html>" in html_str
        assert "vegaEmbed" in html_str
        assert '"mark": "bar"' in html_str
        assert '"values"' in html_str
        assert '"config"' in html_str

    def test_full_pipeline_no_theme(self):
        yaml_str = load_yaml("simple_bar.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        # Skip merge_theme
        rows = json.loads(load_data("orders.json"))
        vl = bind_data(vl, rows)
        html_str = render_html(vl, title=spec.sheet)

        assert "<!DOCTYPE html>" in html_str
        assert '"config"' not in html_str

    def test_full_pipeline_no_data(self):
        yaml_str = load_yaml("simple_bar.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        vl = merge_theme(vl)
        html_str = render_html(vl, title=spec.sheet)

        assert "<!DOCTYPE html>" in html_str
        assert '"values"' not in html_str
        assert '"config"' in html_str

    def test_full_pipeline_model_auto_inject(self):
        """End-to-end: parse → translate (with model) → verify auto-injected values → theme → data → HTML."""
        yaml_str = load_yaml("simple_bar.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Verify auto-injection is present before theme/data stages
        assert vl["encoding"]["x"]["title"] == "Country"
        assert vl["encoding"]["y"]["title"] == "Revenue"
        assert vl["encoding"]["y"]["axis"]["format"] == "$,.0f"
        assert vl["encoding"]["color"]["legend"]["title"] == "Country"

        # Continue pipeline
        vl = merge_theme(vl)
        rows = json.loads(load_data("orders.json"))
        vl = bind_data(vl, rows)
        html_str = render_html(vl, title=spec.sheet)

        assert "<!DOCTYPE html>" in html_str
        assert "vegaEmbed" in html_str
        assert '"values"' in html_str
        assert '"config"' in html_str
