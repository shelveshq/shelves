"""
Layout DSL Schema Tests — Type-Led Syntax

Tests parsing, validation, and child resolution for the new type-led Layout DSL.
Every element starts with its type as the YAML key. Components are bare-string
references to predefined entries.

These tests define expected behavior for the implementation to follow.
"""

import pytest
from pydantic import ValidationError

from shelves.schema.layout_schema import (
    ButtonComponent,
    ContainerComponent,
    FilterComponent,
    ImageComponent,
    LegendComponent,
    LinkComponent,
    ParameterComponent,
    SheetComponent,
    TextComponent,
    parse_dashboard,
    resolve_child,
)
from tests.conftest import load_layout_yaml

# ─── Happy Path: Parsing Fixtures ────────────────────────────────────


class TestLayoutParsing:
    def test_parse_minimal_dashboard(self):
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        assert spec.dashboard == "Minimal Dashboard"
        assert spec.canvas.width == 1440
        assert spec.canvas.height == 900
        assert spec.root.orientation == "vertical"
        assert len(spec.root.contains) == 1
        assert spec.styles is None or spec.styles == {}
        assert spec.components is None or spec.components == {}

    def test_parse_kpi_dashboard(self):
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        assert spec.dashboard == "Sales Overview"
        assert spec.description == "Weekly sales KPIs and revenue trends"
        assert spec.canvas.width == 1440
        assert spec.styles is not None
        assert "card" in spec.styles
        assert spec.root.orientation == "vertical"
        # root contains: header row, kpi row, charts row
        assert len(spec.root.contains) == 3

    def test_parse_sidebar_dashboard(self):
        spec = parse_dashboard(load_layout_yaml("sidebar_dashboard.yaml"))
        assert spec.dashboard == "Executive Summary"
        assert spec.root.orientation == "horizontal"
        # sidebar + main
        assert len(spec.root.contains) == 2

    def test_parse_predefined_components(self):
        spec = parse_dashboard(load_layout_yaml("predefined_components.yaml"))
        assert spec.components is not None
        assert "page_title" in spec.components
        assert "kpi_revenue" in spec.components
        assert "kpi_orders" in spec.components
        assert "kpi_row" in spec.components

    def test_parse_fit_sheets(self):
        spec = parse_dashboard(load_layout_yaml("fit_sheets.yaml"))
        assert spec.dashboard == "Fit Sheets Demo"
        assert spec.root.orientation == "vertical"
        assert len(spec.root.contains) == 3


# ─── Happy Path: Type-Led Child Resolution ──────────────────────────


class TestResolveChild:
    """resolve_child transforms a raw YAML contains entry into (name, component)."""

    # --- Leaf types (multi-key dict) ---

    def test_resolve_sheet(self):
        entry = {"sheet": "charts/revenue.yaml", "style": "card", "padding": 12}
        name, comp = resolve_child(entry, {})
        assert name is None  # no explicit name
        assert comp.type == "sheet"
        assert comp.link == "charts/revenue.yaml"
        assert comp.style == "card"
        assert comp.padding == 12

    def test_resolve_sheet_with_name(self):
        entry = {"sheet": "charts/revenue.yaml", "name": "revenue_chart"}
        name, comp = resolve_child(entry, {})
        assert name == "revenue_chart"
        assert isinstance(comp, SheetComponent)
        assert comp.link == "charts/revenue.yaml"

    def test_resolve_sheet_with_fit(self):
        entry = {"sheet": "charts/foo.yaml", "fit": "width", "show_title": False}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, SheetComponent)
        assert comp.fit == "width"
        assert comp.show_title is False

    def test_resolve_text(self):
        entry = {"text": "Dashboard Title", "preset": "title"}
        name, comp = resolve_child(entry, {})
        assert name is None
        assert comp.type == "text"
        assert comp.content == "Dashboard Title"
        assert comp.preset == "title"

    def test_resolve_text_multiline(self):
        entry = {"text": "Line 1\nLine 2\n", "preset": "caption"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, TextComponent)
        assert "Line 1" in comp.content
        assert "Line 2" in comp.content

    def test_resolve_image(self):
        entry = {"image": "logo.svg", "alt": "Company Logo", "height": 40, "width": 120}
        _, comp = resolve_child(entry, {})
        assert comp.type == "image"
        assert comp.src == "logo.svg"
        assert comp.alt == "Company Logo"
        assert comp.height == 40
        assert comp.width == 120

    def test_resolve_button(self):
        entry = {"button": "View Details →", "href": "/dashboards/detail"}
        _, comp = resolve_child(entry, {})
        assert comp.type == "button"
        assert comp.text == "View Details →"
        assert comp.href == "/dashboards/detail"

    def test_resolve_link(self):
        entry = {"link": "Data Dictionary ↗", "href": "/docs", "target": "_blank"}
        _, comp = resolve_child(entry, {})
        assert comp.type == "link"
        assert comp.text == "Data Dictionary ↗"
        assert comp.href == "/docs"
        assert comp.target == "_blank"

    def test_resolve_blank(self):
        entry = {"blank": None}
        _, comp = resolve_child(entry, {})
        assert comp.type == "blank"

    def test_resolve_blank_with_size(self):
        entry = {"blank": None, "height": 16}
        _, comp = resolve_child(entry, {})
        assert comp.type == "blank"
        assert comp.height == 16

    # --- Container types (single-key dict, value is properties dict) ---

    def test_resolve_horizontal_container(self):
        entry = {
            "horizontal": {
                "gap": 16,
                "contains": [
                    {"sheet": "a.yaml"},
                    {"sheet": "b.yaml"},
                ],
            }
        }
        name, comp = resolve_child(entry, {})
        assert name is None
        assert comp.type == "horizontal"
        assert comp.gap == 16
        assert len(comp.contains) == 2

    def test_resolve_vertical_container(self):
        entry = {
            "vertical": {
                "padding": 24,
                "gap": 12,
                "contains": [
                    {"text": "Title", "preset": "heading"},
                ],
            }
        }
        _, comp = resolve_child(entry, {})
        assert comp.type == "vertical"
        assert comp.padding == 24
        assert comp.gap == 12

    def test_resolve_container_with_sizing(self):
        entry = {
            "horizontal": {
                "height": 56,
                "width": "80%",
                "contains": [],
            }
        }
        _, comp = resolve_child(entry, {})
        assert comp.height == 56
        assert comp.width == "80%"

    # --- String references ---

    def test_resolve_string_component_ref(self):
        """Bare string in contains looks up in the components dict."""
        # Simulate a pre-parsed component
        sheet_entry = {"sheet": "charts/kpi.yaml", "style": "card"}
        _, sheet_comp = resolve_child(sheet_entry, {})
        components = {"kpi_revenue": sheet_comp}

        name, comp = resolve_child("kpi_revenue", components)
        assert name == "kpi_revenue"
        assert comp.type == "sheet"
        assert comp.link == "charts/kpi.yaml"

    def test_resolve_string_ref_unknown_raises(self):
        with pytest.raises((KeyError, ValueError)):
            resolve_child("nonexistent", {})


# ─── Component Definition Parsing ────────────────────────────────────


class TestComponentParsing:
    """Components block uses the same type-led syntax as contains entries."""

    def test_leaf_component_definition(self):
        yaml_str = """\
dashboard: "Component Test"
canvas: { width: 1440, height: 900 }

components:
  revenue_kpi:
    sheet: charts/kpi_revenue.yaml
    style: card
    padding: 8

root:
  orientation: vertical
  contains:
    - revenue_kpi
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        assert "revenue_kpi" in spec.components
        comp = spec.components["revenue_kpi"]
        assert comp.type == "sheet"
        assert comp.link == "charts/kpi_revenue.yaml"
        assert comp.style == "card"

    def test_container_component_definition(self):
        yaml_str = """\
dashboard: "Container Component"
canvas: { width: 1440, height: 900 }

components:
  kpi_row:
    horizontal:
      gap: 16
      height: 120
      contains:
        - sheet: charts/kpi1.yaml
        - sheet: charts/kpi2.yaml

root:
  orientation: vertical
  contains:
    - kpi_row
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["kpi_row"]
        assert comp.type == "horizontal"
        assert comp.gap == 16
        assert comp.height == 120
        assert len(comp.contains) == 2

    def test_text_component_definition(self):
        yaml_str = """\
dashboard: "Text Component"
canvas: { width: 1440, height: 900 }

components:
  header:
    text: "My Dashboard"
    preset: title

root:
  orientation: vertical
  contains:
    - header
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["header"]
        assert comp.type == "text"
        assert comp.content == "My Dashboard"
        assert comp.preset == "title"

    def test_image_component_definition(self):
        yaml_str = """\
dashboard: "Image Component"
canvas: { width: 1440, height: 900 }

components:
  logo:
    image: logo.svg
    alt: "Logo"
    height: 28
    width: 100

root:
  orientation: vertical
  contains:
    - logo
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["logo"]
        assert comp.type == "image"
        assert comp.src == "logo.svg"
        assert comp.alt == "Logo"

    def test_component_with_defined_style(self):
        """Component referencing a style that exists in the styles block."""
        yaml_str = """\
dashboard: "Styled Component"
canvas: { width: 1440, height: 900 }

styles:
  card:
    background: "#FFFFFF"
    border_radius: 8

components:
  kpi:
    sheet: charts/kpi.yaml
    style: card
    padding: 8

root:
  orientation: vertical
  contains:
    - kpi
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["kpi"]
        assert comp.type == "sheet"
        assert comp.style == "card"
        assert spec.styles is not None
        assert "card" in spec.styles

    def test_component_with_undefined_style_allowed(self):
        """Component referencing a style not in styles block still parses."""
        yaml_str = """\
dashboard: "Loose Style"
canvas: { width: 1440, height: 900 }

components:
  kpi:
    sheet: charts/kpi.yaml
    style: fancy

root:
  orientation: vertical
  contains:
    - kpi
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["kpi"]
        assert comp.style == "fancy"

    def test_button_component_definition(self):
        yaml_str = """\
dashboard: "Button Component"
canvas: { width: 1440, height: 900 }

components:
  export_btn:
    button: "Export"
    href: "/export"

root:
  orientation: vertical
  contains:
    - export_btn
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["export_btn"]
        assert comp.type == "button"
        assert comp.text == "Export"
        assert comp.href == "/export"


# ─── Root Parsing ────────────────────────────────────────────────────


class TestRootParsing:
    def test_root_requires_orientation(self):
        yaml_str = """\
dashboard: "No Orientation"
canvas: { width: 1440, height: 900 }
root:
  contains:
    - text: "Hello"
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_root_requires_contains(self):
        yaml_str = """\
dashboard: "No Contains"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_root_accepts_gap(self):
        yaml_str = """\
dashboard: "Root Gap"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  gap: 20
  contains:
    - text: "A"
    - text: "B"
"""
        spec = parse_dashboard(yaml_str)
        assert spec.root.gap == 20

    def test_root_accepts_padding_and_margin(self):
        yaml_str = """\
dashboard: "Root Spacing"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  padding: 24
  margin: 16
  contains: []
"""
        spec = parse_dashboard(yaml_str)
        assert spec.root.padding == 24
        assert spec.root.margin == 16


# ─── Edge Cases ──────────────────────────────────────────────────────


class TestLayoutEdgeCases:
    def test_canvas_defaults(self):
        yaml_str = """\
dashboard: "No Canvas"
root:
  orientation: vertical
  contains: []
"""
        spec = parse_dashboard(yaml_str)
        assert spec.canvas.width == 1440
        assert spec.canvas.height == 900

    def test_empty_styles_block(self):
        yaml_str = """\
dashboard: "Empty Styles"
canvas: { width: 1440, height: 900 }
styles: {}
root:
  orientation: vertical
  contains: []
"""
        spec = parse_dashboard(yaml_str)
        assert spec.styles == {}

    def test_empty_components_block(self):
        yaml_str = """\
dashboard: "Empty Components"
canvas: { width: 1440, height: 900 }
components: {}
root:
  orientation: vertical
  contains: []
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components == {}

    def test_null_description(self):
        yaml_str = """\
dashboard: "No Desc"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains: []
"""
        spec = parse_dashboard(yaml_str)
        assert spec.description is None

    def test_integer_sizing(self):
        entry = {"sheet": "charts/foo.yaml", "width": 300}
        _, comp = resolve_child(entry, {})
        assert comp.width == 300

    def test_string_percentage_sizing(self):
        entry = {"sheet": "charts/foo.yaml", "width": "50%"}
        _, comp = resolve_child(entry, {})
        assert comp.width == "50%"

    def test_string_auto_sizing(self):
        entry = {"sheet": "charts/foo.yaml", "width": "auto"}
        _, comp = resolve_child(entry, {})
        assert comp.width == "auto"

    def test_pixel_string_sizing(self):
        entry = {"sheet": "charts/foo.yaml", "width": "300px"}
        _, comp = resolve_child(entry, {})
        assert comp.width == "300px"

    def test_padding_shorthand_four_values(self):
        entry = {
            "horizontal": {
                "contains": [],
                "padding": "8 16 12 16",
            }
        }
        _, comp = resolve_child(entry, {})
        assert comp.padding == "8 16 12 16"

    def test_padding_shorthand_two_values(self):
        entry = {
            "horizontal": {
                "contains": [],
                "padding": "8 16",
            }
        }
        _, comp = resolve_child(entry, {})
        assert comp.padding == "8 16"

    def test_alt_defaults_to_empty(self):
        entry = {"image": "logo.svg"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, ImageComponent)
        assert comp.alt == ""

    def test_target_defaults_to_self(self):
        entry = {"button": "Go", "href": "/go"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, ButtonComponent)
        assert comp.target == "_self"

    def test_link_target_defaults_to_self(self):
        entry = {"link": "Go", "href": "/go"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, LinkComponent)
        assert comp.target == "_self"

    def test_sheet_fit_default_none_or_fill(self):
        entry = {"sheet": "charts/foo.yaml"}
        _, comp = resolve_child(entry, {})
        # fit defaults to None (solver decides) or "fill"
        assert isinstance(comp, SheetComponent)
        assert comp.fit is None or comp.fit == "fill"

    def test_sheet_show_title_default_true(self):
        entry = {"sheet": "charts/foo.yaml"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, SheetComponent)
        assert comp.show_title is True

    def test_gap_defaults_to_zero(self):
        entry = {"horizontal": {"contains": []}}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, ContainerComponent)
        assert comp.gap == 0 or comp.gap is None

    def test_blank_as_flex_spacer(self):
        """Blank with no size acts as auto spacer."""
        entry = {"blank": None}
        _, comp = resolve_child(entry, {})
        assert comp.width is None or comp.width == "auto"
        assert comp.height is None or comp.height == "auto"

    def test_container_style_property(self):
        entry = {
            "horizontal": {
                "contains": [],
                "style": "header_bar",
                "background": "#F8F9FA",
            }
        }
        _, comp = resolve_child(entry, {})
        assert comp.style == "header_bar"

    def test_html_escape_hatch_on_leaf(self):
        entry = {"text": "HELLO", "html": "text-transform: uppercase;"}
        _, comp = resolve_child(entry, {})
        assert comp.html == "text-transform: uppercase;"

    def test_html_escape_hatch_on_container(self):
        entry = {
            "horizontal": {
                "contains": [],
                "html": "border: 1px solid red;",
            }
        }
        _, comp = resolve_child(entry, {})
        assert comp.html == "border: 1px solid red;"


# ─── Validation / Error Tests ────────────────────────────────────────


class TestLayoutValidation:
    def test_missing_dashboard_name(self):
        yaml_str = """\
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains: []
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_missing_root(self):
        yaml_str = """\
dashboard: "No Root"
canvas: { width: 1440, height: 900 }
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_unknown_type_key_raises(self):
        entry = {"chart": "charts/foo.yaml"}
        with pytest.raises((ValueError, KeyError)):
            resolve_child(entry, {})

    def test_invalid_preset_raises(self):
        yaml_str = """\
dashboard: "Bad Preset"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - text: "Hello"
      preset: huge
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_invalid_fit_value_raises(self):
        yaml_str = """\
dashboard: "Bad Fit"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      fit: stretch
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)


class TestImageComponent:
    """KAN-297 Part A: image fit/center booleans."""

    def test_resolve_image_fit_center(self):
        entry = {"image": "logo.svg", "fit": False, "center": False}
        _, comp = resolve_child(entry, {})
        assert comp.type == "image"
        assert comp.fit is False
        assert comp.center is False

    def test_image_fit_center_defaults(self):
        entry = {"image": "logo.svg"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, ImageComponent)
        assert comp.fit is True
        assert comp.center is False

    def test_invalid_image_fit_raises(self):
        yaml_str = """\
dashboard: "Bad Image Fit"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - image: logo.svg
      fit: sometimes
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_style_ref_not_found_raises(self):
        yaml_str = """\
dashboard: "Bad Style"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - sheet: charts/foo.yaml
      style: nonexistent
"""
        with pytest.raises((ValueError, KeyError)):
            parse_dashboard(yaml_str)

    def test_component_name_shadows_type_raises(self):
        yaml_str = """\
dashboard: "Shadow Type"
canvas: { width: 1440, height: 900 }
components:
  horizontal:
    text: "Bad"
root:
  orientation: vertical
  contains: []
"""
        with pytest.raises((ValueError, KeyError)):
            parse_dashboard(yaml_str)

    def test_component_referencing_component_raises(self):
        """Components cannot reference other component names in contains."""
        yaml_str = """\
dashboard: "Component Cycle"
canvas: { width: 1440, height: 900 }
components:
  inner:
    text: "Inner"
  outer:
    horizontal:
      contains:
        - inner
root:
  orientation: vertical
  contains:
    - outer
"""
        with pytest.raises((ValueError, KeyError)):
            parse_dashboard(yaml_str)

    def test_component_ref_as_dict_raises(self):
        """Component references must be bare strings, not dict keys."""
        yaml_str = """\
dashboard: "Dict Ref"
canvas: { width: 1440, height: 900 }
components:
  kpi:
    sheet: charts/kpi.yaml
root:
  orientation: vertical
  contains:
    - kpi:
"""
        # "kpi:" with null value looks like a dict {"kpi": None}
        # Since "kpi" is not a known type, this should error
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_leaf_with_contains_raises(self):
        """Leaf types must not have contains."""
        yaml_str = """\
dashboard: "Leaf Contains"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - text: "Hello"
      contains:
        - blank:
"""
        with pytest.raises((ValueError, TypeError)):
            parse_dashboard(yaml_str)

    def test_button_missing_href_raises(self):
        yaml_str = """\
dashboard: "No Href"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - button: "Click me"
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_link_missing_href_raises(self):
        yaml_str = """\
dashboard: "No Href"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - link: "Click me"
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)


# ─── Integration: Full Dashboard Round-Trip ──────────────────────────


class TestFullParsing:
    """End-to-end: YAML string → parse_dashboard → verify tree structure."""

    def test_mixed_inline_and_component_refs(self):
        yaml_str = """\
dashboard: "Mixed"
canvas: { width: 1440, height: 900 }

styles:
  card:
    background: "#FFF"
    border_radius: 8

components:
  logo:
    image: logo.svg
    alt: "Logo"
    height: 28
    width: 100

root:
  orientation: vertical
  gap: 20
  contains:
    - logo
    - text: "Sales Overview"
      preset: title
    - horizontal:
        gap: 16
        contains:
          - sheet: charts/revenue.yaml
            width: "60%"
            style: card
          - sheet: charts/orders.yaml
            style: card
"""
        spec = parse_dashboard(yaml_str)
        assert len(spec.root.contains) == 3
        assert spec.styles is not None
        assert spec.components is not None
        assert "card" in spec.styles
        assert "logo" in spec.components

    def test_deeply_nested_containers(self):
        yaml_str = """\
dashboard: "Deep Nesting"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - vertical:
        contains:
          - horizontal:
              contains:
                - vertical:
                    contains:
                      - text: "Deep"
                        preset: body
"""
        spec = parse_dashboard(yaml_str)
        # Should parse without error
        assert spec.root.contains is not None
        assert len(spec.root.contains) == 1

    def test_all_leaf_types_in_one_dashboard(self):
        yaml_str = """\
dashboard: "All Types"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  gap: 8
  contains:
    - sheet: charts/foo.yaml
    - text: "Hello"
    - button: "Click"
      href: "/x"
    - link: "More"
      href: "/y"
    - image: logo.svg
    - blank:
"""
        spec = parse_dashboard(yaml_str)
        assert len(spec.root.contains) == 6

    def test_component_ref_resolves_in_nested_container(self):
        """Component refs work inside inline containers in root."""
        yaml_str = """\
dashboard: "Nested Ref"
canvas: { width: 1440, height: 900 }
components:
  kpi:
    sheet: charts/kpi.yaml
root:
  orientation: vertical
  contains:
    - horizontal:
        contains:
          - kpi
          - kpi
"""
        spec = parse_dashboard(yaml_str)
        # The horizontal container's contains should have two refs to "kpi"
        assert spec.components is not None
        assert "kpi" in spec.components


# ─── Legend Component (SHE-9) ────────────────────────────────────────


class TestLegendComponent:
    """SHE-9: legend leaf component — schema parse/resolve/defaults + errors."""

    def test_parse_dashboard_with_legend(self):
        spec = parse_dashboard(load_layout_yaml("legend_basic.yaml"))
        assert len(spec.root.contains) == 2
        _, comp = resolve_child(spec.root.contains[1], {})
        assert comp.type == "legend"
        assert comp.source == "sales_by_category.yaml"
        assert comp.field == "Category"
        assert comp.title == "Product Category"
        assert comp.width == 180
        assert comp.style == "card"
        assert comp.orientation == "vertical"

    def test_resolve_legend(self):
        entry = {
            "legend": "charts/foo.yaml",
            "field": "Region",
            "title": "Sales Region",
            "width": 200,
            "style": "card",
        }
        name, comp = resolve_child(entry, {})
        assert name is None
        assert comp.type == "legend"
        assert comp.source == "charts/foo.yaml"
        assert comp.field == "Region"
        assert comp.title == "Sales Region"
        assert comp.width == 200
        assert comp.style == "card"
        assert comp.orientation == "vertical"

    def test_resolve_legend_minimal(self):
        entry = {"legend": "charts/foo.yaml", "field": "Region"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, LegendComponent)
        assert comp.source == "charts/foo.yaml"
        assert comp.field == "Region"
        assert comp.title is None
        assert comp.orientation == "vertical"
        assert comp.width is None
        assert comp.height is None
        assert comp.style is None

    def test_resolve_legend_orientation_horizontal(self):
        entry = {"legend": "charts/foo.yaml", "field": "Region", "orientation": "horizontal"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, LegendComponent)
        assert comp.orientation == "horizontal"

    def test_resolve_legend_with_name(self):
        entry = {"legend": "charts/foo.yaml", "field": "X", "name": "cat_legend"}
        name, comp = resolve_child(entry, {})
        assert name == "cat_legend"
        assert isinstance(comp, LegendComponent)
        assert comp.source == "charts/foo.yaml"

    def test_resolve_legend_with_html(self):
        entry = {"legend": "charts/foo.yaml", "field": "X", "html": "border: 1px solid red;"}
        _, comp = resolve_child(entry, {})
        assert comp.html == "border: 1px solid red;"

    def test_legend_missing_field_raises(self):
        with pytest.raises(ValidationError):
            resolve_child({"legend": "charts/foo.yaml"}, {})

    def test_legend_missing_field_in_dashboard_raises(self):
        yaml_str = """\
dashboard: "Legend No Field"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - legend: charts/foo.yaml
"""
        with pytest.raises((ValueError, ValidationError)):
            parse_dashboard(yaml_str)

    def test_legend_with_contains_raises(self):
        yaml_str = """\
dashboard: "Legend Contains"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - legend: charts/foo.yaml
      field: Region
      contains:
        - blank:
"""
        with pytest.raises(ValueError):
            parse_dashboard(yaml_str)

    def test_legend_invalid_orientation_raises(self):
        with pytest.raises(ValidationError):
            resolve_child(
                {"legend": "charts/foo.yaml", "field": "X", "orientation": "diagonal"}, {}
            )

    def test_legend_undefined_style_raises(self):
        yaml_str = """\
dashboard: "Bad Legend Style"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - legend: charts/foo.yaml
      field: Region
      style: nonexistent
"""
        with pytest.raises((ValueError, KeyError)):
            parse_dashboard(yaml_str)


# ─── Parameter Component (SHE-97: renamed from control) ───────────────


class TestParameterComponent:
    """SHE-97: parameter leaf component — schema parse/resolve/defaults + errors."""

    def test_resolve_parameter(self):
        entry = {"parameter": "metric"}
        name, comp = resolve_child(entry, {})
        assert name is None
        assert isinstance(comp, ParameterComponent)
        assert comp.type == "parameter"
        assert comp.param == "metric"
        assert comp.label is None

    def test_resolve_parameter_with_label(self):
        entry = {"parameter": "status", "label": "Order Status"}
        name, comp = resolve_child(entry, {})
        assert name is None
        assert isinstance(comp, ParameterComponent)
        assert comp.param == "status"
        assert comp.label == "Order Status"

    def test_resolve_parameter_with_sizing(self):
        entry = {"parameter": "metric", "width": 200, "height": 40}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, ParameterComponent)
        assert comp.width == 200
        assert comp.height == 40

    def test_resolve_parameter_with_style(self):
        entry = {"parameter": "metric", "style": "card"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, ParameterComponent)
        assert comp.style == "card"

    def test_resolve_parameter_with_html(self):
        entry = {"parameter": "metric", "html": "border: 1px solid red;"}
        _, comp = resolve_child(entry, {})
        assert comp.html == "border: 1px solid red;"

    def test_parameter_empty_param_raises(self):
        with pytest.raises(ValidationError):
            resolve_child({"parameter": ""}, {})

    def test_parameter_with_contains_raises(self):
        yaml_str = """\
dashboard: "Parameter Contains"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - parameter: metric
      contains:
        - blank:
"""
        with pytest.raises(ValueError):
            parse_dashboard(yaml_str)

    def test_parse_dashboard_with_parameters(self):
        spec = parse_dashboard(load_layout_yaml("control_dashboard.yaml"))
        assert len(spec.root.contains) == 2
        # First child is a horizontal container with parameter components
        h_entry = spec.root.contains[0]
        assert isinstance(h_entry, dict)
        inner = h_entry["horizontal"]
        assert len(inner["contains"]) == 3

    def test_parameter_in_components_block(self):
        yaml_str = """\
dashboard: "Parameter Component"
canvas: { width: 1440, height: 900 }
components:
  metric_picker:
    parameter: metric
    label: "Choose KPI"
root:
  orientation: vertical
  contains:
    - metric_picker
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["metric_picker"]
        assert isinstance(comp, ParameterComponent)
        assert comp.param == "metric"
        assert comp.label == "Choose KPI"

    def test_parameter_undefined_style_raises(self):
        yaml_str = """\
dashboard: "Bad Parameter Style"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - parameter: metric
      style: nonexistent
"""
        with pytest.raises((ValueError, KeyError)):
            parse_dashboard(yaml_str)

    def test_control_key_is_now_unknown(self):
        """SHE-97: the old `control:` key is an unknown type — no deprecation alias."""
        with pytest.raises((ValueError, KeyError)):
            resolve_child({"control": "metric"}, {})


# ─── Filter Component (SHE-79) ────────────────────────────────────────


class TestFilterComponent:
    """SHE-79: filter leaf component — schema parse/resolve/defaults + errors."""

    def test_filter_parses_with_defaults(self):
        entry = {"filter": "region", "model": "orders"}
        name, comp = resolve_child(entry, {})
        assert name is None
        assert isinstance(comp, FilterComponent)
        assert comp.type == "filter"
        assert comp.field == "region"
        assert comp.model == "orders"
        assert comp.targets == "all"
        assert comp.mode is None
        assert comp.default is None
        assert comp.label is None

    def test_filter_with_all_properties(self):
        entry = {
            "filter": "region",
            "model": "orders",
            "targets": ["sheet_a"],
            "mode": "multi",
            "default": "EMEA",
            "label": "Region Filter",
            "width": 200,
            "height": 40,
            "style": "card",
        }
        name, comp = resolve_child(entry, {})
        assert name is None
        assert isinstance(comp, FilterComponent)
        assert comp.field == "region"
        assert comp.model == "orders"
        assert comp.targets == ["sheet_a"]
        assert comp.mode == "multi"
        assert comp.default == "EMEA"
        assert comp.label == "Region Filter"
        assert comp.width == 200
        assert comp.height == 40
        assert comp.style == "card"

    def test_filter_in_dashboard_yaml(self):
        spec = parse_dashboard(load_layout_yaml("filter_dashboard.yaml"))
        assert spec.dashboard == "Filter Dashboard"
        assert len(spec.root.contains) == 2

    def test_filter_in_components_block(self):
        yaml_str = """\
dashboard: "Filter Component"
canvas: { width: 1440, height: 900 }
components:
  region_filter:
    filter: region
    model: orders
root:
  orientation: vertical
  contains:
    - region_filter
"""
        spec = parse_dashboard(yaml_str)
        assert spec.components is not None
        comp = spec.components["region_filter"]
        assert isinstance(comp, FilterComponent)
        assert comp.field == "region"
        assert comp.model == "orders"

    def test_filter_coexists_with_parameter(self):
        yaml_str = """\
dashboard: "Filter + Parameter"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - parameter: metric
    - filter: region
      model: orders
"""
        spec = parse_dashboard(yaml_str)
        assert len(spec.root.contains) == 2

    def test_parameter_controls_parse_unchanged(self):
        spec = parse_dashboard(load_layout_yaml("control_dashboard.yaml"))
        assert len(spec.root.contains) == 2

    # --- Edge cases ---

    def test_targets_all_explicit(self):
        entry = {"filter": "region", "model": "orders", "targets": "all"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, FilterComponent)
        assert comp.targets == "all"

    def test_targets_list(self):
        entry = {"filter": "region", "model": "orders", "targets": ["sheet_a"]}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, FilterComponent)
        assert comp.targets == ["sheet_a"]

    def test_default_null_explicit(self):
        entry = {"filter": "region", "model": "orders", "default": None}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, FilterComponent)
        assert comp.default is None

    def test_default_with_value(self):
        entry = {"filter": "region", "model": "orders", "default": "EMEA"}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, FilterComponent)
        assert comp.default == "EMEA"

    def test_filter_with_name(self):
        entry = {"filter": "region", "model": "orders", "name": "my_filter"}
        name, comp = resolve_child(entry, {})
        assert name == "my_filter"
        assert isinstance(comp, FilterComponent)

    def test_filter_with_html(self):
        entry = {"filter": "region", "model": "orders", "html": "border: 1px solid red;"}
        _, comp = resolve_child(entry, {})
        assert comp.html == "border: 1px solid red;"

    def test_mode_null_explicit(self):
        entry = {"filter": "region", "model": "orders", "mode": None}
        _, comp = resolve_child(entry, {})
        assert isinstance(comp, FilterComponent)
        assert comp.mode is None

    # --- Error cases ---

    def test_filter_missing_model_raises(self):
        with pytest.raises(ValidationError, match="model"):
            resolve_child({"filter": "region"}, {})

    def test_filter_empty_field_raises(self):
        with pytest.raises(ValidationError):
            resolve_child({"filter": "", "model": "orders"}, {})

    def test_filter_empty_model_raises(self):
        with pytest.raises(ValidationError):
            resolve_child({"filter": "region", "model": ""}, {})

    def test_filter_with_contains_raises(self):
        yaml_str = """\
dashboard: "Filter Contains"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - filter: region
      model: orders
      contains:
        - blank:
"""
        with pytest.raises(ValueError):
            parse_dashboard(yaml_str)

    def test_filter_invalid_mode_raises(self):
        with pytest.raises(ValidationError):
            resolve_child({"filter": "region", "model": "orders", "mode": "rnge"}, {})

    def test_filter_undefined_style_raises(self):
        yaml_str = """\
dashboard: "Bad Filter Style"
canvas: { width: 1440, height: 900 }
root:
  orientation: vertical
  contains:
    - filter: region
      model: orders
      style: nonexistent
"""
        with pytest.raises((ValueError, KeyError)):
            parse_dashboard(yaml_str)
