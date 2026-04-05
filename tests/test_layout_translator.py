"""
Layout Translator Tests — Type-Led Syntax

Tests style resolution, HTML rendering, and end-to-end translation for the
new type-led Layout DSL. Covers the style cascade, each component type's
HTML output, and integration with the solver.

These tests define expected behavior for the implementation to follow.
"""

from tests.conftest import load_layout_yaml

from src.schema.layout_schema import (
    parse_dashboard,
)
from src.theme.merge import load_theme
from src.translator.layout import translate_dashboard
from src.translator.layout_styles import RenderContext, resolve_styles


# ─── Helpers ──────────────────────────────────────────────────────


def _default_theme():
    return load_theme()


def _make_ctx(styles=None, components=None, theme=None):
    return RenderContext(
        components=components or {},
        styles=styles or {},
        theme=theme or _default_theme(),
    )


def _resolve_component_styles(entry, ctx=None, parent_orientation="vertical", **kwargs):
    """Parse a type-led entry, resolve it, and return CSS string."""
    from src.schema.layout_schema import resolve_child

    _, comp = resolve_child(entry, {})
    ctx = ctx or _make_ctx()
    return resolve_styles(comp, None, ctx, parent_orientation=parent_orientation, **kwargs)


def _translate(yaml_str, theme=None, chart_specs=None):
    """Parse, solve, and translate a dashboard YAML to HTML."""
    spec = parse_dashboard(yaml_str)
    return translate_dashboard(spec, theme or _default_theme(), chart_specs=chart_specs)


# ─── Style Resolution: Cascade ──────────────────────────────────────


class TestStyleCascade:
    def test_theme_font_on_text(self):
        """Text component picks up theme font-family."""
        css = _resolve_component_styles({"text": "Hello"})
        assert "font-family:" in css

    def test_text_preset_applies(self):
        """Text preset applies font-size, font-weight, color."""
        css = _resolve_component_styles({"text": "Hello", "preset": "title"})
        assert "font-size: 24px" in css
        assert "font-weight: bold" in css

    def test_shared_style_applies(self):
        """Shared style properties resolve to CSS."""
        from src.schema.layout_schema import StyleProperties, resolve_child

        ctx = _make_ctx(
            styles={
                "card": StyleProperties(background="#FFFFFF", border_radius=8),
            }
        )
        _, comp = resolve_child({"sheet": "charts/foo.yaml", "style": "card", "padding": 16}, {})
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "background: #FFFFFF" in css
        assert "border-radius: 8px" in css
        assert "padding: 16px" in css

    def test_inline_overrides_preset(self):
        """Inline font_size overrides preset value."""
        css = _resolve_component_styles({"text": "Hello", "preset": "title", "font_size": 20})
        assert "font-size: 20px" in css
        assert "font-size: 24px" not in css

    def test_html_escape_hatch_appended_last(self):
        """html field is appended at the end of CSS."""
        css = _resolve_component_styles(
            {"text": "Hello", "html": "text-transform: uppercase; letter-spacing: 2px;"}
        )
        assert css.endswith("text-transform: uppercase; letter-spacing: 2px;")

    def test_full_cascade(self):
        """All levels of the cascade work together."""
        from src.schema.layout_schema import StyleProperties, resolve_child

        ctx = _make_ctx(styles={"card": StyleProperties(background="#FFF")})
        _, comp = resolve_child(
            {
                "text": "Hello",
                "preset": "title",
                "style": "card",
                "font_size": 20,
                "html": "letter-spacing: 2px;",
            },
            {},
        )
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "font-family:" in css  # theme default
        assert "font-weight: bold" in css  # from preset
        assert "font-size: 20px" in css  # inline override
        assert "background: #FFF" in css  # shared style
        assert "letter-spacing: 2px;" in css  # html escape hatch


# ─── Style Resolution: Sizing ───────────────────────────────────────


class TestSizing:
    def test_solver_dimensions_emitted(self):
        css = _resolve_component_styles(
            {"blank": None},
            parent_orientation="horizontal",
            resolved_width=300,
            resolved_height=900,
        )
        assert "width: 300px" in css
        assert "height: 900px" in css

    def test_no_flex_properties(self):
        css = _resolve_component_styles(
            {"blank": None},
            parent_orientation="horizontal",
            resolved_width=720,
            resolved_height=900,
        )
        assert "flex" not in css

    def test_no_dimensions_without_solver(self):
        css = _resolve_component_styles(
            {"blank": None},
            parent_orientation="horizontal",
        )
        assert "width" not in css
        assert "height" not in css


# ─── Component HTML Rendering ───────────────────────────────────────


class TestComponentRendering:
    def test_text_renders_div(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Hello World"
      preset: title
""")
        assert "<div" in html
        assert "Hello World</div>" in html

    def test_text_html_escaped(self):
        html = _translate("""\
dashboard: "XSS Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "<script>alert('xss')</script>"
""")
        assert "&lt;script&gt;" in html
        assert "<script>alert" not in html

    def test_image_renders_img_tag(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: logo.png
      alt: "Company Logo"
""")
        assert '<img src="logo.png"' in html
        assert 'alt="Company Logo"' in html
        assert "object-fit: contain" in html

    def test_image_src_escaped(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: "img.png?a=1&b=2"
      alt: "test"
""")
        assert 'src="img.png?a=1&amp;b=2"' in html

    def test_image_alt_escaped(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: x.png
      alt: 'Say "hello"'
""")
        assert 'alt="Say &quot;hello&quot;"' in html

    def test_button_renders_anchor(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Go Home"
      href: "/home"
""")
        assert '<a href="/home"' in html
        assert "Go Home</a>" in html
        # Default button styles
        assert "background:" in html
        assert "border-radius:" in html

    def test_button_href_escaped(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Search"
      href: "/search?q=a&b=c"
""")
        assert 'href="/search?q=a&amp;b=c"' in html

    def test_button_text_escaped(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "A <b>bold</b> button"
      href: "/x"
""")
        assert "A &lt;b&gt;bold&lt;/b&gt; button</a>" in html

    def test_link_renders_anchor_with_underline(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - link: "Learn More"
      href: "/about"
""")
        assert '<a href="/about"' in html
        assert "Learn More</a>" in html
        assert "text-decoration: underline" in html
        assert "background: transparent" in html

    def test_button_and_link_different_defaults(self):
        """Button gets solid background; link gets transparent."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Click"
      href: "/a"
    - link: "More"
      href: "/b"
""")
        # Both render as <a> but with different styling
        assert html.count("<a ") == 2
        assert "text-decoration: underline" in html
        assert "text-decoration: none" in html

    def test_button_inline_style_overrides(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Custom"
      href: "/x"
      background: "#FF0000"
      color: "#000000"
""")
        assert "background: #FF0000" in html
        assert "color: #000000" in html

    def test_link_target_blank(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - link: "External"
      href: "https://example.com"
      target: _blank
""")
        assert 'target="_blank"' in html

    def test_blank_renders_empty_div(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - blank:
      height: 20
""")
        assert "></div>" in html

    def test_sheet_renders_div_with_id(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/revenue.yaml
      name: my_chart
""")
        assert 'id="sheet-my_chart"' in html

    def test_sheet_anonymous_gets_auto_id(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
""")
        assert 'id="sheet-auto-1"' in html

    def test_horizontal_children_inline_block(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        contains:
          - text: "Left"
          - text: "Right"
""")
        assert "display: inline-block" in html
        assert "Left" in html
        assert "Right" in html


# ─── Sheet Fit Modes ────────────────────────────────────────────────


class TestSheetFit:
    def test_fit_width_css(self):
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: wide
      fit: width
""",
            chart_specs={"wide": {"mark": "bar"}},
        )
        assert "overflow-y: auto" in html

    def test_fit_height_css(self):
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: tall
      fit: height
""",
            chart_specs={"tall": {"mark": "line"}},
        )
        assert "overflow-x: auto" in html

    def test_fit_fill_css(self):
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: full
      fit: fill
""",
            chart_specs={"full": {"mark": "area"}},
        )
        assert "overflow: hidden" in html

    def test_show_title_false(self):
        """show_title: false suppresses the chart title."""
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: notitle
      show_title: false
""",
            chart_specs={"notitle": {"mark": "bar", "title": "My Chart"}},
        )
        # The title should be nulled in the embedded spec
        assert '"title": null' in html or '"title":null' in html or "title: null" in html


# ─── Spacing CSS ────────────────────────────────────────────────────


class TestSpacingCSS:
    def test_margin_integer(self):
        css = _resolve_component_styles(
            {"blank": None, "margin": 16},
            parent_orientation="vertical",
        )
        assert "margin: 16px" in css

    def test_margin_shorthand(self):
        css = _resolve_component_styles(
            {"blank": None, "margin": "8 16 12 16"},
            parent_orientation="vertical",
        )
        assert "margin: 8px 16px 12px 16px" in css

    def test_padding_integer(self):
        css = _resolve_component_styles(
            {"blank": None, "padding": 16},
            parent_orientation="vertical",
        )
        assert "padding: 16px" in css


# ─── Full Translation Integration ───────────────────────────────────


class TestFullTranslation:
    def test_minimal_dashboard_html_structure(self):
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        html = translate_dashboard(spec, _default_theme())
        assert "<!DOCTYPE html>" in html
        assert "<title>Minimal Dashboard</title>" in html
        assert "width: 1440px" in html
        assert "height: 900px" in html
        assert "Hello World" in html
        # CDN scripts
        assert "vega@5" in html
        assert "vega-lite" in html
        assert "vega-embed" in html
        # CSS reset
        assert "box-sizing: border-box" in html

    def test_kpi_dashboard_renders(self):
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        html = translate_dashboard(spec, _default_theme())
        assert "<title>Sales Overview</title>" in html
        assert '<img src="assets/logo.svg"' in html
        assert '<a href="/dashboards/sales_detail"' in html

    def test_sidebar_dashboard_renders(self):
        spec = parse_dashboard(load_layout_yaml("sidebar_dashboard.yaml"))
        html = translate_dashboard(spec, _default_theme())
        assert "width: 220px" in html
        assert "display: inline-block" in html
        assert "Executive Summary" in html
        assert '<a href="/dashboards/overview"' in html

    def test_predefined_components_render(self):
        spec = parse_dashboard(load_layout_yaml("predefined_components.yaml"))
        html = translate_dashboard(spec, _default_theme())
        # Component "page_title" resolved and rendered
        assert "Overview" in html

    def test_solver_pixel_dimensions_in_output(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - horizontal:
        height: 200
        contains: []
""")
        assert "width: 1440px" in html
        assert "height: 900px" in html
        assert "height: 200px" in html

    def test_vegaembed_with_specs(self):
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        chart_specs = {"revenue_chart": {"mark": "bar", "encoding": {}}}
        html = translate_dashboard(spec, _default_theme(), chart_specs=chart_specs)
        assert "vegaEmbed" in html

    def test_no_vegaembed_without_specs(self):
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        html = translate_dashboard(spec, _default_theme(), chart_specs=None)
        assert "vegaEmbed" not in html or "const specs = {};" in html

    def test_theme_font_in_body(self):
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        html = translate_dashboard(spec, _default_theme())
        assert "font-family:" in html

    def test_empty_container_renders(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        contains: []
""")
        assert "width:" in html
        assert "height:" in html

    def test_deeply_nested_renders(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - vertical:
        contains:
          - horizontal:
              contains:
                - vertical:
                    contains:
                      - text: "Deep Text"
""")
        assert "Deep Text" in html


# ─── Edge Cases ─────────────────────────────────────────────────────


class TestTranslationEdgeCases:
    def test_multiline_text_rendered(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: |
        Line one.
        Line two.
      preset: caption
""")
        assert "Line one." in html
        assert "Line two." in html

    def test_blank_divider_with_background(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - blank:
      height: 1
      background: "#E0E0E0"
""")
        assert "background: #E0E0E0" in html

    def test_button_no_target_attr_for_self(self):
        """Default target _self should not emit a target attribute."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Go"
      href: "/x"
""")
        assert 'target="_self"' not in html

    def test_no_flex_in_output(self):
        """Solver-based layout should never emit flex properties."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: horizontal
  gap: 16
  contains:
    - sheet: charts/a.yaml
      width: "50%"
    - sheet: charts/b.yaml
""")
        assert "flex: 1" not in html
        assert "flex-grow" not in html
        assert "flex-direction" not in html

    def test_text_only_dashboard_no_vegaembed(self):
        html = _translate("""\
dashboard: "Text Only"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Just text"
      preset: title
""")
        assert "Just text" in html
        assert "vegaEmbed" not in html or "const specs = {};" in html
