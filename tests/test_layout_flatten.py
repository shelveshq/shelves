"""
Layout Flatten Tests

Tests the flatten phase that resolves all styles and component references
into a single resolved tree before the solver and renderer consume it.
"""

import warnings

from src.schema.layout_schema import parse_dashboard
from src.translator.layout_flatten import FlatNode, flatten_dashboard
from src.translator.layout_solver import solve_layout


# ─── Helpers ──────────────────────────────────────────────────────────


def _flatten(yaml_str: str) -> FlatNode:
    """Parse a YAML string and return the flattened tree."""
    return flatten_dashboard(parse_dashboard(yaml_str))


def _solve_flat(yaml_str: str):
    """Parse, flatten, and solve a dashboard YAML."""
    spec = parse_dashboard(yaml_str)
    flat = flatten_dashboard(spec)
    return solve_layout(flat)


# ─── Style Padding Applied ─────────────────────────────────────────────


class TestStylePaddingApplied:
    def test_style_padding_merges_onto_component(self):
        """After flatten, a sheet with a style that defines padding gets that padding."""
        yaml_str = """\
dashboard: "Style Padding"
canvas:
  width: 1000
  height: 800
styles:
  card:
    background: "#FFF"
    padding: 16
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      style: card
"""
        flat = _flatten(yaml_str)
        child = flat.children[0]
        assert child.component.padding == 16

    def test_style_padding_affects_solver_content_area(self):
        """Solver uses merged padding to compute content width."""
        yaml_str = """\
dashboard: "Style Padding"
canvas:
  width: 1000
  height: 800
styles:
  card:
    background: "#FFF"
    padding: 16
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      style: card
"""
        tree = _solve_flat(yaml_str)
        child = tree.children[0]
        # outer_width = 1000, content = 1000 - 32 = 968
        assert child.outer_width == 1000
        assert child.content_width == 968

    def test_style_visual_prop_in_origins(self):
        """Background and padding from style are tracked with source='style'."""
        yaml_str = """\
dashboard: "Style Padding"
canvas:
  width: 1000
  height: 800
styles:
  card:
    background: "#FFF"
    padding: 16
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      style: card
"""
        flat = _flatten(yaml_str)
        child = flat.children[0]
        assert child.origins["background"].source == "style"
        assert child.origins["background"].style_name == "card"
        assert child.origins["padding"].source == "style"


# ─── Inline Override ────────────────────────────────────────────────────


class TestInlinePaddingOverride:
    _YAML = """\
dashboard: "Override"
canvas:
  width: 1000
  height: 800
styles:
  card:
    padding: 10
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      style: card
      padding: 20
"""

    def test_inline_padding_wins_over_style(self):
        """When both style and inline define padding, inline value wins."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            flat = _flatten(self._YAML)
        assert flat.children[0].component.padding == 20

    def test_inline_override_emits_warning(self):
        """Inline override of style property emits a warning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _flatten(self._YAML)
        assert any("padding" in str(w.message) for w in caught)

    def test_inline_override_origin_is_inline(self):
        """When inline wins, origin source is 'inline'."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            flat = _flatten(self._YAML)
        origin = flat.children[0].origins["padding"]
        assert origin.source == "inline"
        assert origin.value == 20


# ─── Style Margin ───────────────────────────────────────────────────────


class TestStyleMargin:
    _YAML = """\
dashboard: "Style Margin"
canvas:
  width: 1000
  height: 800
styles:
  spaced:
    margin: "0 8 0 0"
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      style: spaced
    - sheet: charts/b.yaml
"""

    def test_style_margin_merges_onto_component(self):
        """After flatten, component gets margin from style."""
        flat = _flatten(self._YAML)
        assert flat.children[0].component.margin == "0 8 0 0"

    def test_style_margin_affects_distribution(self):
        """Margin from style is used in solver distribution."""
        tree = _solve_flat(self._YAML)
        # distributable = 1000 - 8 (right margin of first child) = 992
        # two auto children: 496 each
        assert tree.children[0].outer_width == 496
        assert tree.children[1].outer_width == 496


# ─── Both Padding and Margin ────────────────────────────────────────────


class TestPaddingAndMarginCombined:
    _YAML = """\
dashboard: "Both"
canvas:
  width: 1000
  height: 800
styles:
  card:
    background: "#FFF"
    padding: 12
    margin: 8
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      style: card
"""

    def test_both_merged_onto_component(self):
        """Style with both padding and margin — both get merged."""
        flat = _flatten(self._YAML)
        child = flat.children[0]
        assert child.component.padding == 12
        assert child.component.margin == 8

    def test_solver_math_with_margin_and_padding(self):
        """Margin 8 all sides → distributable 1000-16=984. Content = 984-24=960."""
        tree = _solve_flat(self._YAML)
        child = tree.children[0]
        # outer = 1000 - 16 (margin left+right) = 984
        assert child.outer_width == 984
        # content = 984 - 24 (padding left+right) = 960
        assert child.content_width == 960


# ─── Origin Tracking ────────────────────────────────────────────────────


class TestOriginTracking:
    _YAML = """\
dashboard: "Origin"
canvas:
  width: 1000
  height: 800
styles:
  card:
    background: "#FFF"
    padding: 10
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      style: card
      padding: 20
"""

    def test_style_prop_origin_is_style(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            flat = _flatten(self._YAML)
        child = flat.children[0]
        bg = child.origins["background"]
        assert bg.source == "style"
        assert bg.style_name == "card"

    def test_inline_prop_origin_is_inline(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            flat = _flatten(self._YAML)
        child = flat.children[0]
        pad = child.origins["padding"]
        assert pad.source == "inline"

    def test_origin_values_correct(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            flat = _flatten(self._YAML)
        child = flat.children[0]
        assert child.origins["padding"].value == 20
        assert child.origins["background"].value == "#FFF"


# ─── Predefined Components ──────────────────────────────────────────────


class TestPredefinedComponentWithStyle:
    _YAML = """\
dashboard: "Predefined"
canvas:
  width: 1000
  height: 800
styles:
  card:
    padding: 8
components:
  kpi:
    sheet: charts/kpi.yaml
    style: card
root:
  orientation: horizontal
  contains:
    - kpi
    - kpi
"""

    def test_predefined_component_gets_style_padding(self):
        """Predefined components referenced multiple times each get style padding."""
        flat = _flatten(self._YAML)
        assert flat.children[0].component.padding == 8
        assert flat.children[1].component.padding == 8

    def test_predefined_instances_are_independent_copies(self):
        """Each instance of a predefined component is an independent copy."""
        flat = _flatten(self._YAML)
        assert flat.children[0].component is not flat.children[1].component


# ─── No Style Ref — Unchanged Behavior ─────────────────────────────────


class TestNoStyleRef:
    def test_component_without_style_has_empty_origins(self):
        """Components without a style ref get no merging and empty origins."""
        yaml_str = """\
dashboard: "No Style"
canvas:
  width: 1000
  height: 800
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
      padding: 16
"""
        flat = _flatten(yaml_str)
        child = flat.children[0]
        assert child.component.padding == 16
        assert child.origins == {}

    def test_no_style_solver_unchanged(self):
        """Solver behavior is unchanged for components without styles."""
        yaml_str = """\
dashboard: "No Style"
canvas:
  width: 1000
  height: 800
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
"""
        tree = _solve_flat(yaml_str)
        assert tree.children[0].outer_width == 1000
        assert tree.children[0].content_width == 1000


# ─── Root With Style ────────────────────────────────────────────────────


class TestRootWithStyle:
    _YAML = """\
dashboard: "Root Style"
canvas:
  width: 1000
  height: 800
styles:
  padded:
    padding: 24
root:
  orientation: vertical
  style: padded
  contains:
    - text: "Hello"
"""

    def test_root_gets_padding_from_style(self):
        """Root component gets padding from its style reference."""
        flat = _flatten(self._YAML)
        assert flat.component.padding == 24

    def test_root_style_padding_affects_content_area(self):
        """Root's style-merged padding shrinks content area."""
        tree = _solve_flat(self._YAML)
        # content = 1000-48 x 800-48
        assert tree.content_width == 952
        assert tree.content_height == 752
