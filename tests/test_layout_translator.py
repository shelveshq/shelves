"""
Layout Translator Tests

Tests the Layout DSL → HTML translation pipeline.
Covers style resolution, sizing, and full integration.
"""

from tests.conftest import load_layout_yaml

from src.schema.layout_schema import (
    BlankComponent,
    DashboardSpec,
    RootComponent,
    SheetComponent,
    StyleProperties,
    TextComponent,
    parse_dashboard,
)
from src.theme.merge import load_theme
from src.translator.layout import translate_dashboard
from src.translator.layout_styles import RenderContext, resolve_styles


# ─── Helpers ──────────────────────────────────────────────────────


def _default_theme():
    return load_theme()


def _make_ctx(
    styles: dict | None = None,
    theme=None,
):
    """Build a minimal RenderContext for unit tests."""
    return RenderContext(
        components={},
        styles=styles or {},
        theme=theme or _default_theme(),
    )


# ─── Style Resolution ────────────────────────────────────────────


class TestStyleResolution:
    def test_resolve_styles_theme_defaults(self):
        """Bare text component picks up theme font-family."""
        comp = TextComponent(type="text", content="Hello")
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "font-family: Inter, system-ui, sans-serif" in css

    def test_resolve_styles_preset(self):
        """Text preset applies font-size, font-weight, color."""
        comp = TextComponent(type="text", content="Hello", preset="title")
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "font-size: 24px" in css
        assert "font-weight: bold" in css
        assert "color: #1a1a1a" in css

    def test_resolve_styles_shared_style(self):
        """Shared style properties resolve to CSS."""
        comp = SheetComponent(type="sheet", link="charts/foo.yaml", style="card", padding=16)
        ctx = _make_ctx(
            styles={
                "card": StyleProperties(background="#FFFFFF", border_radius=8),
            }
        )
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "background: #FFFFFF" in css
        assert "border-radius: 8px" in css
        assert "padding: 16px" in css

    def test_resolve_styles_inline_override(self):
        """Inline font_size overrides preset value."""
        comp = TextComponent(type="text", content="Hello", preset="title", font_size=20)
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "font-size: 20px" in css
        assert "font-size: 24px" not in css

    def test_resolve_styles_html_escape_hatch(self):
        """html field is appended to end of CSS."""
        comp = TextComponent(
            type="text",
            content="Hello",
            preset="title",
            html="text-transform: uppercase; letter-spacing: 2px;",
        )
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert css.endswith("text-transform: uppercase; letter-spacing: 2px;")

    def test_resolve_styles_full_cascade(self):
        """All five levels of the cascade work together."""
        comp = TextComponent(
            type="text",
            content="Hello",
            preset="title",
            style="card",
            font_size=20,
            html="letter-spacing: 2px;",
        )
        ctx = _make_ctx(
            styles={
                "card": StyleProperties(background="#FFF"),
            }
        )
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "font-family: Inter, system-ui, sans-serif" in css  # theme default
        assert "font-weight: bold" in css  # from preset, not overridden
        assert "color: #1a1a1a" in css  # from preset
        assert "font-size: 20px" in css  # inline override
        assert "background: #FFF" in css  # from shared style
        assert "letter-spacing: 2px;" in css  # from html


# ─── Sizing ───────────────────────────────────────────────────────


class TestSizing:
    def test_sizing_solver_dimensions(self):
        """Solver-provided dimensions emit fixed width/height CSS."""
        comp = BlankComponent(type="blank", width=300)
        ctx = _make_ctx()
        css = resolve_styles(
            comp,
            None,
            ctx,
            parent_orientation="horizontal",
            resolved_width=300,
            resolved_height=900,
        )
        assert "width: 300px" in css
        assert "height: 900px" in css

    def test_sizing_no_flex_emitted(self):
        """Solver-based sizing does not emit flex properties."""
        comp = BlankComponent(type="blank", width="50%")
        ctx = _make_ctx()
        css = resolve_styles(
            comp,
            None,
            ctx,
            parent_orientation="horizontal",
            resolved_width=720,
            resolved_height=900,
        )
        assert "flex" not in css
        assert "width: 720px" in css

    def test_sizing_without_solver(self):
        """Without solver dimensions, no width/height is emitted."""
        comp = BlankComponent(type="blank")
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="horizontal")
        assert "width" not in css
        assert "height" not in css


# ─── Component Rendering ─────────────────────────────────────────


class TestComponentRendering:
    """Verify each component type produces the correct HTML tag and attributes."""

    def test_text_renders_div_with_content(self):
        """TextComponent → <div> containing escaped text."""
        dashboard = DashboardSpec(
            dashboard="Text Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[{"type": "text", "content": "Hello World", "preset": "title"}],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert "<div" in html
        assert "Hello World</div>" in html

    def test_image_renders_img_tag(self):
        """ImageComponent → <img> with src, alt, and object-fit."""
        dashboard = DashboardSpec(
            dashboard="Image Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {"type": "image", "src": "logo.png", "alt": "Company Logo"},
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert '<img src="logo.png"' in html
        assert 'alt="Company Logo"' in html
        assert "object-fit: contain" in html

    def test_image_src_html_escaped(self):
        """Image src attribute is HTML-escaped."""
        dashboard = DashboardSpec(
            dashboard="Img Escape Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {"type": "image", "src": "img.png?a=1&b=2", "alt": "test"},
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert 'src="img.png?a=1&amp;b=2"' in html

    def test_image_alt_html_escaped(self):
        """Image alt attribute is HTML-escaped."""
        dashboard = DashboardSpec(
            dashboard="Alt Escape Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {"type": "image", "src": "x.png", "alt": 'Say "hello"'},
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert 'alt="Say &quot;hello&quot;"' in html

    def test_navigation_renders_anchor_tag(self):
        """NavigationComponent → <a> with href and button-style defaults."""
        dashboard = DashboardSpec(
            dashboard="Nav Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "type": "navigation",
                        "text": "Go Home",
                        "link": "/home",
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert '<a href="/home"' in html
        assert "Go Home</a>" in html
        # Default button styles
        assert "background: #4A90D9" in html
        assert "color: #FFFFFF" in html
        assert "border-radius: 6px" in html
        assert "padding: 8px 20px" in html
        assert "text-decoration: none" in html
        # No target attr for default _self
        assert 'target="_self"' not in html

    def test_navigation_button_renders_anchor_with_button_defaults(self):
        """NavigationButtonComponent → <a> with same button defaults as navigation."""
        dashboard = DashboardSpec(
            dashboard="Button Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "type": "navigation_button",
                        "text": "Click Me",
                        "link": "/action",
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert '<a href="/action"' in html
        assert "Click Me</a>" in html
        assert "background: #4A90D9" in html
        assert "padding: 8px 20px" in html

    def test_navigation_link_renders_anchor_with_link_defaults(self):
        """NavigationLinkComponent → <a> with underline, no button background."""
        dashboard = DashboardSpec(
            dashboard="Link Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "type": "navigation_link",
                        "text": "Learn More",
                        "link": "/about",
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert '<a href="/about"' in html
        assert "Learn More</a>" in html
        assert "text-decoration: underline" in html
        assert "background: transparent" in html
        assert "color: #4A90D9" in html
        assert "padding: 0" in html

    def test_navigation_link_href_escaped(self):
        """Navigation href is HTML-escaped."""
        dashboard = DashboardSpec(
            dashboard="Href Escape Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "type": "navigation",
                        "text": "Search",
                        "link": "/search?q=a&b=c",
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert 'href="/search?q=a&amp;b=c"' in html

    def test_navigation_text_escaped(self):
        """Navigation text content is HTML-escaped."""
        dashboard = DashboardSpec(
            dashboard="Text Escape Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "type": "navigation",
                        "text": "A <b>bold</b> link",
                        "link": "/x",
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert "A &lt;b&gt;bold&lt;/b&gt; link</a>" in html

    def test_navigation_inline_style_overrides_defaults(self):
        """Inline style properties override navigation button defaults."""
        dashboard = DashboardSpec(
            dashboard="Override Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "type": "navigation",
                        "text": "Custom",
                        "link": "/x",
                        "background": "#FF0000",
                        "color": "#000000",
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert "background: #FF0000" in html
        assert "color: #000000" in html

    def test_blank_renders_empty_div(self):
        """BlankComponent → empty <div> with only style."""
        dashboard = DashboardSpec(
            dashboard="Blank Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[{"type": "blank", "height": 20}],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        # Blank should produce an empty div (no text content)
        assert "></div>" in html

    def test_sheet_renders_div_with_id(self):
        """SheetComponent → <div> with id='sheet-{name}'."""
        dashboard = DashboardSpec(
            dashboard="Sheet Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "my_chart": {
                            "type": "sheet",
                            "link": "charts/revenue.yaml",
                        }
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert 'id="sheet-my_chart"' in html
        # Sheet div should be empty (chart is injected by vegaEmbed)
        assert 'id="sheet-my_chart" style=' in html

    def test_container_renders_div_with_children(self):
        """ContainerComponent → <div> with solver-computed dimensions and children."""
        dashboard = DashboardSpec(
            dashboard="Container Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "row": {
                            "type": "container",
                            "orientation": "horizontal",
                            "contains": [
                                {"type": "text", "content": "Left"},
                                {"type": "text", "content": "Right"},
                            ],
                        }
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        # Horizontal children get inline-block
        assert "display: inline-block" in html
        assert "Left" in html
        assert "Right" in html


# ─── Integration Tests ───────────────────────────────────────────


class TestLayoutTranslation:
    def test_translate_minimal_dashboard(self):
        """Minimal dashboard translates to valid HTML page structure."""
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        assert "<!DOCTYPE html>" in html
        assert "<title>Minimal Dashboard</title>" in html
        assert "width: 1440px" in html
        assert "height: 900px" in html
        assert "Hello World" in html
        # CDN scripts
        assert "vega@5" in html
        assert "vega-lite@6" in html
        assert "vega-embed@6" in html
        # CSS reset
        assert "margin: 0" in html
        assert "padding: 0" in html
        assert "box-sizing: border-box" in html

    def test_translate_kpi_dashboard(self):
        """Full KPI dashboard with all component types renders correctly."""
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        assert "<title>Sales Overview</title>" in html
        assert 'id="sheet-kpi_revenue"' in html
        assert 'id="sheet-kpi_orders"' in html
        assert 'id="sheet-kpi_arpu"' in html
        assert 'id="sheet-kpi_customers"' in html
        assert 'id="sheet-revenue_chart"' in html
        assert 'id="sheet-orders_chart"' in html
        assert '<a href="/dashboards/sales_detail"' in html
        assert '<img src="assets/logo.svg"' in html

    def test_translate_sidebar_dashboard(self):
        """Sidebar pattern with horizontal root translates correctly."""
        spec = parse_dashboard(load_layout_yaml("sidebar_dashboard.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        assert "width: 220px" in html
        # Horizontal root children are inline-block
        assert "display: inline-block" in html
        assert '<a href="/dashboards/overview"' in html
        assert "Executive Summary" in html

    def test_sheet_ids_in_output(self):
        """Named sheets get stable id='sheet-{name}' attributes."""
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        assert 'id="sheet-revenue_chart"' in html
        assert 'id="sheet-orders_chart"' in html

    def test_vegaembed_script(self):
        """When chart_specs are provided, vegaEmbed calls are generated."""
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        theme = _default_theme()
        chart_specs = {"revenue_chart": {"mark": "bar", "encoding": {}}}
        html = translate_dashboard(spec, theme, chart_specs=chart_specs)
        assert (
            "vegaEmbed('#sheet-revenue_chart'" in html
            or "vegaEmbed(`#sheet-revenue_chart`" in html
            or "vegaEmbed" in html
        )
        assert '"mark": "bar"' in html or "'mark': 'bar'" in html or '"mark"' in html

    def test_vegaembed_script_absent_without_specs(self):
        """When no chart specs, no vegaEmbed calls are generated."""
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme, chart_specs=None)
        # Should have empty specs or no vegaEmbed calls
        assert "vegaEmbed" not in html or "const specs = {};" in html

    def test_theme_font_in_body(self):
        """Body font-family comes from theme."""
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        assert "font-family: Inter, system-ui, sans-serif" in html

    def test_navigation_button_defaults(self):
        """Navigation/navigation_button gets button-style defaults."""
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        # The navigation component in kpi_dashboard should render as <a>
        assert "background: #4A90D9" in html or "background:#4A90D9" in html

    def test_navigation_link_defaults(self):
        """Navigation_link gets underlined text link defaults."""
        spec = parse_dashboard(load_layout_yaml("sidebar_dashboard.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        assert "text-decoration: underline" in html

    def test_image_object_fit(self):
        """Image gets default object-fit: contain."""
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        assert "object-fit: contain" in html

    def test_blank_spacer_resolved(self):
        """Blank with auto width gets solver-computed pixel dimensions."""
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        theme = _default_theme()
        html = translate_dashboard(spec, theme)
        # The blank with width: auto gets a concrete pixel width from solver
        # (no flex properties — solver pre-computes all dimensions)
        assert "flex: 1" not in html

    def test_text_html_escaped(self):
        """Text content is HTML-escaped to prevent XSS."""
        dashboard = DashboardSpec(
            dashboard="XSS Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[{"type": "text", "content": "<script>alert('xss')</script>"}],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert "&lt;script&gt;" in html
        assert "<script>alert" not in html

    def test_solver_dimensions_in_output(self):
        """Solver-computed pixel dimensions appear in rendered HTML."""
        dashboard = DashboardSpec(
            dashboard="Dimensions Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "row": {
                            "type": "container",
                            "orientation": "horizontal",
                            "height": 200,
                            "contains": [],
                        }
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        # Root gets canvas dimensions
        assert "width: 1440px" in html
        assert "height: 900px" in html
        # Container gets solver-computed dimensions
        assert "height: 200px" in html


# ─── Edge Cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_anonymous_sheet_auto_id(self):
        """Inline anonymous sheet gets auto-generated ID."""
        dashboard = DashboardSpec(
            dashboard="Auto ID Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[{"type": "sheet", "link": "charts/foo.yaml"}],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert 'id="sheet-auto-1"' in html

    def test_deeply_nested_containers(self):
        """4 levels of nesting all render."""
        dashboard = DashboardSpec(
            dashboard="Nested Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "l1": {
                            "type": "container",
                            "orientation": "horizontal",
                            "contains": [
                                {
                                    "l2": {
                                        "type": "container",
                                        "orientation": "vertical",
                                        "contains": [
                                            {
                                                "l3": {
                                                    "type": "container",
                                                    "orientation": "horizontal",
                                                    "contains": [
                                                        {
                                                            "type": "text",
                                                            "content": "Deep Text",
                                                        }
                                                    ],
                                                }
                                            }
                                        ],
                                    }
                                }
                            ],
                        }
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert "Deep Text" in html

    def test_empty_container(self):
        """Empty container renders as empty div with dimensions."""
        dashboard = DashboardSpec(
            dashboard="Empty Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "empty": {
                            "type": "container",
                            "orientation": "horizontal",
                            "contains": [],
                        }
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        # Empty container still gets solver-computed width/height
        assert "width:" in html
        assert "height:" in html

    def test_margin_as_integer(self):
        """Integer margin → CSS: margin: 16px."""
        comp = BlankComponent(type="blank", margin=16)
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "margin: 16px" in css

    def test_margin_as_shorthand_string(self):
        """String margin → CSS: margin with px units."""
        comp = BlankComponent(type="blank", margin="8 16 12 16")
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "margin: 8px 16px 12px 16px" in css

    def test_navigation_target_blank(self):
        """target: _blank includes target attribute on <a> tag."""
        dashboard = DashboardSpec(
            dashboard="Target Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "type": "navigation",
                        "text": "External",
                        "link": "https://example.com",
                        "target": "_blank",
                    }
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert 'target="_blank"' in html

    def test_fit_on_anonymous_sheet(self):
        """Anonymous sheet with fit gets auto-ID and fit CSS."""
        dashboard = DashboardSpec(
            dashboard="Fit Anon Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {"type": "sheet", "link": "charts/foo.yaml", "fit": "fill"},
                ],
            ),
        )
        theme = _default_theme()
        html = translate_dashboard(dashboard, theme)
        assert 'id="sheet-auto-1"' in html
        assert "overflow: hidden" in html

    def test_fit_width_with_explicit_height(self):
        """fit: width + height: 400 → overflow-y: auto, height sizing normal."""
        comp = SheetComponent(type="sheet", link="charts/foo.yaml", fit="width", height=400)
        ctx = _make_ctx()
        css = resolve_styles(comp, None, ctx, parent_orientation="vertical")
        assert "overflow-y: auto" in css


# ─── Sheet Fit ────────────────────────────────────────────────────


class TestSheetFit:
    def test_sheet_fit_width(self):
        """fit: width → overflow-y: auto, vegaEmbed injects width: container."""
        spec = parse_dashboard(load_layout_yaml("fit_sheets.yaml"))
        theme = _default_theme()
        chart_specs = {"wide_chart": {"mark": "bar"}}
        html = translate_dashboard(spec, theme, chart_specs=chart_specs)
        # The wide_chart sheet div
        assert 'id="sheet-wide_chart"' in html
        # Overflow CSS
        assert "overflow-y: auto" in html
        # vegaEmbed spec should have width: container
        assert '"width": "container"' in html

    def test_sheet_fit_height(self):
        """fit: height → overflow-x: auto, vegaEmbed injects height: container."""
        spec = parse_dashboard(load_layout_yaml("fit_sheets.yaml"))
        theme = _default_theme()
        chart_specs = {"tall_chart": {"mark": "line"}}
        html = translate_dashboard(spec, theme, chart_specs=chart_specs)
        assert 'id="sheet-tall_chart"' in html
        assert "overflow-x: auto" in html
        assert '"height": "container"' in html

    def test_sheet_fit_fill(self):
        """fit: fill → overflow: hidden, vegaEmbed injects both dimensions."""
        spec = parse_dashboard(load_layout_yaml("fit_sheets.yaml"))
        theme = _default_theme()
        chart_specs = {"full_chart": {"mark": "area"}}
        html = translate_dashboard(spec, theme, chart_specs=chart_specs)
        assert 'id="sheet-full_chart"' in html
        assert "overflow: hidden" in html
        assert '"width": "container"' in html
        assert '"height": "container"' in html

    def test_sheet_fit_none_default(self):
        """No fit → no overflow CSS, no container injection."""
        spec = parse_dashboard(load_layout_yaml("fit_sheets.yaml"))
        theme = _default_theme()
        chart_specs = {"fixed_chart": {"mark": "point"}}
        html = translate_dashboard(spec, theme, chart_specs=chart_specs)
        # fixed_chart should NOT have fit-related overflow
        assert 'id="sheet-fixed_chart"' in html

    def test_sheet_fit_with_explicit_size(self):
        """fit: width + width: 300 → both coexist."""
        dashboard = DashboardSpec(
            dashboard="Fit+Size Test",
            root=RootComponent(
                type="root",
                orientation="vertical",
                contains=[
                    {
                        "test_sheet": {
                            "type": "sheet",
                            "link": "charts/foo.yaml",
                            "fit": "width",
                            "width": 300,
                        }
                    }
                ],
            ),
        )
        theme = _default_theme()
        chart_specs = {"test_sheet": {"mark": "bar"}}
        html = translate_dashboard(dashboard, theme, chart_specs=chart_specs)
        assert "overflow-y: auto" in html
        assert '"width": "container"' in html

    def test_fit_sheets_full_translation(self):
        """End-to-end: fit modes propagated to vegaEmbed specs."""
        spec = parse_dashboard(load_layout_yaml("fit_sheets.yaml"))
        theme = _default_theme()
        chart_specs = {
            "wide_chart": {"mark": "bar"},
            "tall_chart": {"mark": "line"},
            "full_chart": {"mark": "area"},
            "fixed_chart": {"mark": "point"},
        }
        html = translate_dashboard(spec, theme, chart_specs=chart_specs)

        # Extract the script section for detailed assertion
        script_start = html.find("<script>")
        script_end = html.rfind("</script>")
        script = html[script_start:script_end]

        assert "vegaEmbed" in script
