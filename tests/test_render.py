"""
Render Tests

Smoke tests for HTML output.
"""

from src.render.to_html import render_html


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
        assert "cdn.jsdelivr.net/npm/vega-lite@5" in html
        assert "cdn.jsdelivr.net/npm/vega-embed@6" in html
