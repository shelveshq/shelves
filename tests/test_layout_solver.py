"""
Layout Solver Tests — Type-Led Syntax

Tests the layout solver that resolves DSL sizes to concrete pixel dimensions.
The solver implements border-box semantics, three-bucket distribution
(% → px → auto), gap subtraction, and overconstrained handling.

These tests define expected behavior for the implementation to follow.
"""

import warnings

from src.schema.layout_schema import parse_dashboard
from src.translator.layout_flatten import flatten_dashboard
from src.translator.layout_solver import (
    parse_spacing,
    solve_layout,
)


# ─── Helpers ────────────────────────────────────────────────────────


def _solve(yaml_str: str):
    """Parse, flatten, and solve a dashboard YAML, return the resolved tree."""
    spec = parse_dashboard(yaml_str)
    return solve_layout(flatten_dashboard(spec))


def _simple_dashboard(
    orientation: str = "vertical",
    contains_yaml: str = "",
    gap: int = 0,
    padding: int | str = 0,
    margin: int | str = 0,
    canvas_w: int = 1000,
    canvas_h: int = 800,
) -> str:
    """Build a minimal dashboard YAML string."""
    gap_line = f"  gap: {gap}" if gap else ""
    padding_line = (
        f'  padding: "{padding}"'
        if isinstance(padding, str)
        else (f"  padding: {padding}" if padding else "")
    )
    margin_line = (
        f'  margin: "{margin}"'
        if isinstance(margin, str)
        else (f"  margin: {margin}" if margin else "")
    )
    return f"""\
dashboard: "Test"
canvas:
  width: {canvas_w}
  height: {canvas_h}
root:
  orientation: {orientation}
{gap_line}
{padding_line}
{margin_line}
  contains:
{contains_yaml}
"""


# ─── Spacing Parsing ────────────────────────────────────────────────


class TestParseSpacing:
    def test_none_returns_zeros(self):
        assert parse_spacing(None) == (0, 0, 0, 0)

    def test_single_int(self):
        assert parse_spacing(16) == (16, 16, 16, 16)

    def test_two_values(self):
        assert parse_spacing("8 16") == (8, 16, 8, 16)

    def test_four_values(self):
        assert parse_spacing("8 16 12 24") == (8, 16, 12, 24)

    def test_single_string_int(self):
        assert parse_spacing("16") == (16, 16, 16, 16)

    def test_zero(self):
        assert parse_spacing(0) == (0, 0, 0, 0)

    def test_invalid_three_values_raises(self):
        import pytest

        with pytest.raises(ValueError):
            parse_spacing("8 16 12")


# ─── Root Resolution ────────────────────────────────────────────────


class TestRootResolution:
    def test_root_no_margin_no_padding(self):
        tree = _solve(_simple_dashboard())
        assert tree.outer_width == 1000
        assert tree.outer_height == 800
        assert tree.content_width == 1000
        assert tree.content_height == 800

    def test_root_with_padding(self):
        tree = _solve(_simple_dashboard(padding=24))
        assert tree.outer_width == 1000
        assert tree.outer_height == 800
        assert tree.content_width == 952  # 1000 - 48
        assert tree.content_height == 752  # 800 - 48

    def test_root_with_margin(self):
        tree = _solve(_simple_dashboard(margin=16))
        assert tree.outer_width == 968  # 1000 - 32
        assert tree.outer_height == 768  # 800 - 32
        assert tree.content_width == 968
        assert tree.content_height == 768

    def test_root_with_margin_and_padding(self):
        tree = _solve(_simple_dashboard(margin=16, padding=24))
        assert tree.outer_width == 968
        assert tree.outer_height == 768
        assert tree.content_width == 920  # 968 - 48
        assert tree.content_height == 720  # 768 - 48

    def test_root_asymmetric_margin(self):
        tree = _solve(_simple_dashboard(margin="10 20 30 40"))
        # left+right = 60, top+bottom = 40
        assert tree.outer_width == 940
        assert tree.outer_height == 760

    def test_root_two_value_padding(self):
        tree = _solve(_simple_dashboard(padding="10 20"))
        # left+right = 40, top+bottom = 20
        assert tree.content_width == 960
        assert tree.content_height == 780


# ─── Basic Container Distribution (No Gap) ──────────────────────────


class TestContainerDistribution:
    def test_single_auto_child_fills_space(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="    - sheet: charts/a.yaml",
            )
        )
        child = tree.children[0]
        assert child.outer_width == 1000
        assert child.outer_height == 800

    def test_two_auto_children_split_equally(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml""",
            )
        )
        assert tree.children[0].outer_width == 500
        assert tree.children[1].outer_width == 500
        assert tree.children[0].outer_height == 800
        assert tree.children[1].outer_height == 800

    def test_three_auto_children_rounding(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml
    - sheet: charts/c.yaml""",
            )
        )
        total = sum(c.outer_width for c in tree.children)
        assert total == 1000  # no pixels lost

    def test_fixed_px_child(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 300
    - sheet: charts/b.yaml""",
            )
        )
        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 700

    def test_two_fixed_children(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 300
    - sheet: charts/b.yaml
      width: 400""",
            )
        )
        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 400

    def test_percentage_child(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "60%"
    - sheet: charts/b.yaml""",
            )
        )
        assert tree.children[0].outer_width == 600
        assert tree.children[1].outer_width == 400

    def test_two_percentages(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "60%"
    - sheet: charts/b.yaml
      width: "40%\"""",
            )
        )
        assert tree.children[0].outer_width == 600
        assert tree.children[1].outer_width == 400

    def test_percentage_and_fixed_and_auto(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "50%"
    - sheet: charts/b.yaml
      width: 200
    - sheet: charts/c.yaml""",
            )
        )
        assert tree.children[0].outer_width == 500
        assert tree.children[1].outer_width == 200
        assert tree.children[2].outer_width == 300

    def test_vertical_orientation(self):
        tree = _solve(
            _simple_dashboard(
                orientation="vertical",
                contains_yaml="""\
    - sheet: charts/a.yaml
      height: 56
    - sheet: charts/b.yaml""",
            )
        )
        assert tree.children[0].outer_height == 56
        assert tree.children[1].outer_height == 744
        assert tree.children[0].outer_width == 1000
        assert tree.children[1].outer_width == 1000


# ─── Gap Distribution ───────────────────────────────────────────────


class TestGapDistribution:
    """Gap is subtracted from distributable space as gap × (N-1)."""

    def test_gap_between_two_auto_children(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=16,
                contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml""",
            )
        )
        # distributable = 1000 - 16 = 984, split: 492 each
        assert tree.children[0].outer_width == 492
        assert tree.children[1].outer_width == 492

    def test_gap_between_three_children(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=16,
                contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml
    - sheet: charts/c.yaml""",
            )
        )
        # total_gap = 16 * 2 = 32
        # distributable = 1000 - 32 = 968
        total = sum(c.outer_width for c in tree.children)
        assert total == 968

    def test_gap_with_fixed_children(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=16,
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 300
    - sheet: charts/b.yaml""",
            )
        )
        # distributable = 1000 - 16 = 984
        # fixed claims 300, auto gets 684
        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 684

    def test_gap_with_percentage(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=16,
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "60%"
    - sheet: charts/b.yaml""",
            )
        )
        # 60% of 1000 (content box) = 600
        # distributable = 1000 - 16 = 984
        # auto = 984 - 600 = 384
        assert tree.children[0].outer_width == 600
        assert tree.children[1].outer_width == 384

    def test_gap_in_vertical_container(self):
        tree = _solve(
            _simple_dashboard(
                orientation="vertical",
                gap=20,
                contains_yaml="""\
    - sheet: charts/a.yaml
      height: 56
    - sheet: charts/b.yaml""",
            )
        )
        # distributable = 800 - 20 = 780
        # header claims 56, body gets 724
        assert tree.children[0].outer_height == 56
        assert tree.children[1].outer_height == 724

    def test_gap_exceeds_available_space_warns(self):
        """When total gap exceeds available space, solver should warn."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # 4 children → 3 gaps → 3 × 400 = 1200 > 1000 available
            _solve(
                _simple_dashboard(
                    orientation="horizontal",
                    gap=400,
                    contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml
    - sheet: charts/c.yaml
    - sheet: charts/d.yaml""",
                )
            )
            warning_msgs = [str(x.message).lower() for x in w]
            assert any("gap" in msg for msg in warning_msgs)

    def test_gap_single_child_no_effect(self):
        """Gap with one child: gap × 0 = 0, no effect."""
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=16,
                contains_yaml="    - sheet: charts/a.yaml",
            )
        )
        assert tree.children[0].outer_width == 1000

    def test_gap_in_nested_container(self):
        yaml_str = """\
dashboard: "Nested Gap"
canvas: { width: 1000, height: 800 }
root:
  orientation: vertical
  gap: 20
  contains:
    - horizontal:
        height: 100
        gap: 16
        contains:
          - sheet: charts/a.yaml
          - sheet: charts/b.yaml
          - sheet: charts/c.yaml
    - sheet: charts/d.yaml
"""
        tree = _solve(yaml_str)

        header = tree.children[0]
        body = tree.children[1]

        # root distributable vertical: 800 - 20 = 780
        assert header.outer_height == 100
        assert body.outer_height == 680  # 780 - 100

        # header children: 3 auto with gap 16
        # total_gap = 16 * 2 = 32, distributable = 1000 - 32 = 968
        total_w = sum(c.outer_width for c in header.children)
        assert total_w == 968

    def test_gap_zero_is_same_as_omitted(self):
        with_gap = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=0,
                contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml""",
            )
        )
        without_gap = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml""",
            )
        )
        assert with_gap.children[0].outer_width == without_gap.children[0].outer_width


# ─── Margins in Distribution ────────────────────────────────────────


class TestMarginsInDistribution:
    def test_child_margins_subtracted(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      margin: "0 8 0 0"
    - sheet: charts/b.yaml""",
            )
        )
        # distributable = 1000 - 8 = 992, split: 496 each
        assert tree.children[0].outer_width == 496
        assert tree.children[1].outer_width == 496

    def test_margins_with_gap(self):
        """Gap and margins both subtract from distributable."""
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=16,
                contains_yaml="""\
    - sheet: charts/a.yaml
      margin: "0 8 0 0"
    - sheet: charts/b.yaml""",
            )
        )
        # distributable = 1000 - 16 (gap) - 8 (margin) = 976, split: 488 each
        assert tree.children[0].outer_width == 488
        assert tree.children[1].outer_width == 488

    def test_margins_in_vertical(self):
        tree = _solve(
            _simple_dashboard(
                orientation="vertical",
                contains_yaml="""\
    - sheet: charts/a.yaml
      height: 56
      margin: "0 0 16 0"
    - sheet: charts/b.yaml""",
            )
        )
        # distributable = 800 - 16 = 784
        assert tree.children[0].outer_height == 56
        assert tree.children[1].outer_height == 728  # 784 - 56


# ─── Padding and Content Areas ──────────────────────────────────────


class TestPaddingAndContentAreas:
    def test_child_padding_shrinks_content(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      padding: 16""",
            )
        )
        child = tree.children[0]
        assert child.outer_width == 1000
        assert child.content_width == 968  # 1000 - 32
        assert child.content_height == 768  # 800 - 32

    def test_container_padding_then_child(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                padding=20,
                contains_yaml="    - sheet: charts/a.yaml",
            )
        )
        # Root content: 960 × 760
        child = tree.children[0]
        assert child.outer_width == 960
        assert child.outer_height == 760

    def test_asymmetric_padding(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      padding: "10 20 30 40\"""",
            )
        )
        child = tree.children[0]
        assert child.content_width == 940  # 1000 - 60 (left 40 + right 20)
        assert child.content_height == 760  # 800 - 40 (top 10 + bottom 30)


# ─── Cross-Axis Resolution ──────────────────────────────────────────


class TestCrossAxis:
    def test_default_cross_axis_fills_parent(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 500""",
            )
        )
        assert tree.children[0].outer_height == 800

    def test_explicit_cross_axis_px(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 500
      height: 300""",
            )
        )
        assert tree.children[0].outer_height == 300

    def test_explicit_cross_axis_percentage(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 500
      height: "50%\"""",
            )
        )
        assert tree.children[0].outer_height == 400

    def test_vertical_cross_axis(self):
        tree = _solve(
            _simple_dashboard(
                orientation="vertical",
                contains_yaml="""\
    - sheet: charts/a.yaml
      height: 200
      width: 600""",
            )
        )
        assert tree.children[0].outer_width == 600


# ─── Nested Containers ──────────────────────────────────────────────


class TestNestedContainers:
    def test_nested_container(self):
        yaml_str = """\
dashboard: "Nested"
canvas: { width: 1000, height: 800 }
root:
  orientation: vertical
  contains:
    - horizontal:
        height: 100
        contains:
          - blank:
            width: 100
    - horizontal:
        contains:
          - sheet: charts/a.yaml
          - sheet: charts/b.yaml
"""
        tree = _solve(yaml_str)

        header = tree.children[0]
        inner = tree.children[1]

        assert header.outer_height == 100
        assert inner.outer_height == 700  # 800 - 100
        assert inner.children[0].outer_width == 500
        assert inner.children[1].outer_width == 500

    def test_deeply_nested(self):
        yaml_str = """\
dashboard: "Deep"
canvas: { width: 1000, height: 800 }
root:
  orientation: vertical
  contains:
    - horizontal:
        contains:
          - vertical:
              width: "50%"
              padding: 10
              contains:
                - sheet: charts/a.yaml
                  height: 100
          - sheet: charts/b.yaml
"""
        tree = _solve(yaml_str)

        level1 = tree.children[0]
        level2 = level1.children[0]
        deep_sheet = level2.children[0]

        assert level1.outer_width == 1000
        assert level1.outer_height == 800

        assert level2.outer_width == 500
        assert level2.content_width == 480  # 500 - 20
        assert level2.content_height == 780  # 800 - 20

        assert deep_sheet.outer_height == 100
        assert deep_sheet.outer_width == 480


# ─── Overconstrained Layouts ────────────────────────────────────────


class TestOverconstrained:
    def test_fixed_children_exceed_space(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 700
    - sheet: charts/b.yaml
      width: 500""",
            )
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = _solve(
                _simple_dashboard(
                    orientation="horizontal",
                    contains_yaml="""\
    - sheet: charts/a.yaml
      width: 700
    - sheet: charts/b.yaml
      width: 500""",
                )
            )
            assert len(w) >= 1

        total = tree.children[0].outer_width + tree.children[1].outer_width
        assert total == 1000
        assert tree.children[0].outer_width > tree.children[1].outer_width

    def test_percentage_plus_fixed_exceeds(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = _solve(
                _simple_dashboard(
                    orientation="horizontal",
                    contains_yaml="""\
    - sheet: charts/a.yaml
      width: "60%"
    - sheet: charts/b.yaml
      width: 600""",
                )
            )
            assert len(w) >= 1

        # Percentage honored first
        assert tree.children[0].outer_width == 600
        assert tree.children[1].outer_width == 400

    def test_percentages_exceed_100(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = _solve(
                _simple_dashboard(
                    orientation="horizontal",
                    contains_yaml="""\
    - sheet: charts/a.yaml
      width: "70%"
    - sheet: charts/b.yaml
      width: "50%\"""",
                )
            )
            assert len(w) >= 1

        total = tree.children[0].outer_width + tree.children[1].outer_width
        assert total == 1000
        assert tree.children[0].outer_width > tree.children[1].outer_width

    def test_auto_child_gets_zero_when_fully_claimed(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = _solve(
                _simple_dashboard(
                    orientation="horizontal",
                    contains_yaml="""\
    - sheet: charts/a.yaml
      width: 1000
    - sheet: charts/b.yaml""",
                )
            )
            warning_msgs = [str(x.message).lower() for x in w]
            assert any("0px" in msg or "0 px" in msg or "zero" in msg for msg in warning_msgs)

        assert tree.children[0].outer_width == 1000
        assert tree.children[1].outer_width == 0

    def test_overconstrained_with_gap(self):
        """Gap makes it easier to overconstrain."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = _solve(
                _simple_dashboard(
                    orientation="horizontal",
                    gap=16,
                    contains_yaml="""\
    - sheet: charts/a.yaml
      width: 500
    - sheet: charts/b.yaml
      width: 500""",
                )
            )
            # 500 + 500 = 1000, but distributable is 1000 - 16 = 984
            assert len(w) >= 1

        total = tree.children[0].outer_width + tree.children[1].outer_width
        assert total == 984


# ─── Negative Content Area ──────────────────────────────────────────


class TestNegativeContentArea:
    def test_padding_exceeds_size(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = _solve(
                _simple_dashboard(
                    orientation="horizontal",
                    contains_yaml="""\
    - sheet: charts/a.yaml
      width: 20
      padding: 50
    - sheet: charts/b.yaml""",
                )
            )
            warning_msgs = [str(x.message).lower() for x in w]
            assert any("padding" in msg or "clamp" in msg for msg in warning_msgs)

        child = tree.children[0]
        assert child.outer_width == 20
        assert child.content_width == 0


# ─── Edge Cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_container(self):
        tree = _solve(_simple_dashboard())
        assert tree.outer_width == 1000
        assert tree.children == []

    def test_single_fixed_smaller_than_container(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 200""",
            )
        )
        assert tree.children[0].outer_width == 200

    def test_pixel_string_equivalent_to_int(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "300px"
    - sheet: charts/b.yaml""",
            )
        )
        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 700

    def test_auto_string_equivalent_to_omitted(self):
        tree1 = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "auto"
    - sheet: charts/b.yaml""",
            )
        )
        tree2 = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
    - sheet: charts/b.yaml""",
            )
        )
        assert tree1.children[0].outer_width == tree2.children[0].outer_width

    def test_zero_dimension_canvas(self):
        tree = _solve("""\
dashboard: "Zero"
canvas: { width: 0, height: 600 }
root:
  orientation: horizontal
  contains:
    - sheet: charts/a.yaml
""")
        assert tree.outer_width == 0
        assert tree.children[0].outer_width == 0

    def test_leaf_types_have_no_children(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
    - text: "hello"
    - blank:
      width: 10""",
            )
        )
        for child in tree.children:
            assert child.children == []

    def test_blank_spacer_gets_auto_share(self):
        """Blank with no size acts as auto — gets equal share."""
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 300
    - blank:
    - sheet: charts/b.yaml
      width: 300""",
            )
        )
        # distributable = 1000, fixed = 600, blank gets 400
        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 400
        assert tree.children[2].outer_width == 300


# ─── ResolvedNode Structure ──────────────────────────────────────────


class TestResolvedNodeStructure:
    def test_resolved_node_has_required_fields(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 400
      padding: 10""",
            )
        )
        # Root
        assert tree.name is None
        assert tree.component is not None
        assert isinstance(tree.outer_width, int)
        assert isinstance(tree.children, list)

        # Child
        child = tree.children[0]
        assert child.outer_width == 400
        assert child.content_width == 380  # 400 - 20


# ─── Percentage Resolves Against Content Box ────────────────────────


class TestPercentageResolution:
    def test_percentage_ignores_sibling_margins(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "60%"
    - sheet: charts/b.yaml
      margin: "0 0 0 20\"""",
            )
        )
        # 60% of 1000 = 600
        assert tree.children[0].outer_width == 600
        # distributable = 1000 - 20 = 980; auto = 980 - 600 = 380
        assert tree.children[1].outer_width == 380

    def test_percentage_with_container_padding(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                padding=50,
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "50%"
    - sheet: charts/b.yaml""",
            )
        )
        # Root content: 900; 50% of 900 = 450
        assert tree.children[0].outer_width == 450
        assert tree.children[1].outer_width == 450

    def test_percentage_with_gap(self):
        """Percentage resolves against content box, not distributable (post-gap)."""
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                gap=100,
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "60%"
    - sheet: charts/b.yaml""",
            )
        )
        # 60% of 1000 = 600 (percentage against content box)
        # distributable = 1000 - 100 = 900; auto = 900 - 600 = 300
        assert tree.children[0].outer_width == 600
        assert tree.children[1].outer_width == 300


# ─── Mixed Bucket Combinations ──────────────────────────────────────


class TestMixedBuckets:
    def test_pct_fixed_auto(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "50%"
    - sheet: charts/b.yaml
      width: 200
    - sheet: charts/c.yaml""",
            )
        )
        assert tree.children[0].outer_width == 500
        assert tree.children[1].outer_width == 200
        assert tree.children[2].outer_width == 300

    def test_multiple_auto_with_fixed(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: 300
    - sheet: charts/b.yaml
    - sheet: charts/c.yaml""",
            )
        )
        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 350
        assert tree.children[2].outer_width == 350

    def test_all_percentages_exactly_100(self):
        tree = _solve(
            _simple_dashboard(
                orientation="horizontal",
                contains_yaml="""\
    - sheet: charts/a.yaml
      width: "25%"
    - sheet: charts/b.yaml
      width: "50%"
    - sheet: charts/c.yaml
      width: "25%\"""",
            )
        )
        assert tree.children[0].outer_width == 250
        assert tree.children[1].outer_width == 500
        assert tree.children[2].outer_width == 250


# ─── Integration: Worked Example from Spec ──────────────────────────


class TestWorkedExample:
    """Reproduces the worked example from the Layout DSL spec §9.3."""

    def test_spec_worked_example(self):
        yaml_str = """\
dashboard: "Test Dashboard"
canvas:
  width: 1440
  height: 900

root:
  orientation: vertical
  padding: 24
  gap: 16
  contains:
    - horizontal:
        height: 56
        padding: "0 16"
        gap: 12
        contains:
          - image: logo.svg
            width: 120
            height: 28
          - text: "Dashboard"
            preset: title
          - blank:
          - button: "Details →"
            href: "/detail"
            width: 140
            padding: "6 16"
    - horizontal:
        padding: 16
        gap: 16
        contains:
          - sheet: charts/revenue.yaml
            width: "60%"
            padding: 16
          - sheet: charts/orders.yaml
            padding: 16
"""
        tree = _solve(yaml_str)

        # Root
        assert tree.outer_width == 1440
        assert tree.outer_height == 900
        assert tree.content_width == 1392  # 1440 - 48
        assert tree.content_height == 852  # 900 - 48

        # Header: height 56, fills width
        header = tree.children[0]
        assert header.outer_height == 56
        assert header.outer_width == 1392
        assert header.content_width == 1360  # 1392 - 32

        # Header children
        logo = header.children[0]
        text = header.children[1]
        blank = header.children[2]
        nav = header.children[3]

        assert logo.outer_width == 120
        assert logo.outer_height == 28
        assert nav.outer_width == 140
        assert nav.content_width == 108  # 140 - 32
        assert nav.content_height == 44  # 56 - 12

        # text and blank are auto
        # gap = 12 * 3 = 36
        # distributable = 1360 - 36 = 1324
        # fixed: 120 + 140 = 260
        # auto: (1324 - 260) / 2 = 532
        assert text.outer_width == 532
        assert blank.outer_width == 532

        # Chart row: auto height
        # root gap = 16 * 1 = 16
        # distributable_h = 852 - 16 = 836
        # header claims 56, chart_row = 836 - 56 = 780
        chart_row = tree.children[1]
        assert chart_row.outer_height == 780
        assert chart_row.content_width == 1360  # 1392 - 32
        assert chart_row.content_height == 748  # 780 - 32

        # Chart row children: gap=16, 60% + auto
        # gap = 16 * 1 = 16
        # distributable = 1360 - 16 = 1344
        # revenue: 60% of 1360 = 816
        # orders: 1344 - 816 = 528
        main = chart_row.children[0]
        side = chart_row.children[1]

        assert main.outer_width == 816
        assert main.content_width == 784  # 816 - 32
        assert side.outer_width == 528
        assert side.content_width == 496  # 528 - 32


# ─── Full Dashboard YAML Integration ────────────────────────────────


class TestFullDashboardIntegration:
    def test_kpi_dashboard_layout(self):
        yaml_str = """\
dashboard: "Sales"
canvas: { width: 1200, height: 800 }
root:
  orientation: vertical
  padding: 16
  gap: 8
  contains:
    - horizontal:
        height: 48
        contains:
          - text: "Sales Dashboard"
            preset: title
    - horizontal:
        height: 120
        gap: 8
        contains:
          - sheet: charts/kpi1.yaml
          - sheet: charts/kpi2.yaml
          - sheet: charts/kpi3.yaml
    - horizontal:
        gap: 8
        contains:
          - sheet: charts/main.yaml
            width: "65%"
          - sheet: charts/side.yaml
"""
        tree = _solve(yaml_str)

        # Root content: 1168 × 768
        assert tree.content_width == 1168
        assert tree.content_height == 768

        header = tree.children[0]
        kpi_row = tree.children[1]
        chart_area = tree.children[2]

        assert header.outer_height == 48
        assert kpi_row.outer_height == 120

        # Chart area: 768 - gap(8*2) - 48 - 120 = 768 - 16 - 168 = 584
        assert chart_area.outer_height == 584

        # KPI children: 3 auto with gap 8
        # gap = 8 * 2 = 16, distributable = 1168 - 16 = 1152
        total_kpi = sum(c.outer_width for c in kpi_row.children)
        assert total_kpi == 1152

    def test_sidebar_layout(self):
        yaml_str = """\
dashboard: "Executive"
canvas: { width: 1440, height: 900 }
root:
  orientation: horizontal
  contains:
    - vertical:
        width: 220
        padding: "24 16"
        contains:
          - text: "Menu"
            preset: heading
    - vertical:
        padding: 24
        contains:
          - text: "Content"
            preset: title
"""
        tree = _solve(yaml_str)

        sidebar = tree.children[0]
        main = tree.children[1]

        assert sidebar.outer_width == 220
        assert sidebar.outer_height == 900
        assert sidebar.content_width == 188  # 220 - 32

        assert main.outer_width == 1220  # 1440 - 220
        assert main.outer_height == 900
        assert main.content_width == 1172  # 1220 - 48

    def test_component_refs_in_layout(self):
        yaml_str = """\
dashboard: "Components"
canvas: { width: 1000, height: 800 }

components:
  kpi:
    sheet: charts/kpi.yaml
    style: card
    padding: 8

root:
  orientation: vertical
  gap: 16
  contains:
    - horizontal:
        height: 120
        gap: 16
        contains:
          - kpi
          - kpi
          - kpi
    - sheet: charts/main.yaml
"""
        tree = _solve(yaml_str)

        kpi_row = tree.children[0]
        assert kpi_row.outer_height == 120

        # 3 children with gap 16: gap = 32, distributable = 1000 - 32 = 968
        total = sum(c.outer_width for c in kpi_row.children)
        assert total == 968

        # Each KPI has padding 8: content = outer - 16
        for kpi in kpi_row.children:
            assert kpi.content_width == kpi.outer_width - 16
