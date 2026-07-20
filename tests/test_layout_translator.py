"""
Layout Translator Tests — Type-Led Syntax

Tests style resolution, HTML rendering, and end-to-end translation for the
new type-led Layout DSL. Covers the style cascade, each component type's
HTML output, and integration with the solver.

These tests define expected behavior for the implementation to follow.
"""

import re
import warnings

import pytest

from shelves.schema.layout_schema import (
    parse_dashboard,
)
from shelves.theme.merge import load_theme
from shelves.translator.layout import translate_dashboard
from shelves.translator.layout_styles import RenderContext, resolve_styles
from tests.conftest import load_layout_yaml

# ─── Helpers ──────────────────────────────────────────────────────


def _default_theme():
    return load_theme()


def _make_ctx(theme=None):
    return RenderContext(theme=theme or _default_theme())


def _resolve_component_styles(entry, ctx=None, parent_orientation="vertical", **kwargs):
    """Parse a type-led entry, resolve it, and return CSS string."""
    from shelves.schema.layout_schema import resolve_child

    _, comp = resolve_child(entry, {})
    ctx = ctx or _make_ctx()
    return resolve_styles(comp, None, ctx, parent_orientation=parent_orientation, **kwargs)


def _translate(yaml_str, theme=None, chart_specs=None):
    """Parse, solve, and translate a dashboard YAML to HTML."""
    spec = parse_dashboard(yaml_str)
    return translate_dashboard(spec, theme or _default_theme(), chart_specs=chart_specs)


def _inner_sheet_style(html: str, sheet_name: str) -> str:
    """Extract the style attribute of the inner div id="sheet-{name}"."""
    m = re.search(rf'id="sheet-{re.escape(sheet_name)}" style="([^"]+)"', html)
    assert m is not None, f"inner sheet div for '{sheet_name}' not found"
    return m.group(1)


def _outer_wrapper_style(html: str, sheet_name: str) -> str:
    """Extract the outer wrapper div style for a sheet (the div immediately
    wrapping id="sheet-{name}")."""
    m = re.search(rf'<div style="([^"]+)"><div id="sheet-{re.escape(sheet_name)}"', html)
    assert m is not None, f"outer wrapper for '{sheet_name}' not found"
    return m.group(1)


def _inner_text_style(html: str, content: str) -> str:
    """Extract the style attribute of the block div directly wrapping a text node.

    This is the ellipsis "holder" in the <flex-center><holder>{text}</holder></flex-center>
    structure — the innermost div that actually contains the text node.
    """
    m = re.search(rf'style="([^"]+)">{re.escape(content)}</div>', html)
    assert m is not None, f"inner text div for {content!r} not found"
    return m.group(1)


def _text_flex_parent_style(html: str, content: str) -> str:
    """Extract the style of the flex-centering div that wraps the text holder.

    Structure: <div FLEX-CENTER><div HOLDER>{content}</div></div>
    """
    m = re.search(rf'<div style="([^"]+)"><div style="[^"]*">{re.escape(content)}</div>', html)
    assert m is not None, f"flex-centering parent for {content!r} not found"
    return m.group(1)


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
        """Shared style properties resolve to CSS after flatten."""
        from shelves.translator.layout_flatten import flatten_dashboard

        yaml_str = """\
dashboard: "Test"
canvas: { width: 1000, height: 800 }
styles:
  card:
    background: "#FFFFFF"
    border_radius: 8
root:
  orientation: horizontal
  contains:
    - sheet: charts/foo.yaml
      style: card
      padding: 16
"""
        spec = parse_dashboard(yaml_str)
        flat = flatten_dashboard(spec)
        child_comp = flat.children[0].component
        css = resolve_styles(child_comp, None, _make_ctx(), parent_orientation="vertical")
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
        from shelves.translator.layout_flatten import flatten_dashboard

        yaml_str = """\
dashboard: "Test"
canvas: { width: 1000, height: 800 }
styles:
  card:
    background: "#FFF"
root:
  orientation: horizontal
  contains:
    - text: "Hello"
      preset: title
      style: card
      font_size: 20
      html: "letter-spacing: 2px;"
"""
        spec = parse_dashboard(yaml_str)
        flat = flatten_dashboard(spec)
        child_comp = flat.children[0].component
        css = resolve_styles(child_comp, None, _make_ctx(), parent_orientation="vertical")
        assert "font-family:" in css  # theme default
        assert "font-weight: bold" in css  # from preset
        assert "font-size: 20px" in css  # inline override
        assert "background: #FFF" in css  # shared style (now pre-merged via flatten)
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
        assert '<img src="assets/logo.png"' in html
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
        assert 'src="assets/img.png?a=1&amp;b=2"' in html

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

    def test_button_html_hatch_overrides_anchor_background(self):
        """html escape hatch must apply to the inner <a>, not just the outer wrapper div."""
        result = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Nav"
      href: "/nav"
      color: "#94A3B8"
      html: "display:block; background:none; border:none;"
""")
        # The <a> element should carry background:none from the html hatch,
        # overriding the #4A90D9 default from BUTTON_DEFAULTS.
        import re

        a_tag_match = re.search(r'<a [^>]*style="([^"]*)"', result)
        assert a_tag_match, "No <a> tag with style found"
        a_style = a_tag_match.group(1)
        assert "background:none" in a_style or "background: none" in a_style, (
            f"Expected background:none in <a> style, got: {a_style}"
        )

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
        assert 'rel="noopener noreferrer"' in html

    def test_button_target_blank_has_rel(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "External"
      href: "https://example.com"
      target: _blank
""")
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html

    def test_link_target_self_no_rel(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - link: "Internal"
      href: "/page"
""")
        assert 'rel="noopener' not in html

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


# ─── Gap Rendering ─────────────────────────────────────────────────


class TestGapRendering:
    """Gaps must produce visual spacing in rendered HTML, not just shrink children."""

    def test_horizontal_gap_produces_spacer(self):
        """Horizontal container with gap should render spacer divs between children."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        gap: 16
        contains:
          - text: "Left"
          - text: "Right"
""")
        # There should be a spacer div between the two text divs
        assert "width: 16px" in html

    def test_vertical_gap_produces_spacer(self):
        """Vertical container with gap should render spacer divs between children."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  gap: 20
  contains:
    - text: "Top"
      height: 50
    - text: "Bottom"
""")
        # There should be a spacer div with the gap height
        assert "height: 20px" in html

    def test_gap_zero_no_spacer(self):
        """Gap of 0 should not produce any spacer divs."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  gap: 0
  contains:
    - text: "A"
      height: 50
    - text: "B"
""")
        # Count divs — no spacer divs should appear
        # With gap=0, the output should be the same as without gap
        no_gap_html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "A"
      height: 50
    - text: "B"
""")
        assert html == no_gap_html

    def test_gap_single_child_no_spacer(self):
        """Single child with gap should not produce spacers."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  gap: 20
  contains:
    - text: "Only"
""")
        # With one child, no spacer div should be inserted
        # Check that no spacer div with the gap height exists
        assert '<div style="height: 20px;"></div>' not in html

    def test_horizontal_gap_spacer_count(self):
        """N children should produce N-1 spacer divs."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 1000, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        gap: 12
        contains:
          - text: "A"
          - text: "B"
          - text: "C"
""")
        # 3 children → 2 spacers, each with width: 12px
        assert html.count("width: 12px") == 2

    def test_nested_gaps_both_render(self):
        """Gaps at different nesting levels should all render."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 1000, height: 800 }
root:
  orientation: vertical
  gap: 20
  contains:
    - horizontal:
        height: 100
        gap: 16
        contains:
          - text: "A"
          - text: "B"
    - text: "C"
""")
        # Vertical gap spacer (20px height) between the horizontal row and "C"
        assert "height: 20px" in html
        # Horizontal gap spacer (16px width) between "A" and "B"
        assert "width: 16px" in html


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

    def test_fit_fill_chart_sizes_to_container(self):
        """A chart with fit: fill should stretch to fill its container in both dimensions."""
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: fitted
      fit: fill
""",
            chart_specs={"fitted": {"mark": "bar", "encoding": {}}},
        )
        assert '"width": "container"' in html
        assert '"height": "container"' in html

    def test_fit_width_chart_stretches_horizontally(self):
        """A chart with fit: width should stretch horizontally but keep its authored height."""
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
            chart_specs={"wide": {"mark": "bar", "height": 300}},
        )
        assert '"width": "container"' in html
        # Original height preserved — not replaced with "container"
        assert '"height": 300' in html

    def test_fit_height_chart_stretches_vertically(self):
        """A chart with fit: height should stretch vertically but keep its authored width."""
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
            chart_specs={"tall": {"mark": "line", "width": 400}},
        )
        assert '"height": "container"' in html
        # Original width preserved
        assert '"width": 400' in html

    def test_fit_sheet_padding_transferred_to_vega(self):
        """A fitted sheet's padding is CSS on the outer wrapper, not transferred to Vega.

        With div-in-div, CSS padding lives on the outer wrapper div.  The inner
        div (id="sheet-*") has no padding.  The Vega spec has no spec-level
        padding and config.padding is zeroed out so the chart fills the inner div.
        """
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: padded
      fit: fill
      padding: 12
""",
            chart_specs={
                "padded": {"mark": "bar", "config": {"padding": 16, "mark": {"color": "red"}}}
            },
        )

        # Outer wrapper div has CSS padding
        assert "padding: 12px" in html
        assert "box-sizing: border-box" in html

        # The inner sheet div should NOT have padding in its style
        m_div = re.search(r'id="sheet-padded" style="([^"]+)"', html)
        assert m_div is not None
        assert "padding" not in m_div.group(1)

        # The Vega spec should NOT carry spec-level padding
        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        spec = specs["sheet-padded"]
        assert "padding" not in spec
        # config.padding zeroed out — CSS outer div handles spacing
        assert spec.get("config", {}).get("padding") == 0
        # Other config properties preserved
        assert spec["config"]["mark"]["color"] == "red"

    def test_fit_sheet_string_padding_transferred_to_vega(self):
        """A fitted sheet with string padding shorthand emits CSS shorthand on the wrapper."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: asym
      fit: fill
      padding: "8 16"
""",
            chart_specs={"asym": {"mark": "bar"}},
        )

        # Outer wrapper has CSS shorthand padding
        assert "padding: 8px 16px" in html
        assert "box-sizing: border-box" in html

        # Vega spec has no padding
        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        spec = specs["sheet-asym"]
        assert "padding" not in spec

    def test_fit_sheet_four_value_padding_transferred_to_vega(self):
        """A fitted sheet with 4-value padding shorthand emits CSS shorthand on the wrapper."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: fourpad
      fit: fill
      padding: "10 20 30 40"
""",
            chart_specs={"fourpad": {"mark": "bar"}},
        )

        # Outer wrapper has CSS 4-value padding
        assert "padding: 10px 20px 30px 40px" in html
        assert "box-sizing: border-box" in html

        # Vega spec has no padding
        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        spec = specs["sheet-fourpad"]
        assert "padding" not in spec

    def test_no_fit_keeps_css_padding_and_zeros_vega_padding(self):
        """Without fit mode, CSS padding on wrapper; Vega config.padding zeroed."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: fixed
      padding: 8
""",
            chart_specs={"fixed": {"mark": "bar", "config": {"padding": 16}}},
        )
        # CSS padding should still be on the div
        assert "padding: 8px" in html
        # Vega config.padding zeroed out
        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        spec = specs["sheet-fixed"]
        assert spec.get("config", {}).get("padding") == 0

    def test_vega_background_zeroed_to_transparent(self):
        """Layout-embedded sheets have config.background forced to transparent.

        The CSS background on the outer wrapper div must show through — Vega's
        default white canvas (config.background="#ffffff" from ChartTheme) would
        otherwise cover it.  Analogous to config.padding being zeroed out.
        Other config properties must be preserved.
        """
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: colored
      background: "#FF0000"
""",
            chart_specs={
                "colored": {
                    "mark": "bar",
                    "config": {"background": "#ffffff", "mark": {"color": "blue"}},
                }
            },
        )

        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        spec = specs["sheet-colored"]
        # Vega background zeroed to transparent — CSS wrapper background shows through
        assert spec.get("config", {}).get("background") == "transparent"
        # Other config properties preserved
        assert spec["config"]["mark"]["color"] == "blue"

    def test_vega_background_set_when_no_existing_config(self):
        """config.background is set transparent even when the spec has no config block."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/bar.yaml
      name: plain
""",
            chart_specs={"plain": {"mark": "bar"}},
        )

        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        spec = specs["sheet-plain"]
        assert spec.get("config", {}).get("background") == "transparent"

    def test_faceted_chart_routed_to_browser_fit(self):
        """A faceted chart with fit: fill is sized in the browser: it is emitted
        UNSIZED and routed through compoundFit.fit with its solved content box
        (the browser applies the per-cell width). Height stays data-dependent.
        """
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: faceted
      fit: fill
      padding: 10
""",
            chart_specs={
                "faceted": {
                    "facet": {"field": "region", "type": "nominal"},
                    "columns": 2,
                    "spec": {"mark": "bar", "encoding": {}},
                    "config": {"padding": 16},
                }
            },
        )

        specs_match = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert specs_match is not None
        specs = json.loads(specs_match.group(1))
        spec = specs["sheet-faceted"]
        # Python does NOT size the cell — the browser does.
        assert "width" not in spec
        assert "width" not in spec["spec"]
        # Routed with its solved content box (780x580 from 800x600 minus padding 10).
        targets_match = re.search(r"const fitTargets = ({.*?});", html, re.DOTALL)
        assert targets_match is not None
        targets = json.loads(targets_match.group(1))
        assert targets["sheet-faceted"] == {"width": 780, "height": 580}
        # config.padding still zeroed out
        assert spec.get("config", {}).get("padding") == 0

    def test_faceted_chart_emitted_unsized_both_axes(self):
        """The browser owns facet sizing on BOTH axes (KAN-294): Python emits the
        facet spec with no width/height on the spec or its inner spec, and records
        the full solved content box for the browser to fill."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: faceted
      fit: fill
      padding: 10
""",
            chart_specs={
                "faceted": {
                    "facet": {"field": "region", "type": "nominal"},
                    "columns": 2,
                    "spec": {"mark": "bar", "encoding": {}},
                }
            },
        )

        specs_match = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert specs_match is not None
        specs = json.loads(specs_match.group(1))
        spec = specs["sheet-faceted"]
        assert "width" not in spec and "height" not in spec
        assert "width" not in spec["spec"] and "height" not in spec["spec"]
        targets_match = re.search(r"const fitTargets = ({.*?});", html, re.DOTALL)
        assert targets_match is not None
        targets = json.loads(targets_match.group(1))
        assert targets["sheet-faceted"] == {"width": 780, "height": 580}

    def test_faceted_chart_routes_for_fit_height(self):
        """A faceted chart with fit: height now routes to the browser sizer too
        (KAN-294 sizes height); previously facet only routed for width/fill."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: faceted
      fit: height
      padding: 10
""",
            chart_specs={
                "faceted": {
                    "facet": {"field": "region", "type": "nominal"},
                    "columns": 2,
                    "spec": {"mark": "bar", "encoding": {}},
                }
            },
        )

        targets_match = re.search(r"const fitTargets = ({.*?});", html, re.DOTALL)
        assert targets_match is not None
        targets = json.loads(targets_match.group(1))
        assert targets["sheet-faceted"] == {"width": 780, "height": 580}

    def test_rowcol_facet_routed(self):
        """A row/column/grid facet is emitted unsized and routed with its solved
        box; the grid shape is resolved in the browser from the bound data."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: faceted
      fit: fill
      padding: 10
""",
            chart_specs={
                "faceted": {
                    "facet": {"row": {"field": "category", "type": "nominal"}},
                    "spec": {"mark": "bar", "encoding": {}},
                }
            },
        )

        specs_match = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert specs_match is not None
        specs = json.loads(specs_match.group(1))
        targets_match = re.search(r"const fitTargets = ({.*?});", html, re.DOTALL)
        assert targets_match is not None
        targets = json.loads(targets_match.group(1))
        assert targets["sheet-faceted"] == {"width": 780, "height": 580}
        assert "height" not in specs["sheet-faceted"]["spec"]

    def test_no_fit_chart_keeps_original_dimensions(self):
        """A chart without fit should keep its authored width/height untouched."""
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: fixed
""",
            chart_specs={"fixed": {"mark": "bar", "width": 400, "height": 300}},
        )
        assert '"width": 400' in html
        assert '"height": 300' in html
        # No autosize override — chart renders at its authored size
        assert '"type": "fit"' not in html

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

    def test_compound_fit_with_legends_guards_and_catches(self):
        """A compound (faceted) sheet routed through compoundFit.fit on a
        dashboard that also has legends must not throw on a fit error: the
        populate callback guards an undefined result, and the compound branch
        carries a trailing .catch like the non-compound branch. Regression for
        the `undefined.view` TypeError when compoundFit.fit's internal .catch
        resolves with undefined.
        """
        from shelves.translator.layout_styles import LegendLink

        spec = parse_dashboard(
            """\
dashboard: "Compound + Legend"
canvas: { width: 800, height: 600 }
root:
  orientation: horizontal
  contains:
    - sheet: charts/foo.yaml
      name: faceted
      fit: fill
    - legend: charts/foo.yaml
      field: region
      width: 180
"""
        )
        legend_links = {
            ("charts/foo.yaml", "region"): LegendLink(
                sheet_id="sheet-faceted", title="Region", channel="color"
            )
        }
        html = translate_dashboard(
            spec,
            _default_theme(),
            chart_specs={
                "faceted": {
                    "facet": {"field": "region", "type": "nominal"},
                    "columns": 2,
                    "spec": {"mark": "bar", "encoding": {}},
                }
            },
            legend_links=legend_links,
        )

        # The compound sheet must route through compoundFit.fit with legends wired.
        line = next(ln for ln in html.splitlines() if "compoundFit.fit" in ln)
        assert "legendRender.populate" in line
        # populate must guard against an undefined result (fit error path):
        assert "if (r &&" in line
        # the compound branch must catch errors like the non-compound branch does:
        assert ".catch(" in line


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


# ─── Div-in-Div Rendering ───────────────────────────────────────────


class TestDivInDiv:
    """Tests for the div-in-div pattern for padded elements (KAN-221)."""

    def test_sheet_emits_wrapper_and_inner_div(self):
        """Fitted sheet with padding emits outer wrapper + inner div with id."""
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: padded_chart
      fit: fill
      padding: 16
""",
            chart_specs={"padded_chart": {"mark": "bar", "encoding": {}}},
        )
        # Outer div: dimensions, padding, overflow, box-sizing
        assert "padding: 16px" in html
        assert "overflow: hidden" in html
        assert "box-sizing: border-box" in html
        # Inner div has the sheet id
        assert 'id="sheet-padded_chart"' in html
        # Inner div style: width:100%, height:100%, position:relative
        m = re.search(r'id="sheet-padded_chart" style="([^"]+)"', html)
        assert m is not None, "sheet-padded_chart div not found"
        inner_css = m.group(1)
        assert "width: 100%" in inner_css
        assert "height: 100%" in inner_css
        assert "position: relative" in inner_css
        # Vega spec: no padding key, autosize without contains:padding
        import json

        m2 = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m2 is not None
        specs = json.loads(m2.group(1))
        spec = specs["sheet-padded_chart"]
        assert "padding" not in spec
        assert spec.get("autosize") == {"type": "fit"}

    def test_text_emits_wrapper_with_overflow_hidden(self):
        """Text element with padding gets outer wrapper + inner div with overflow:hidden."""
        import re

        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "A very long string that might overflow"
      padding: 12
      height: 40
""")
        # Outer div has padding and overflow:hidden
        assert "padding: 12px" in html
        assert "overflow: hidden" in html
        assert "box-sizing: border-box" in html
        # Inner div contains the text content
        assert "A very long string that might overflow" in html
        # Text is inside an inner div with overflow:hidden
        m = re.search(
            r'<div style="([^"]*overflow: hidden[^"]*)">'
            r"A very long string that might overflow</div>",
            html,
        )
        assert m is not None, "inner text div with overflow:hidden not found"

    def test_no_padding_emits_wrapper(self):
        """Element without padding always emits div-in-div — outer and inner divs."""
        import re

        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "No padding here"
""")
        assert "No padding here" in html
        # Outer div has overflow:hidden and box-sizing:border-box even without padding
        inline_styles = re.findall(r'style="([^"]+)"', html)
        assert any("box-sizing: border-box" in s for s in inline_styles)
        # Inner flex-centering div wraps a block holder that contains the text
        m = re.search(
            r'<div style="[^"]*box-sizing: border-box[^"]*">'
            r'<div style="[^"]*">'
            r'<div style="[^"]*">No padding here</div></div></div>',
            html,
        )
        assert m is not None, "Expected outer+flex+holder div structure around text"

    def test_no_fit_sheet_padding_stays_css(self):
        """Non-fitted sheet with padding uses div-in-div; Vega config.padding zeroed."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: fixed
      padding: 8
""",
            chart_specs={"fixed": {"mark": "bar", "config": {"padding": 16}}},
        )
        # Outer wrapper has CSS padding
        assert "padding: 8px" in html
        assert "box-sizing: border-box" in html
        # Inner div has sheet id
        m = re.search(r'id="sheet-fixed" style="([^"]+)"', html)
        assert m is not None
        # Vega config.padding zeroed out — CSS outer div handles spacing
        m2 = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m2 is not None
        specs = json.loads(m2.group(1))
        spec = specs["sheet-fixed"]
        assert "padding" not in spec
        assert spec.get("config", {}).get("padding") == 0

    def test_fit_width_scroll_on_outer(self):
        """fit:width puts overflow-y:auto on the outer wrapper."""
        import re

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
      padding: 10
""",
            chart_specs={"wide": {"mark": "bar", "height": 300}},
        )
        assert "overflow-y: auto" in html
        assert "box-sizing: border-box" in html
        # Sheet id on inner div
        assert 'id="sheet-wide"' in html
        m = re.search(r'id="sheet-wide" style="([^"]+)"', html)
        assert m is not None
        inner_css = m.group(1)
        assert "width: 100%" in inner_css
        assert "height: 100%" in inner_css

    def test_fit_height_scroll_on_outer(self):
        """fit:height puts overflow-x:auto on the outer wrapper."""
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
      padding: 10
""",
            chart_specs={"tall": {"mark": "line", "width": 400}},
        )
        assert "overflow-x: auto" in html
        assert "box-sizing: border-box" in html
        assert 'id="sheet-tall"' in html

    def test_container_padding_wrapper(self):
        """Container with padding uses div-in-div; children inside inner div."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        padding: 20
        contains:
          - text: "Child"
""")
        assert "padding: 20px" in html
        assert "overflow: hidden" in html
        assert "box-sizing: border-box" in html
        assert "Child" in html

    def test_faceted_chart_fit_target_uses_content_dims(self):
        """Faceted chart with fit:fill is routed to the browser sizer with its
        content_dims box (already padding-subtracted by the solver)."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: faceted
      fit: fill
      padding: 10
""",
            chart_specs={
                "faceted": {
                    "facet": {"field": "region", "type": "nominal"},
                    "columns": 2,
                    "spec": {"mark": "bar", "encoding": {}},
                }
            },
        )
        targets_match = re.search(r"const fitTargets = ({.*?});", html, re.DOTALL)
        assert targets_match is not None
        targets = json.loads(targets_match.group(1))
        # content_dims is (780, 580) [800-2*10, 600-2*10]
        assert targets["sheet-faceted"] == {"width": 780, "height": 580}

    def test_asymmetric_padding_on_wrapper(self):
        """Asymmetric padding renders as CSS shorthand on the wrapper; no Vega padding."""
        import json
        import re

        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: asym
      fit: fill
      padding: "8 16"
""",
            chart_specs={"asym": {"mark": "bar"}},
        )
        assert "padding: 8px 16px" in html
        assert "box-sizing: border-box" in html
        m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
        assert m is not None
        specs = json.loads(m.group(1))
        spec = specs["sheet-asym"]
        assert "padding" not in spec
        assert spec.get("autosize") == {"type": "fit"}

    def test_blank_and_image_with_padding(self):
        """Blank and image elements with padding use div-in-div."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - blank:
      height: 40
      padding: 8
    - image: logo.png
      alt: Logo
      height: 60
      padding: 4
""")
        assert "padding: 8px" in html
        assert "padding: 4px" in html
        assert "box-sizing: border-box" in html
        assert "<img" in html

    def test_button_link_padding_wrapper(self):
        """Button and link with padding use div-in-div outer wrapper."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Click"
      href: "/x"
      padding: 12
    - link: "More"
      href: "/y"
      padding: 8
""")
        assert "padding: 12px" in html
        assert "padding: 8px" in html
        assert "box-sizing: border-box" in html
        assert '<a href="/x"' in html
        assert '<a href="/y"' in html

    def test_zero_padding_still_emits_wrapper(self):
        """padding: 0 still emits div-in-div — wrapper is always present."""
        import re

        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Zero pad"
      padding: 0
""")
        assert "Zero pad" in html
        inline_styles = re.findall(r'style="([^"]+)"', html)
        assert any("box-sizing: border-box" in s for s in inline_styles)

    def test_margin_coexists_with_padding_wrapper(self):
        """Margin goes on outer div alongside padding."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Margined"
      margin: 8
      padding: 16
""")
        assert "padding: 16px" in html
        assert "margin: 8px" in html
        assert "box-sizing: border-box" in html

    def test_html_escape_hatch_on_outer_div(self):
        """html escape hatch is appended to the outer div's style."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Custom"
      padding: 16
      html: "border: 1px solid red;"
""")
        assert "border: 1px solid red;" in html
        assert "padding: 16px" in html


# ─── Bug Fixes (PR #20 Copilot Review) ─────────────────────────────


class TestConfigShallowCopyBug:
    """Bug #1: wrap_html_page mutates the caller's chart_specs config dict."""

    def test_chart_specs_config_not_mutated(self):
        """Original chart_specs config dict must not be modified after rendering."""
        original_config = {"axis": {"labelFontSize": 12}, "padding": 10, "background": "#fff"}
        chart_specs = {"mychart": {"mark": "bar", "encoding": {}, "config": original_config}}

        _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: mychart
      fit: fill
""",
            chart_specs=chart_specs,
        )

        assert original_config["padding"] == 10, "config.padding was mutated"
        assert original_config["background"] == "#fff", "config.background was mutated"
        assert original_config["axis"] == {"labelFontSize": 12}, "config.axis was mutated"


class TestImageAssetPaths:
    """KAN-308: image src is resolved relative to the assets dir via a URL prefix."""

    def _img_src(self, html: str) -> str:
        m = re.search(r'<img src="([^"]*)"', html)
        assert m is not None, "<img> tag not found"
        return m.group(1)

    def test_relative_src_gets_assets_prefix(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: png/logo.png
      alt: "Logo"
""")
        assert self._img_src(html) == "assets/png/logo.png"

    def test_external_url_passthrough(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: "https://cdn.example.com/logo.png"
      alt: "Logo"
""")
        assert self._img_src(html) == "https://cdn.example.com/logo.png"

    def test_data_uri_passthrough(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: "data:image/png;base64,AAAA"
      alt: "Logo"
""")
        assert self._img_src(html) == "data:image/png;base64,AAAA"

    def test_protocol_relative_passthrough(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: "//cdn.example.com/logo.png"
      alt: "Logo"
""")
        assert self._img_src(html) == "//cdn.example.com/logo.png"

    def test_custom_asset_prefix(self):
        spec = parse_dashboard("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: png/logo.png
      alt: "Logo"
""")
        html = translate_dashboard(spec, _default_theme(), asset_url_prefix="../assets/")
        m = re.search(r'<img src="([^"]*)"', html)
        assert m is not None
        assert m.group(1) == "../assets/png/logo.png"

    def test_no_leading_slash_in_emitted_relative_src(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: png/logo.png
      alt: "Logo"
""")
        assert not self._img_src(html).startswith("/")


class TestImageHtmlEscapeHatch:
    """Bug #2: Image component ignores html escape hatch and style extras."""

    def test_image_html_escape_hatch_on_img_tag(self):
        """html escape hatch on image must appear on the <img> tag, not just outer div."""
        import re

        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: photo.jpg
      alt: Photo
      height: 200
      html: "object-fit: cover"
""")
        m = re.search(r'<img[^>]+style="([^"]+)"', html)
        assert m is not None, "<img> tag not found"
        img_style = m.group(1)
        assert "object-fit: cover" in img_style


class TestImageFit:
    """KAN-297 Part A: image fit/center boolean content control."""

    def _img_style(self, html: str) -> str:
        m = re.search(r'<img[^>]+style="([^"]+)"', html)
        assert m is not None, "<img> tag not found"
        return m.group(1)

    def test_image_default_fit_top_left(self):
        """Defaults (fit:true, center:false) → contain, top-left, single sizing."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: logo.png
      alt: "Logo"
""")
        img_style = self._img_style(html)
        assert "object-fit: contain" in img_style
        assert "object-position: left top" in img_style
        assert "object-position: center" not in img_style
        assert img_style.count("width: 100%") == 1
        assert img_style.count("height: 100%") == 1
        assert "overflow: hidden" in html

    def test_image_fit_true_center_true(self):
        """fit:true + center:true centers the fitted image."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: logo.png
      alt: "Logo"
      fit: true
      center: true
""")
        img_style = self._img_style(html)
        assert "object-fit: contain" in img_style
        assert "object-position: center" in img_style
        assert "object-position: left top" not in img_style

    def test_image_fit_false_scrolls(self):
        """fit:false → natural-size image in a scrollable box."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: logo.png
      alt: "Logo"
      fit: false
""")
        img_style = self._img_style(html)
        assert "overflow: auto" in html
        assert "display: block" in img_style
        assert "object-fit" not in img_style

    def test_image_fit_false_ignores_center(self):
        """center has no effect when fit:false."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: logo.png
      alt: "Logo"
      fit: false
      center: true
""")
        img_style = self._img_style(html)
        assert "overflow: auto" in html
        assert "display: block" in img_style
        assert "object-position" not in img_style


class TestTextPresetIntegration:
    """Bug #4: Text presets (font-size/weight/color) must appear in rendered HTML."""

    def test_text_preset_title_in_rendered_html(self):
        """A text component with preset:title must have font-size/weight in the HTML."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Big Title"
      preset: title
""")
        assert "font-size: 24px" in html
        assert "font-weight: bold" in html
        assert "Big Title" in html


class TestScriptEscaping:
    """XSS: </script> in chart spec values must not break the dashboard script block."""

    def test_dashboard_spec_script_breakout(self):
        chart_specs = {
            "test_chart": {
                "mark": "bar",
                "title": "</script><script>alert(1)</script>",
            }
        }
        html = _translate(
            """\
dashboard: "XSS Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: dummy.yaml
      name: test_chart
""",
            chart_specs=chart_specs,
        )
        json_area = html.split("const specs = ")[1].split("Object.entries")[0]
        assert "</script>" not in json_area


class TestSheetInnerOverflow:
    """KAN-292: clipping/scroll lives on the inner content div so the clip
    boundary is the content box (inside padding), not the padding box."""

    def test_inner_div_overflow_hidden_default(self):
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: s1
      padding: 24
""",
            chart_specs={"s1": {"mark": "bar"}},
        )
        inner = _inner_sheet_style(html, "s1")
        assert "overflow: hidden" in inner
        assert "position: relative" in inner
        assert "width: 100%" in inner
        assert "height: 100%" in inner

    def test_container_inner_div_clips_overflow(self):
        """Non-sheet/text wrappers (container/image/blank) clip at the content
        box: the outer wrapper no longer carries overflow, so the inner content
        div must, or child content bleeds past the component boundary."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        padding: 20
        contains:
          - text: "Child"
""")
        m = re.search(r'<div style="[^"]*padding: 20px[^"]*"><div style="([^"]+)">', html)
        assert m is not None, "container outer+inner div structure not found"
        assert "overflow: hidden" in m.group(1)

    def test_padding_preserved_on_outer_wrapper(self):
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: s1
      padding: 24
""",
            chart_specs={"s1": {"mark": "bar"}},
        )
        outer = _outer_wrapper_style(html, "s1")
        assert "padding: 24px" in outer
        assert "box-sizing: border-box" in outer

    def test_outer_wrapper_no_overflow_when_no_fit(self):
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: s1
      padding: 24
""",
            chart_specs={"s1": {"mark": "bar"}},
        )
        outer = _outer_wrapper_style(html, "s1")
        assert "overflow" not in outer

    def test_fit_width_scroll_on_inner_div(self):
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
      padding: 24
""",
            chart_specs={"wide": {"mark": "bar"}},
        )
        inner = _inner_sheet_style(html, "wide")
        assert "overflow-y: auto" in inner
        assert "overflow: hidden" not in inner
        outer = _outer_wrapper_style(html, "wide")
        assert "overflow-y" not in outer
        assert "padding: 24px" in outer

    def test_fit_height_scroll_on_inner_div(self):
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
      padding: 24
""",
            chart_specs={"tall": {"mark": "line"}},
        )
        inner = _inner_sheet_style(html, "tall")
        assert "overflow-x: auto" in inner
        assert "overflow: hidden" not in inner
        outer = _outer_wrapper_style(html, "tall")
        assert "overflow-x" not in outer

    def test_fit_fill_clips_on_inner_div(self):
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
      padding: 24
""",
            chart_specs={"full": {"mark": "area"}},
        )
        inner = _inner_sheet_style(html, "full")
        assert "overflow: hidden" in inner
        outer = _outer_wrapper_style(html, "full")
        assert "overflow" not in outer

    def test_non_sheet_inner_styles_unchanged(self):
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Hello"
""",
            chart_specs={},
        )
        # Text inner div keeps overflow:hidden and the KAN-293 flex centering
        # (no position:relative leaked from the sheet branch).  The KAN-295
        # ellipsis clipping lives on the nested block holder, not the flex div.
        assert (
            "width: 100%; height: 100%; overflow: hidden; "
            "display: flex; flex-direction: column; justify-content: center" in html
        )
        assert "overflow: hidden; text-overflow: ellipsis; white-space: nowrap" in html


class TestTextVerticalCentering:
    """KAN-293: text content is vertically centered within its box so small and
    large text presets sit on the same vertical center (not top-aligned)."""

    def test_text_inner_div_vertically_centers(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Hello"
""")
        inner = _text_flex_parent_style(html, "Hello")
        assert "display: flex" in inner
        assert "flex-direction: column" in inner
        assert "justify-content: center" in inner

    def test_text_inner_div_keeps_overflow_and_size(self):
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Clip me"
""")
        # Sizing + clip on the flex-centering div; the ellipsis clip on the holder.
        inner = _text_flex_parent_style(html, "Clip me")
        assert "overflow: hidden" in inner
        assert "width: 100%" in inner
        assert "height: 100%" in inner
        assert "overflow: hidden" in _inner_text_style(html, "Clip me")

    def test_sheet_inner_div_not_centered(self):
        """Sheets must NOT get text flex-centering — only their fit-aware overflow."""
        html = _translate(
            """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: s1
      fit: fill
""",
            chart_specs={"s1": {"mark": "bar"}},
        )
        inner = _inner_sheet_style(html, "s1")
        assert "display: flex" not in inner
        assert "position: relative" in inner

    def test_image_inner_not_centered(self):
        """Images keep object-fit:contain sizing — no flex centering injected."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - image: "logo.png"
      alt: "Logo"
""")
        assert "object-fit: contain" in html
        m = re.search(r'<img src="assets/logo.png"[^>]*style="([^"]+)"', html)
        assert m is not None
        assert "justify-content: center" not in m.group(1)

    def test_link_in_horizontal_centers_anchor(self):
        """A link in a horizontal bar uses inline-flex + align-items:center so the
        <a> is vertically centered alongside centered text (KAN-293)."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        height: 60
        contains:
          - text: "Title"
          - link: "Nav"
            href: "/about"
""")
        m = re.search(r'<div style="([^"]+)"><a href="/about"', html)
        assert m is not None, "outer wrapper around link <a> not found"
        outer = m.group(1)
        assert "display: inline-flex" in outer
        assert "align-items: center" in outer

    def test_button_in_vertical_centers_anchor(self):
        """A button placed in a vertical container flex-centers its <a> so a fixed
        box height (e.g. a sidebar nav item) centers the label vertically."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - button: "Menu"
      href: "/x"
      height: 40
""")
        m = re.search(r'<div style="([^"]+)"><a href="/x"', html)
        assert m is not None, "outer wrapper around button <a> not found"
        outer = m.group(1)
        assert "display: flex" in outer
        assert "align-items: center" in outer


# ─── Text Overflow (KAN-295) ────────────────────────────────────────


class TestTextOverflow:
    """Text boxes clip with an ellipsis instead of silently swallowing content."""

    _LONG_TEXT = "A very long string that would overflow its fixed-size box"

    def test_text_inner_div_has_ellipsis(self):
        """Inner text div degrades clipped text with ellipsis + nowrap."""
        html = _translate(f"""\
dashboard: "Test"
canvas: {{ width: 800, height: 600 }}
root:
  orientation: vertical
  contains:
    - text: "{self._LONG_TEXT}"
      width: 120
      height: 40
""")
        style = _inner_text_style(html, self._LONG_TEXT)
        assert "overflow: hidden" in style
        assert "text-overflow: ellipsis" in style
        assert "white-space: nowrap" in style

    def test_text_inner_div_keeps_flex_centering(self):
        """The ellipsis change is additive — KAN-293 vertical centering is kept."""
        html = _translate(f"""\
dashboard: "Test"
canvas: {{ width: 800, height: 600 }}
root:
  orientation: vertical
  contains:
    - text: "{self._LONG_TEXT}"
      width: 120
      height: 40
""")
        style = _text_flex_parent_style(html, self._LONG_TEXT)
        assert "display: flex" in style
        assert "flex-direction: column" in style
        assert "justify-content: center" in style

    def test_text_no_explicit_size_gets_ellipsis(self):
        """Ellipsis default applies regardless of explicit width/height."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - text: "Auto sized"
""")
        style = _inner_text_style(html, "Auto sized")
        assert "text-overflow: ellipsis" in style
        assert "white-space: nowrap" in style

    def test_text_ellipsis_holder_is_block_not_flex(self):
        """KAN-295/KAN-293: the ellipsis lives on a block child, not the
        flex-centering parent — text-overflow:ellipsis is inert on a flex
        container, so it must not be co-located with display:flex."""
        html = _translate(f"""\
dashboard: "Test"
canvas: {{ width: 800, height: 600 }}
root:
  orientation: vertical
  contains:
    - text: "{self._LONG_TEXT}"
      width: 120
      height: 40
""")
        holder = _inner_text_style(html, self._LONG_TEXT)
        assert "text-overflow: ellipsis" in holder
        assert "display: flex" not in holder  # ellipsis only renders on a block box
        parent = _text_flex_parent_style(html, self._LONG_TEXT)
        assert "display: flex" in parent
        assert "justify-content: center" in parent
        assert "text-overflow" not in parent  # inert here; must live on the holder

    def test_non_text_leaf_no_ellipsis(self):
        """Only the text branch changes — sheet inner divs get no text-overflow."""
        html = _translate("""\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: chart_a
""")
        style = _inner_sheet_style(html, "chart_a")
        assert "text-overflow" not in style
        assert "white-space" not in style


# ─── Gap Warning Consolidation (KAN-295) ────────────────────────────


class TestGapWarningConsolidation:
    """Gap-overflow is warned exactly once, by the solver (single owner)."""

    def test_gap_overflow_warns_once(self):
        """Gap alone exceeding the box warns once (solver), not twice."""
        yaml_str = """\
dashboard: "Test"
canvas: { width: 200, height: 200 }
root:
  orientation: vertical
  contains:
    - horizontal:
        gap: 300
        contains:
          - text: "A"
          - text: "B"
"""
        with pytest.warns(UserWarning) as record:
            _translate(yaml_str)
        gap_warnings = [w for w in record if "exceeds available space" in str(w.message)]
        assert len(gap_warnings) == 1  # solver only
        # old renderer message is gone
        assert not any("does not fit in container" in str(w.message) for w in record)

    def test_gap_fits_no_warning(self):
        """A fitting gap produces no gap-overflow warning from either layer."""
        yaml_str = """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - horizontal:
        gap: 16
        contains:
          - text: "A"
          - text: "B"
"""
        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            _translate(yaml_str)
        assert not any("available space" in str(w.message) for w in record)
        assert not any("does not fit in container" in str(w.message) for w in record)

    def test_vertical_gap_overflow_warns_once_and_renders_spacer(self):
        """Vertical gap overflow warns once; spacer divs are still emitted."""
        yaml_str = """\
dashboard: "Test"
canvas: { width: 200, height: 200 }
root:
  orientation: vertical
  gap: 300
  contains:
    - text: "A"
    - text: "B"
"""
        with pytest.warns(UserWarning) as record:
            html = _translate(yaml_str)
        gap_warnings = [w for w in record if "exceeds available space" in str(w.message)]
        assert len(gap_warnings) == 1
        # Removing the warning must not remove spacer rendering.
        assert '<div style="height: 300px;"></div>' in html

    def test_single_child_large_gap_no_warning(self):
        """A single child means total_gap=0, so no gap warning fires."""
        yaml_str = """\
dashboard: "Test"
canvas: { width: 200, height: 200 }
root:
  orientation: vertical
  gap: 300
  contains:
    - text: "Only"
"""
        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter("always")
            _translate(yaml_str)
        assert not any("available space" in str(w.message) for w in record)
        assert not any("does not fit in container" in str(w.message) for w in record)


# ─── Concat (stacked multi-measure) sizing — KAN-291 ──────────────


def _concat_sheet_yaml(fit=None):
    """Dashboard YAML with a single stacked sheet named 'stacked'.

    canvas 800x600, padding 10 -> solver content_dims = (780, 580).
    """
    fit_str = f"      fit: {fit}\n" if fit else ""
    return (
        'dashboard: "Test"\n'
        "canvas: { width: 800, height: 600 }\n"
        "root:\n"
        "  orientation: vertical\n"
        "  contains:\n"
        "    - sheet: charts/stacked.yaml\n"
        "      name: stacked\n"
        f"{fit_str}"
        "      padding: 10\n"
    )


def _vconcat_spec():
    """Two measures on rows -> vconcat; x-axis shown only on the last panel."""
    return {
        "vconcat": [
            {
                "mark": "bar",
                "encoding": {
                    "x": {"field": "order_date", "type": "temporal", "axis": None},
                    "y": {"field": "revenue", "type": "quantitative"},
                },
            },
            {
                "mark": "bar",
                "encoding": {
                    "x": {"field": "order_date", "type": "temporal"},
                    "y": {"field": "profit", "type": "quantitative"},
                },
            },
        ],
        "spacing": 10,
        "bounds": "flush",
    }


def _hconcat_spec():
    """Two measures on cols -> hconcat; y-axis shown only on the first panel."""
    return {
        "hconcat": [
            {
                "mark": "bar",
                "encoding": {
                    "y": {"field": "category", "type": "nominal"},
                    "x": {"field": "revenue", "type": "quantitative"},
                },
            },
            {
                "mark": "bar",
                "encoding": {
                    "y": {"field": "category", "type": "nominal", "axis": None},
                    "x": {"field": "profit", "type": "quantitative"},
                },
            },
        ],
        "spacing": 10,
        "bounds": "flush",
    }


def _specs_from_html(html):
    import json

    m = re.search(r"const specs = ({.*?});", html, re.DOTALL)
    assert m is not None, "vegaEmbed specs block not found"
    return json.loads(m.group(1))


class TestCompoundFitWiring:
    """Compound (stacked multi-measure) specs are sized in the BROWSER (KAN-291).

    Python no longer computes per-panel pixels — it emits the compound spec
    unsized and hands compoundFit the solved content box, which measures axis/
    title extents in the DOM and sizes the panels. These tests assert that
    wiring; the pure sizing math is unit-tested in compound_fit.test.js and the
    rendered result is verified manually via PNG.
    """

    def _fit_targets(self, html):
        import json

        m = re.search(r"const fitTargets = ({.*?});", html, re.DOTALL)
        return json.loads(m.group(1)) if m else {}

    def test_vconcat_routed_to_browser_fit(self):
        html = _translate(_concat_sheet_yaml(fit="fill"), chart_specs={"stacked": _vconcat_spec()})
        spec = _specs_from_html(html)["sheet-stacked"]
        panels = spec["vconcat"]
        # Python does NOT size the panels — the browser does.
        for panel in panels:
            assert "width" not in panel and "height" not in panel
        assert "width" not in spec and "height" not in spec
        # The solved content box (canvas 800x600, padding 10 -> 780x580) is the target.
        assert self._fit_targets(html)["sheet-stacked"] == {"width": 780, "height": 580}
        # Flush bounds + emitted spacing are preserved for the browser sizer.
        assert spec["bounds"] == "flush"
        assert spec["spacing"] == 10
        # The browser sizer is inlined and invoked.
        assert "compoundFit" in html
        assert "compoundFit.fit(" in html

    def test_hconcat_routed_to_browser_fit(self):
        # The SAME path handles the swapped orientation (no orientation-specific
        # Python heuristic) — this is the regression the rewrite fixes.
        html = _translate(_concat_sheet_yaml(fit="fill"), chart_specs={"stacked": _hconcat_spec()})
        spec = _specs_from_html(html)["sheet-stacked"]
        for panel in spec["hconcat"]:
            assert "width" not in panel and "height" not in panel
        assert self._fit_targets(html)["sheet-stacked"] == {"width": 780, "height": 580}

    def test_fit_target_used_for_any_fit_mode(self):
        # width/height/fill all hand the box to the browser sizer.
        for mode in ("width", "height", "fill"):
            html = _translate(
                _concat_sheet_yaml(fit=mode), chart_specs={"stacked": _vconcat_spec()}
            )
            assert "sheet-stacked" in self._fit_targets(html)

    def test_concat_without_fit_not_routed(self):
        # No fit mode -> no target; falls through to a plain vegaEmbed, unsized.
        html = _translate(_concat_sheet_yaml(fit=None), chart_specs={"stacked": _vconcat_spec()})
        assert self._fit_targets(html) == {}
        panels = _specs_from_html(html)["sheet-stacked"]["vconcat"]
        assert all("width" not in p and "height" not in p for p in panels)

    def test_fit_js_inlined_only_when_a_concat_needs_it(self):
        # A single-view (non-compound) sheet doesn't pull in the browser sizer.
        single = {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "b"}}}
        html = _translate(_concat_sheet_yaml(fit="fill"), chart_specs={"stacked": single})
        assert self._fit_targets(html) == {}
        assert "compoundFit" not in html

    def test_single_view_uses_container_sizing(self):
        single = {"mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "b"}}}
        html = _translate(_concat_sheet_yaml(fit="fill"), chart_specs={"stacked": single})
        spec = _specs_from_html(html)["sheet-stacked"]
        assert spec["width"] == "container"
        assert spec["height"] == "container"
        assert spec["autosize"] == {"type": "fit"}

    def test_facet_routed_to_browser_fit(self):
        facet_spec = {
            "facet": {"field": "region", "type": "nominal"},
            "columns": 2,
            "spec": {"mark": "bar", "encoding": {}},
        }
        html = _translate(_concat_sheet_yaml(fit="fill"), chart_specs={"stacked": facet_spec})
        spec = _specs_from_html(html)["sheet-stacked"]
        # facet is sized in the browser on both axes (KAN-294): routed with its box,
        # NOT sized in Python (neither the spec nor its inner spec).
        assert self._fit_targets(html)["sheet-stacked"] == {"width": 780, "height": 580}
        assert "width" not in spec.get("spec", {}) and "height" not in spec.get("spec", {})
        assert "width" not in spec and "height" not in spec

    def test_repeat_routed_to_browser_fit(self):
        repeat_spec = {
            "repeat": {"row": ["a", "b"]},
            "spec": {"mark": "bar", "encoding": {}},
        }
        html = _translate(_concat_sheet_yaml(fit="width"), chart_specs={"stacked": repeat_spec})
        spec = _specs_from_html(html)["sheet-stacked"]
        assert self._fit_targets(html)["sheet-stacked"] == {"width": 780, "height": 580}
        assert "width" not in spec.get("spec", {})
        assert "width" not in spec

    def test_facet_routed_for_fit_height(self):
        # KAN-294: facet is now sized on both axes, so a height-only fit routes it
        # to the browser sizer too (previously facet was width-only and skipped).
        facet_spec = {
            "facet": {"field": "region", "type": "nominal"},
            "columns": 2,
            "spec": {"mark": "bar", "encoding": {}},
        }
        html = _translate(_concat_sheet_yaml(fit="height"), chart_specs={"stacked": facet_spec})
        assert self._fit_targets(html)["sheet-stacked"] == {"width": 780, "height": 580}


# ─── Label patch wiring in dashboards (KAN-307) ────────────────────


class TestDashboardLabelPatchWiring:
    """Dashboards must apply the browser-side label patch like the single-chart
    render path does, or labels (e.g. heatmap cell values) never appear.

    Bug: wrap_html_page embedded each sheet with vegaEmbed(..., {actions:false})
    and never inlined label_patch.js nor passed `patch: labelPatch`, so the
    label intent in usermeta.shelves.labels was silently ignored in dashboards.
    """

    _DASH = """\
dashboard: "Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: heat
      fit: fill
"""

    def test_label_patch_js_is_inlined(self):
        html = _translate(self._DASH, chart_specs={"heat": {"mark": "rect", "encoding": {}}})
        # The patch's global function must be present so `patch: labelPatch` resolves.
        assert "function labelPatch(" in html

    def test_plain_embed_passes_patch(self):
        html = _translate(self._DASH, chart_specs={"heat": {"mark": "rect", "encoding": {}}})
        assert "patch: labelPatch" in html

    def test_compound_embed_passes_patch(self):
        # Compound sheets route through compoundFit.fit, which forwards embedOpts
        # to vegaEmbed — the patch must ride along there too.
        html = _translate(_concat_sheet_yaml(fit="fill"), chart_specs={"stacked": _vconcat_spec()})
        assert "function labelPatch(" in html
        assert "patch: labelPatch" in html


# ─── Legend Render (SHE-9) ───────────────────────────────────────────


class TestLegendRender:
    """SHE-9: legend renders as a sized, positioned, empty placeholder box."""

    def test_legend_placeholder_box(self):
        html_out = _translate(load_layout_yaml("legend_basic.yaml"))

        # A legend placeholder div exists, with an id of the form legend-<name-or-auto-id>.
        m = re.search(
            r'<div style="([^"]+)"><div id="(legend-[^"]+)" style="([^"]+)"></div></div>',
            html_out,
        )
        assert m is not None
        outer_css, _legend_id, inner_css = m.group(1), m.group(2), m.group(3)

        # Outer wrapper carries solver dims + the card style + box-sizing.
        assert "width: 180px" in outer_css
        assert "height: 800px" in outer_css
        assert "background: #FFFFFF" in outer_css
        assert "border-radius: 8px" in outer_css
        assert "box-sizing: border-box" in outer_css
        assert "display: inline-block" in outer_css  # child of a horizontal container

        # Inner placeholder is a full-box clipped div, and EMPTY (no content yet).
        assert "width: 100%" in inner_css
        assert "height: 100%" in inner_css
        assert "overflow: hidden" in inner_css

    def test_legend_js_not_inlined_for_text_containing_data_channel(self):
        """#2: the legend renderer must be gated on resolved legend links, not on
        a substring scan of the rendered body. A text component that merely
        contains the literal 'data-channel=' must NOT pull in the legend JS when
        no legend is linked."""
        spec = parse_dashboard("""\
dashboard: "Legend False Positive"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      name: s1
    - text: "css snippet: data-channel=color"
""")
        html_out = translate_dashboard(
            spec,
            _default_theme(),
            chart_specs={"s1": {"mark": "bar", "encoding": {}}},
            legend_links={},  # no legend resolved
        )
        # The literal substring is present in the body, but no legend is linked:
        assert "data-channel=" in html_out
        assert "global.legendRender = api" not in html_out
        assert "legendRender.populate(" not in html_out

    def test_legend_minimal_render(self):
        html_out = _translate("""\
dashboard: "Legend Min"
canvas: { width: 600, height: 400 }
root:
  orientation: vertical
  contains:
    - legend: charts/foo.yaml
      field: Region
      height: 120
""")
        m = re.search(
            r'<div style="([^"]+)"><div id="(legend-[^"]+)" style="[^"]*"></div></div>',
            html_out,
        )
        assert m is not None
        outer_css = m.group(1)
        assert "height: 120px" in outer_css
        # vertical parent → fills cross axis
        assert "width: 600px" in outer_css
        # No style → no visual style keys on the wrapper (box-sizing: border-box
        # is structural and always present, so don't match the bare "border" token).
        assert "background" not in outer_css
        assert "border-radius" not in outer_css

    def test_legend_explicit_name_in_id(self):
        html_out = _translate("""\
dashboard: "Legend Named"
canvas: { width: 600, height: 400 }
root:
  orientation: vertical
  contains:
    - legend: charts/foo.yaml
      field: X
      name: cat_legend
""")
        assert 'id="legend-cat_legend"' in html_out

    def test_legend_html_escape_hatch(self):
        html_out = _translate("""\
dashboard: "Legend Html"
canvas: { width: 600, height: 400 }
root:
  orientation: vertical
  contains:
    - legend: charts/foo.yaml
      field: X
      html: "border: 1px solid red;"
""")
        m = re.search(
            r'<div style="([^"]+)"><div id="legend-[^"]+" style="[^"]*"></div></div>',
            html_out,
        )
        assert m is not None
        assert m.group(1).endswith("border: 1px solid red;")
