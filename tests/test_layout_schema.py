"""
Layout DSL Schema Tests

Tests parsing, validation, and child resolution for the Layout DSL.
"""

import pytest

from tests.conftest import load_layout_yaml
from src.schema.layout_schema import (
    parse_dashboard,
    resolve_child,
    SheetComponent,
)


# ─── Happy Path: Parsing ──────────────────────────────────────────


class TestLayoutParsing:
    def test_parse_minimal_dashboard(self):
        spec = parse_dashboard(load_layout_yaml("minimal.yaml"))
        assert spec.dashboard == "Minimal Dashboard"
        assert spec.canvas.width == 1440
        assert spec.canvas.height == 900
        assert spec.root.type == "root"
        assert spec.root.orientation == "vertical"
        assert len(spec.root.contains) == 1
        assert spec.styles is None
        assert spec.components is None

    def test_parse_kpi_dashboard(self):
        spec = parse_dashboard(load_layout_yaml("kpi_dashboard.yaml"))
        assert spec.dashboard == "Sales Overview"
        assert spec.description == "Weekly sales KPIs and revenue trends"
        assert spec.canvas.width == 1440
        assert spec.canvas.height == 900
        assert "card" in spec.styles
        assert spec.root.orientation == "vertical"
        assert len(spec.root.contains) == 3  # header, kpi_row, chart_row

    def test_parse_sidebar_dashboard(self):
        spec = parse_dashboard(load_layout_yaml("sidebar_dashboard.yaml"))
        assert spec.dashboard == "Executive Summary"
        assert spec.root.orientation == "horizontal"  # sidebar layout
        assert len(spec.root.contains) == 2  # sidebar + main
        assert "card" in spec.styles
        assert "nav_link" in spec.styles

    def test_parse_predefined_components(self):
        spec = parse_dashboard(load_layout_yaml("predefined_components.yaml"))
        assert spec.components is not None
        assert "kpi_revenue" in spec.components
        assert "kpi_orders" in spec.components
        assert "kpi_row" in spec.components
        assert spec.components["kpi_row"].type == "container"
        # root.contains has a string ref "kpi_row"
        assert "kpi_row" in spec.root.contains  # string ref

    def test_parse_three_child_shapes(self):
        yaml_str = """\
dashboard: "Child Shapes Test"
canvas: { width: 1440, height: 900 }

components:
  logo:
    type: image
    src: "assets/logo.svg"
    alt: "Logo"

root:
  type: root
  orientation: vertical
  contains:
    - logo
    - type: text
      content: "Sales Overview"
      preset: title
    - detail_nav:
        type: navigation
        text: "Details"
        link: "/detail"
"""
        spec = parse_dashboard(yaml_str)
        assert len(spec.root.contains) == 3
        # Element 0: string ref
        assert spec.root.contains[0] == "logo"
        # Element 1: inline anonymous dict with "type" key
        assert spec.root.contains[1]["type"] == "text"
        # Element 2: inline named dict with single key
        assert "detail_nav" in spec.root.contains[2]

    def test_parse_all_component_types(self):
        yaml_str = """\
dashboard: "All Types"
canvas: { width: 1440, height: 900 }
root:
  type: root
  orientation: vertical
  contains:
    - type: container
      orientation: horizontal
      contains:
        - type: sheet
          link: "charts/revenue.yaml"
        - type: text
          content: "Hello"
        - type: navigation
          text: "Go"
          link: "/go"
        - type: navigation_button
          text: "Click"
          link: "/click"
        - type: navigation_link
          text: "Link"
          link: "/link"
        - type: image
          src: "logo.svg"
        - type: blank
          width: 16
"""
        spec = parse_dashboard(yaml_str)
        # All 9 types (root, container, sheet, text, navigation,
        # navigation_button, navigation_link, image, blank) parse without error
        assert spec.root.type == "root"
        container = spec.root.contains[0]
        assert container["type"] == "container"


# ─── Happy Path: resolve_child ─────────────────────────────────────


class TestResolveChild:
    def test_resolve_child_string_ref(self):
        components = {"revenue": SheetComponent(type="sheet", link="charts/revenue.yaml")}
        name, defn = resolve_child("revenue", components)
        assert name == "revenue"
        assert defn.type == "sheet"
        assert defn.link == "charts/revenue.yaml"

    def test_resolve_child_inline_anonymous(self):
        node = {"type": "text", "content": "Hello", "preset": "title"}
        name, defn = resolve_child(node, {})
        assert name is None
        assert defn.type == "text"
        assert defn.content == "Hello"

    def test_resolve_child_inline_named(self):
        node = {"revenue_chart": {"type": "sheet", "link": "charts/revenue.yaml"}}
        name, defn = resolve_child(node, {})
        assert name == "revenue_chart"
        assert defn.type == "sheet"
        assert defn.link == "charts/revenue.yaml"

    def test_resolve_child_unknown_ref(self):
        with pytest.raises(KeyError):
            resolve_child("nonexistent", {})


# ─── Edge Cases ────────────────────────────────────────────────────


class TestLayoutEdgeCases:
    def test_canvas_defaults(self):
        yaml_str = """\
dashboard: "No Canvas"
root:
  type: root
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
  type: root
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
  type: root
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
  type: root
  orientation: vertical
  contains: []
"""
        spec = parse_dashboard(yaml_str)
        assert spec.description is None

    def test_integer_sizing(self):
        node = {"type": "sheet", "link": "charts/foo.yaml", "width": 300}
        _, defn = resolve_child(node, {})
        assert defn.width == 300

    def test_string_percentage_sizing(self):
        node = {"type": "sheet", "link": "charts/foo.yaml", "width": "50%"}
        _, defn = resolve_child(node, {})
        assert defn.width == "50%"

    def test_string_auto_sizing(self):
        node = {"type": "sheet", "link": "charts/foo.yaml", "width": "auto"}
        _, defn = resolve_child(node, {})
        assert defn.width == "auto"

    def test_padding_shorthand(self):
        node = {
            "type": "container",
            "orientation": "horizontal",
            "contains": [],
            "padding": "8 16 12 16",
        }
        _, defn = resolve_child(node, {})
        assert defn.padding == "8 16 12 16"

    def test_alt_defaults_to_empty(self):
        node = {"type": "image", "src": "logo.svg"}
        _, defn = resolve_child(node, {})
        assert defn.alt == ""

    def test_target_defaults_to_self(self):
        node = {"type": "navigation", "text": "Go", "link": "/go"}
        _, defn = resolve_child(node, {})
        assert defn.target == "_self"

    def test_extra_keys_on_components(self):
        node = {
            "type": "container",
            "orientation": "horizontal",
            "contains": [],
            "background": "#F00",
        }
        _, defn = resolve_child(node, {})
        assert defn.background == "#F00"


# ─── Validation / Error Tests ─────────────────────────────────────


class TestLayoutValidation:
    def test_missing_dashboard_name(self):
        yaml_str = """\
canvas: { width: 1440, height: 900 }
root:
  type: root
  orientation: vertical
  contains: []
"""
        with pytest.raises(Exception):
            parse_dashboard(yaml_str)

    def test_missing_root(self):
        yaml_str = """\
dashboard: "No Root"
canvas: { width: 1440, height: 900 }
"""
        with pytest.raises(Exception):
            parse_dashboard(yaml_str)

    def test_invalid_component_type(self):
        node = {"type": "chart", "link": "charts/foo.yaml"}
        with pytest.raises(ValueError):
            resolve_child(node, {})

    def test_invalid_preset(self):
        yaml_str = """\
dashboard: "Bad Preset"
canvas: { width: 1440, height: 900 }
root:
  type: root
  orientation: vertical
  contains:
    - type: text
      content: "Hello"
      preset: huge
"""
        with pytest.raises(Exception):
            parse_dashboard(yaml_str)

    def test_invalid_size_value(self):
        yaml_str = """\
dashboard: "Bad Size"
canvas: { width: 1440, height: 900 }
root:
  type: root
  orientation: vertical
  contains:
    - type: sheet
      link: "charts/foo.yaml"
      width: "wide"
"""
        with pytest.raises(ValueError):
            parse_dashboard(yaml_str)

    def test_style_ref_not_found(self):
        yaml_str = """\
dashboard: "Bad Style Ref"
canvas: { width: 1440, height: 900 }
root:
  type: root
  orientation: vertical
  contains:
    - type: sheet
      link: "charts/revenue.yaml"
      style: nonexistent_style
"""
        with pytest.raises(ValueError):
            parse_dashboard(yaml_str)

    def test_leaf_with_contains(self):
        yaml_str = """\
dashboard: "Leaf Contains"
canvas: { width: 1440, height: 900 }
root:
  type: root
  orientation: vertical
  contains:
    - type: text
      content: "Hello"
      contains:
        - type: blank
"""
        with pytest.raises(ValueError):
            parse_dashboard(yaml_str)
