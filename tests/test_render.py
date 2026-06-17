"""
Render Tests

Tests for theme merging, data binding, HTML rendering,
and the full YAML -> HTML pipeline.
"""

import json

from shelves.data.bind import bind_data
from shelves.render.to_html import render_html
from shelves.schema.chart_schema import parse_chart
from shelves.theme.merge import load_theme, merge_theme
from shelves.translator.translate import translate_chart
from tests.conftest import MODELS_DIR, load_data, load_yaml

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

    def test_script_breakout_escaped(self):
        """</script> in a spec string must not break out of the script block."""
        spec = {"mark": "bar", "title": "</script><script>alert(1)</script>"}
        result = render_html(spec)
        json_area = result.split("const spec = ")[1].split("vegaEmbed")[0]
        assert "</script>" not in json_area

    def test_patch_callback_in_output(self):
        spec = {"mark": "bar", "encoding": {}}
        html = render_html(spec)
        assert "function charterPatch(vgSpec)" in html
        assert "patch: charterPatch" in html

    def test_patch_function_returns_spec(self):
        spec = {"mark": "bar", "encoding": {}}
        html = render_html(spec)
        assert "return vgSpec;" in html

    def test_patch_finds_named_marks(self):
        html = render_html({"mark": "bar"})
        assert "findMarkPath" in html
        assert "insertAfterMark" in html

    def test_patch_labels_bars_only(self):
        # Bars and ticks both compile to rect; the patch must label only bars,
        # distinguished by ariaRoleDescription.
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "ariaRoleDescription" in CHARTER_PATCH_JS
        assert "!== 'bar'" in CHARTER_PATCH_JS

    def test_patch_unclips_faceted_bar_groups(self):
        # Stacked/rounded bars are wrapped in a facet group clipped to the bar
        # bounding box; the patch must drop that clip so tip labels aren't
        # clipped away.
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "from.facet" in CHARTER_PATCH_JS
        assert "clip = { value: false }" in CHARTER_PATCH_JS

    def test_patch_creates_text_marks(self):
        html = render_html({"mark": "bar"})
        assert "type: 'text'" in html

    def test_patch_formats_with_d3(self):
        html = render_html({"mark": "bar"})
        assert "format(" in html
        # outside labels read the bar scene item's backing tuple at datum.datum
        assert "'datum.datum'" in html

    def test_patch_handles_match_color(self):
        html = render_html({"mark": "bar"})
        assert "'match'" in html

    def test_patch_skips_non_rect(self):
        html = render_html({"mark": "bar"})
        assert "!== 'rect'" in html

    def test_inlines_canonical_patch_source(self):
        # The standalone page must inline the canonical charter_patch.js
        # verbatim — never a stale copy. This guards against drift with the
        # studio pipeline, which serves the same file.
        from shelves.render.to_html import CHARTER_PATCH_JS, PATCH_JS_PATH

        source = PATCH_JS_PATH.read_text(encoding="utf-8")
        assert source == CHARTER_PATCH_JS
        assert CHARTER_PATCH_JS in render_html({"mark": "bar"})

    def test_patch_uses_label_transform(self):
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "type: 'label'" in CHARTER_PATCH_JS
        assert "size: { signal: labelSizeSignal(path) }" in CHARTER_PATCH_JS
        assert "as: ['x', 'y', 'opacity', 'align', 'baseline']" in CHARTER_PATCH_JS

    def test_patch_size_resolves_from_enclosing_group(self):
        # Concat/faceted layouts have no top-level width/height signal; the label
        # transform size must come from the enclosing child group, falling back
        # to the global signals for a top-level unit spec. (KAN-283 follow-up.)
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "function labelSizeSignal(path)" in CHARTER_PATCH_JS
        assert "from.facet" in CHARTER_PATCH_JS
        assert "return '[width, height]';" in CHARTER_PATCH_JS

    def test_patch_stacked_segments_default_center(self):
        # A real multi-segment stack (fill bound to a field other than the band
        # field) defaults to inside-center placement so inner segments aren't
        # auto-hidden by the outside anchor. (KAN-283 follow-up.)
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "isSegmented" in CHARTER_PATCH_JS
        assert "enc.fill.field !== bandField" in CHARTER_PATCH_JS
        assert "isSegmented ? 'center' : outsideDefault" in CHARTER_PATCH_JS

    def test_patch_maps_side_to_anchors(self):
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "function anchorCandidates(side)" in CHARTER_PATCH_JS
        assert "['top', 'bottom']" in CHARTER_PATCH_JS
        assert "['bottom', 'top']" in CHARTER_PATCH_JS
        assert "['left', 'right']" in CHARTER_PATCH_JS
        assert "['right', 'left']" in CHARTER_PATCH_JS
        assert "['middle']" in CHARTER_PATCH_JS

    def test_patch_sources_labels_from_mark(self):
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "from: { data: mark.name }" in CHARTER_PATCH_JS
        # outside labels read the bar scene item's backing tuple at datum.datum
        assert "'datum.datum'" in CHARTER_PATCH_JS

    def test_patch_center_placed_deterministically(self):
        # Inside/center labels (stacked segments) are NOT routed through the
        # label transform — its ['middle'] anchor drops most stacked labels.
        # They are placed by hand (band center + measure midpoint), sourced from
        # the data, while outside labels still use the transform.
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "function bandCenter(enc, dim)" in CHARTER_PATCH_JS
        assert "function midSignal(enc, axis)" in CHARTER_PATCH_JS
        assert "if (isCenter) {" in CHARTER_PATCH_JS
        assert "from: clone(mark.from)" in CHARTER_PATCH_JS
        # outside placement still avoids the base mark via the transform
        assert "avoidBaseMark: true" in CHARTER_PATCH_JS

    def test_patch_keeps_headroom(self):
        from shelves.render.to_html import CHARTER_PATCH_JS

        assert "applyHeadroom" in CHARTER_PATCH_JS
        # headroom is gated to outside placement (the non-center branch)
        assert "isCenter" in CHARTER_PATCH_JS


# ─── Theme Merge ─────────────────────────────────────────────────


class TestThemeMerge:
    def test_default_theme_loads(self):
        theme = load_theme()
        assert theme.chart.background == "#ffffff"
        assert "range" in theme.chart.model_dump()
        assert len(theme.chart.model_dump()["range"]["category"]) == 8

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
        theme = load_theme()
        assert theme.chart.model_dump()["range"]["category"][0] == "#4A90D9"


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
        """End-to-end: parse → translate (with model) → auto-inject → theme → data → HTML."""
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
