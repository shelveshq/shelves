"""
Layout Solver Tests

Tests the layout solver that resolves DSL sizes to concrete pixel dimensions.
The solver implements the v2 sizing model: border-box semantics, three-bucket
distribution (% → px → auto), and overconstrained handling.

These tests cover:
- Margin/padding parsing helpers
- Root resolution (canvas → content box)
- Container resolution (three-bucket algorithm)
- Cross-axis resolution
- Nested container recursion
- Overconstrained layouts (warnings, proportional shrinking)
- Edge cases (zero-size, negative content, single child, etc.)
"""

import warnings

from src.schema.layout_schema import (
    Canvas,
    DashboardSpec,
    RootComponent,
    parse_dashboard,
)
from src.translator.layout_solver import (
    parse_spacing,
    solve_layout,
)


# ─── Helpers ────────────────────────────────────────────────────────


def _minimal_dashboard(**root_kwargs) -> DashboardSpec:
    """Build a minimal DashboardSpec with custom root kwargs."""
    defaults = {
        "type": "root",
        "orientation": "vertical",
        "contains": [],
    }
    defaults.update(root_kwargs)
    return DashboardSpec(
        dashboard="Test",
        canvas=Canvas(width=1000, height=800),
        root=RootComponent(**defaults),
    )


def _sheet(name: str = "s", **kwargs) -> dict:
    """Build an inline named sheet child for contains list."""
    defaults = {"type": "sheet", "link": "charts/test.yaml"}
    defaults.update(kwargs)
    return {name: defaults}


def _blank(**kwargs) -> dict:
    """Build an inline anonymous blank child for contains list."""
    return {"type": "blank", **kwargs}


def _text(content: str = "hello", **kwargs) -> dict:
    """Build an inline anonymous text child for contains list."""
    return {"type": "text", "content": content, **kwargs}


def _container(orientation: str, contains: list, **kwargs) -> dict:
    """Build an inline anonymous container child for contains list."""
    return {"type": "container", "orientation": orientation, "contains": contains, **kwargs}


def _named_container(name: str, orientation: str, contains: list, **kwargs) -> dict:
    """Build an inline named container child for contains list."""
    inner = {"type": "container", "orientation": orientation, "contains": contains, **kwargs}
    return {name: inner}


# ─── Spacing Parsing ────────────────────────────────────────────────


class TestParseSpacing:
    """Tests for parse_spacing() which converts DSL margin/padding values
    to (top, right, bottom, left) pixel tuples."""

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

    def test_string_zero(self):
        assert parse_spacing("0") == (0, 0, 0, 0)


# ─── Root Resolution ────────────────────────────────────────────────


class TestRootResolution:
    """Tests for how the root element resolves against the canvas."""

    def test_root_no_margin_no_padding(self):
        """Root with no margin/padding fills the canvas exactly."""
        dash = _minimal_dashboard()
        tree = solve_layout(dash)

        assert tree.outer_width == 1000
        assert tree.outer_height == 800
        assert tree.content_width == 1000
        assert tree.content_height == 800

    def test_root_with_padding(self):
        """Root padding shrinks content area inward."""
        dash = _minimal_dashboard(padding=24)
        tree = solve_layout(dash)

        assert tree.outer_width == 1000
        assert tree.outer_height == 800
        assert tree.content_width == 1000 - 48  # 952
        assert tree.content_height == 800 - 48  # 752

    def test_root_with_margin(self):
        """Root margin shrinks the outer box (canvas is absolute boundary)."""
        dash = _minimal_dashboard(margin=16)
        tree = solve_layout(dash)

        assert tree.outer_width == 1000 - 32  # 968
        assert tree.outer_height == 800 - 32  # 768
        assert tree.content_width == 968
        assert tree.content_height == 768

    def test_root_with_margin_and_padding(self):
        """Root with both margin and padding: margin shrinks outer, padding shrinks content."""
        dash = _minimal_dashboard(margin=16, padding=24)
        tree = solve_layout(dash)

        assert tree.outer_width == 968
        assert tree.outer_height == 768
        assert tree.content_width == 968 - 48  # 920
        assert tree.content_height == 768 - 48  # 720

    def test_root_with_asymmetric_margin(self):
        """Root with asymmetric margin (top right bottom left)."""
        dash = _minimal_dashboard(margin="10 20 30 40")
        tree = solve_layout(dash)

        # margin left+right = 60, top+bottom = 40
        assert tree.outer_width == 1000 - 60  # 940
        assert tree.outer_height == 800 - 40  # 760

    def test_root_with_two_value_padding(self):
        """Root with two-value padding shorthand."""
        dash = _minimal_dashboard(padding="10 20")
        tree = solve_layout(dash)

        # padding left+right = 40, top+bottom = 20
        assert tree.content_width == 1000 - 40  # 960
        assert tree.content_height == 800 - 20  # 780


# ─── Basic Container Distribution ───────────────────────────────────


class TestContainerDistribution:
    """Tests the three-bucket algorithm for distributing space among children."""

    def test_single_auto_child_fills_space(self):
        """A single auto-sized child gets all the container's content area."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("chart")],
        )
        tree = solve_layout(dash)
        child = tree.children[0]

        assert child.outer_width == 1000
        assert child.outer_height == 800

    def test_two_auto_children_split_equally(self):
        """Two auto children split the main axis equally."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("a"), _sheet("b")],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 500
        assert tree.children[1].outer_width == 500
        # Both fill cross-axis
        assert tree.children[0].outer_height == 800
        assert tree.children[1].outer_height == 800

    def test_three_auto_children_split_equally(self):
        """Three auto children split equally (with rounding)."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("a"), _sheet("b"), _sheet("c")],
        )
        tree = solve_layout(dash)

        # 1000 / 3 = 333.33... — total must add up to 1000
        total = sum(c.outer_width for c in tree.children)
        assert total == 1000

    def test_fixed_px_child(self):
        """A fixed px child takes its exact size; auto child gets remainder."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("fixed", width=300),
                _sheet("flex"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 700

    def test_two_fixed_children(self):
        """Two fixed children; remaining space is empty (start-aligned)."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width=300),
                _sheet("b", width=400),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 400

    def test_percentage_child(self):
        """A percentage child resolves against the content box."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("pct", width="60%"),
                _sheet("flex"),
            ],
        )
        tree = solve_layout(dash)

        # 60% of 1000 = 600
        assert tree.children[0].outer_width == 600
        assert tree.children[1].outer_width == 400

    def test_two_percentages(self):
        """Two percentage children: 60% + 40% = 100%."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width="60%"),
                _sheet("b", width="40%"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 600
        assert tree.children[1].outer_width == 400

    def test_percentage_and_fixed(self):
        """Percentage + fixed; auto child gets the remainder."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("pct", width="50%"),
                _sheet("fixed", width=200),
                _sheet("flex"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 500
        assert tree.children[1].outer_width == 200
        assert tree.children[2].outer_width == 300

    def test_vertical_orientation(self):
        """Vertical container distributes on height axis."""
        dash = _minimal_dashboard(
            orientation="vertical",
            contains=[
                _sheet("header", height=56),
                _sheet("body"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_height == 56
        assert tree.children[1].outer_height == 744
        # Cross-axis: both fill width
        assert tree.children[0].outer_width == 1000
        assert tree.children[1].outer_width == 1000


# ─── Margins in Distribution ────────────────────────────────────────


class TestMarginsInDistribution:
    """Margins are subtracted from distributable space before size allocation."""

    def test_child_margins_subtracted(self):
        """Child margins reduce distributable space."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", margin="0 8 0 0"),
                _sheet("b"),
            ],
        )
        tree = solve_layout(dash)

        # Distributable = 1000 - 8 = 992, split equally: 496 each
        assert tree.children[0].outer_width == 496
        assert tree.children[1].outer_width == 496

    def test_margins_with_fixed_child(self):
        """Fixed child + margin: auto child gets remainder minus all margins."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("fixed", width=300, margin="0 16 0 0"),
                _sheet("flex"),
            ],
        )
        tree = solve_layout(dash)

        # Distributable = 1000 - 16 = 984
        # fixed takes 300, flex gets 684
        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 684

    def test_symmetric_margins(self):
        """Uniform margins on all children."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", margin=8),
                _sheet("b", margin=8),
            ],
        )
        tree = solve_layout(dash)

        # Each child has margin-left=8, margin-right=8 on main axis
        # Total margins on main axis: (8+8) + (8+8) = 32
        # Distributable: 1000 - 32 = 968, split equally: 484 each
        assert tree.children[0].outer_width == 484
        assert tree.children[1].outer_width == 484

    def test_margins_in_vertical(self):
        """Vertical container with margins on main axis (top/bottom)."""
        dash = _minimal_dashboard(
            orientation="vertical",
            contains=[
                _sheet("header", height=56, margin="0 0 16 0"),
                _sheet("body"),
            ],
        )
        tree = solve_layout(dash)

        # Distributable = 800 - 16 = 784
        # header takes 56, body gets 784 - 56 = 728
        assert tree.children[0].outer_height == 56
        assert tree.children[1].outer_height == 728


# ─── Padding and Content Areas ──────────────────────────────────────


class TestPaddingAndContentAreas:
    """Element padding shrinks the content area inward."""

    def test_child_padding_shrinks_content(self):
        """Child's padding reduces its content area."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("chart", padding=16)],
        )
        tree = solve_layout(dash)

        child = tree.children[0]
        assert child.outer_width == 1000
        assert child.outer_height == 800
        assert child.content_width == 1000 - 32  # 968
        assert child.content_height == 800 - 32  # 768

    def test_container_padding_then_child(self):
        """Container padding reduces available space for children."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            padding=20,
            contains=[_sheet("chart")],
        )
        tree = solve_layout(dash)

        # Root content: 1000 - 40 = 960 wide, 800 - 40 = 760 tall
        child = tree.children[0]
        assert child.outer_width == 960
        assert child.outer_height == 760

    def test_asymmetric_padding(self):
        """Asymmetric padding on a child."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("chart", padding="10 20 30 40")],
        )
        tree = solve_layout(dash)

        child = tree.children[0]
        assert child.content_width == 1000 - 60  # 940 (left 40 + right 20)
        assert child.content_height == 800 - 40  # 760 (top 10 + bottom 30)


# ─── Cross-Axis Resolution ──────────────────────────────────────────


class TestCrossAxis:
    """Cross-axis defaults to 100% of container content; explicit values override."""

    def test_default_cross_axis_fills_parent(self):
        """Child with no cross-axis size fills 100% of parent content box."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("chart", width=500)],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_height == 800  # full cross-axis

    def test_explicit_cross_axis_px(self):
        """Explicit cross-axis px overrides the 100% default."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("chart", width=500, height=300)],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_height == 300

    def test_explicit_cross_axis_percentage(self):
        """Cross-axis percentage resolves against container content box."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("chart", width=500, height="50%")],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_height == 400  # 50% of 800

    def test_vertical_cross_axis(self):
        """Vertical container: cross-axis is width."""
        dash = _minimal_dashboard(
            orientation="vertical",
            contains=[_sheet("chart", height=200, width=600)],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 600


# ─── Percentage Resolution Against Content Box ──────────────────────


class TestPercentageResolution:
    """Percentages resolve against the container's content box, not distributable space."""

    def test_percentage_ignores_sibling_margins(self):
        """60% means 60% of content box, regardless of sibling margins."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width="60%"),
                _sheet("b", margin="0 0 0 20"),
            ],
        )
        tree = solve_layout(dash)

        # 60% of 1000 = 600 for child a
        assert tree.children[0].outer_width == 600
        # Distributable: 1000 - 20 = 980. Claimed: 600. Auto gets 980 - 600 = 380
        assert tree.children[1].outer_width == 380

    def test_percentage_with_container_padding(self):
        """Percentage resolves against container content box (after container padding)."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            padding=50,
            contains=[
                _sheet("a", width="50%"),
                _sheet("b"),
            ],
        )
        tree = solve_layout(dash)

        # Root content width: 1000 - 100 = 900
        # 50% of 900 = 450
        assert tree.children[0].outer_width == 450
        assert tree.children[1].outer_width == 450


# ─── Nested Containers ──────────────────────────────────────────────


class TestNestedContainers:
    """Solver recurses into nested containers correctly."""

    def test_nested_container(self):
        """A container inside a container resolves sizes correctly."""
        inner_container = _named_container(
            "inner",
            orientation="horizontal",
            contains=[_sheet("a"), _sheet("b")],
        )
        dash = _minimal_dashboard(
            orientation="vertical",
            contains=[
                {
                    "header": {
                        "type": "container",
                        "orientation": "horizontal",
                        "height": 100,
                        "contains": [_blank(width=100)],
                    }
                },
                inner_container,
            ],
        )
        tree = solve_layout(dash)

        header = tree.children[0]
        inner = tree.children[1]

        assert header.outer_height == 100
        assert inner.outer_height == 700  # 800 - 100

        # Inner children split its content width equally
        assert inner.children[0].outer_width == 500
        assert inner.children[1].outer_width == 500
        assert inner.children[0].outer_height == 700

    def test_deeply_nested(self):
        """Three levels of nesting resolve correctly."""
        dash = _minimal_dashboard(
            orientation="vertical",
            contains=[
                {
                    "level1": {
                        "type": "container",
                        "orientation": "horizontal",
                        "contains": [
                            {
                                "level2": {
                                    "type": "container",
                                    "orientation": "vertical",
                                    "width": "50%",
                                    "padding": 10,
                                    "contains": [_sheet("deep", height=100)],
                                }
                            },
                            _sheet("sibling"),
                        ],
                    }
                },
            ],
        )
        tree = solve_layout(dash)

        level1 = tree.children[0]
        level2 = level1.children[0]
        deep_sheet = level2.children[0]

        # level1 fills root: 1000 x 800
        assert level1.outer_width == 1000
        assert level1.outer_height == 800

        # level2 is 50% of 1000 = 500
        assert level2.outer_width == 500
        assert level2.content_width == 480  # 500 - 20 (padding 10 each side)
        assert level2.content_height == 780  # 800 - 20

        # deep_sheet: height=100, width fills level2 content
        assert deep_sheet.outer_height == 100
        assert deep_sheet.outer_width == 480


# ─── Overconstrained Layouts ────────────────────────────────────────


class TestOverconstrained:
    """When children's explicit sizes exceed available space, the solver
    shrinks proportionally and emits warnings."""

    def test_fixed_children_exceed_space(self):
        """Two fixed children summing to more than available: shrink proportionally."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width=700),
                _sheet("b", width=500),
            ],
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = solve_layout(dash)

            # Should emit a warning
            assert len(w) >= 1
            assert "exceed" in str(w[0].message).lower()

        # Both shrunk proportionally: 700/1200 * 1000, 500/1200 * 1000
        total = tree.children[0].outer_width + tree.children[1].outer_width
        assert total == 1000

        # Proportional: 700:500 ratio preserved
        assert tree.children[0].outer_width > tree.children[1].outer_width

    def test_percentage_plus_fixed_exceeds_space(self):
        """60% + 600px exceeds space: percentages honored first, fixed shrunk."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("pct", width="60%"),
                _sheet("fixed", width=600),
            ],
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = solve_layout(dash)

            assert len(w) >= 1

        # Percentage honored: 60% of 1000 = 600
        assert tree.children[0].outer_width == 600
        # Fixed gets remaining: 1000 - 600 = 400
        assert tree.children[1].outer_width == 400

    def test_percentages_exceed_100(self):
        """Two percentages totaling > 100%: all shrunk proportionally."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width="70%"),
                _sheet("b", width="50%"),
            ],
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = solve_layout(dash)

            assert len(w) >= 1
            assert (
                "percentage" in str(w[0].message).lower() or "exceed" in str(w[0].message).lower()
            )

        # Both shrunk proportionally: 70/120 * 1000 ≈ 583, 50/120 * 1000 ≈ 417
        total = tree.children[0].outer_width + tree.children[1].outer_width
        assert total == 1000
        assert tree.children[0].outer_width > tree.children[1].outer_width

    def test_auto_child_gets_zero_when_fully_claimed(self):
        """Auto child gets 0px when explicit sizes claim all space."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("fixed", width=1000),
                _sheet("flex"),
            ],
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = solve_layout(dash)

            # Should warn about auto child getting 0
            warning_msgs = [str(x.message).lower() for x in w]
            assert any("0px" in msg or "0 px" in msg or "zero" in msg for msg in warning_msgs)

        assert tree.children[0].outer_width == 1000
        assert tree.children[1].outer_width == 0


# ─── Negative Content Area (Padding > Outer Box) ────────────────────


class TestNegativeContentArea:
    """When padding exceeds an element's solved size, content area clamps to 0."""

    def test_padding_exceeds_size(self):
        """Content area clamped to 0 when padding > outer size."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("tiny", width=20, padding=50),
                _sheet("rest"),
            ],
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            tree = solve_layout(dash)

            warning_msgs = [str(x.message).lower() for x in w]
            assert any(
                "padding" in msg and "clamp" in msg or "content area" in msg for msg in warning_msgs
            )

        child = tree.children[0]
        assert child.outer_width == 20
        assert child.content_width == 0
        # Height padding (50 top + 50 bottom = 100) does not exceed outer_height (800),
        # so content_height is clamped per-dimension, not both at once.
        assert child.content_height == 800 - 100  # 700


# ─── Edge Cases ─────────────────────────────────────────────────────


class TestEdgeCases:
    """Various edge cases and boundary conditions."""

    def test_empty_container(self):
        """Container with no children resolves to its own size."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[],
        )
        tree = solve_layout(dash)

        assert tree.outer_width == 1000
        assert tree.outer_height == 800
        assert tree.children == []

    def test_single_fixed_child_no_auto(self):
        """Single fixed child smaller than container: remaining space is empty."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("small", width=200)],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 200

    def test_all_children_fixed_under_budget(self):
        """Multiple fixed children all under budget: no auto children, space remains empty."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width=200),
                _sheet("b", width=300),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 200
        assert tree.children[1].outer_width == 300

    def test_pixel_string_equivalent_to_int(self):
        """'300px' is equivalent to 300."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width="300px"),
                _sheet("b"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 700

    def test_auto_string_equivalent_to_omitted(self):
        """'auto' and omitted both mean equal-share fill."""
        dash1 = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("a", width="auto"), _sheet("b")],
        )
        dash2 = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("a"), _sheet("b")],
        )
        tree1 = solve_layout(dash1)
        tree2 = solve_layout(dash2)

        assert tree1.children[0].outer_width == tree2.children[0].outer_width
        assert tree1.children[1].outer_width == tree2.children[1].outer_width

    def test_rounding_distributes_all_pixels(self):
        """Auto distribution with non-divisible space accounts for all pixels."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("a"), _sheet("b"), _sheet("c")],
        )
        tree = solve_layout(dash)

        total = sum(c.outer_width for c in tree.children)
        assert total == 1000  # no pixels lost to rounding

    def test_zero_dimension_canvas(self):
        """Canvas with zero width: everything resolves to 0."""
        dash = DashboardSpec(
            dashboard="Test",
            canvas=Canvas(width=0, height=600),
            root=RootComponent(
                type="root",
                orientation="horizontal",
                contains=[_sheet("s")],
            ),
        )
        tree = solve_layout(dash)

        assert tree.outer_width == 0
        assert tree.children[0].outer_width == 0

    def test_leaf_types_have_no_children(self):
        """Leaf nodes (sheet, text, blank, image) have empty children list."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("s"),
                _text("hello"),
                _blank(width=10),
            ],
        )
        tree = solve_layout(dash)

        for child in tree.children:
            assert child.children == []


# ─── ResolvedNode Structure ─────────────────────────────────────────


class TestResolvedNodeStructure:
    """Validate the ResolvedNode dataclass structure."""

    def test_resolved_node_has_required_fields(self):
        """ResolvedNode has name, component, outer/content dims, children."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[_sheet("chart", width=400, padding=10)],
        )
        tree = solve_layout(dash)

        # Root node
        assert tree.name is None  # root has no name
        assert tree.component is not None
        assert isinstance(tree.outer_width, int)
        assert isinstance(tree.outer_height, int)
        assert isinstance(tree.content_width, int)
        assert isinstance(tree.content_height, int)
        assert isinstance(tree.children, list)

        # Child node
        child = tree.children[0]
        assert child.name == "chart"
        assert child.outer_width == 400
        assert child.content_width == 380  # 400 - 20
        assert child.content_height == 800 - 20  # 780

    def test_root_node_preserves_component(self):
        """The root ResolvedNode links back to the RootComponent."""
        dash = _minimal_dashboard()
        tree = solve_layout(dash)

        assert tree.component.type == "root"


# ─── Integration: Worked Example from Spec ──────────────────────────


class TestWorkedExample:
    """Reproduces the worked example from the Layout DSL v2 spec section 8.3."""

    def test_spec_worked_example(self):
        yaml_str = """
dashboard: "Test Dashboard"
canvas:
  width: 1440
  height: 900

root:
  type: root
  orientation: vertical
  padding: 24
  contains:
    - header:
        type: container
        orientation: horizontal
        height: 56
        padding: "0 16"
        contains:
          - logo:
              type: image
              src: "logo.svg"
              alt: "Logo"
              width: 120
              height: 28
          - type: text
            content: "Dashboard"
            preset: title
            margin: "0 0 0 12"
          - type: blank
            width: auto
          - type: navigation
            text: "Details"
            link: "/details"
            width: 140
            padding: "6 16"
    - chart_row:
        type: container
        orientation: horizontal
        padding: 16
        margin: "16 0 0 0"
        contains:
          - main_chart:
              type: sheet
              link: "charts/revenue.yaml"
              width: "60%"
              padding: 16
              margin: "0 8 0 0"
          - side_chart:
              type: sheet
              link: "charts/orders.yaml"
              padding: 16
"""
        dash = parse_dashboard(yaml_str)
        tree = solve_layout(dash)

        # Root
        assert tree.outer_width == 1440
        assert tree.outer_height == 900
        assert tree.content_width == 1392  # 1440 - 48
        assert tree.content_height == 852  # 900 - 48

        # Header: height 56, width fills root content (1392)
        header = tree.children[0]
        assert header.outer_height == 56
        assert header.outer_width == 1392
        assert header.content_width == 1360  # 1392 - 32 (padding 0 16)
        assert header.content_height == 56  # no vertical padding

        # Header children
        logo = header.children[0]
        text = header.children[1]
        blank = header.children[2]
        nav = header.children[3]

        assert logo.outer_width == 120
        assert logo.outer_height == 28  # explicit cross-axis

        assert nav.outer_width == 140
        assert nav.content_width == 108  # 140 - 32 (padding 16 left+right)
        assert nav.content_height == 44  # 56 - 12 (padding 6 top+bottom)

        # text and blank are auto: distributable = 1360 - 12 (text margin) = 1348
        # fixed claimed: 120 + 140 = 260
        # remaining: 1348 - 260 = 1088, split equally: 544 each
        assert text.outer_width == 544
        assert blank.outer_width == 544

        # Chart row: auto height, has margin "16 0 0 0"
        chart_row = tree.children[1]
        # Distributable for vertical after header: 852 - 56 - 16 (chart_row margin top) = 780
        assert chart_row.outer_height == 780
        assert chart_row.outer_width == 1392
        assert chart_row.content_width == 1360  # 1392 - 32 (padding 16)
        assert chart_row.content_height == 748  # 780 - 32

        # Chart row children
        main_chart = chart_row.children[0]
        side_chart = chart_row.children[1]

        # main_chart: 60% of 1360 (content box) = 816
        assert main_chart.outer_width == 816
        assert main_chart.content_width == 784  # 816 - 32 (padding 16)
        assert main_chart.content_height == 716  # 748 - 32

        # side_chart: auto, distributable = 1360 - 8 (margin) = 1352, remaining: 1352 - 816 = 536
        assert side_chart.outer_width == 536
        assert side_chart.content_width == 504  # 536 - 32
        assert side_chart.content_height == 716


# ─── Mixed Bucket Combinations ──────────────────────────────────────


class TestMixedBuckets:
    """Tests combining percentage, fixed, and auto children in various orders."""

    def test_pct_fixed_auto(self):
        """50% + 200px + auto: auto gets the remainder."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width="50%"),
                _sheet("b", width=200),
                _sheet("c"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 500
        assert tree.children[1].outer_width == 200
        assert tree.children[2].outer_width == 300

    def test_multiple_auto_with_fixed(self):
        """300px fixed + two auto children: auto split remaining equally."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("fixed", width=300),
                _sheet("a"),
                _sheet("b"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 300
        assert tree.children[1].outer_width == 350
        assert tree.children[2].outer_width == 350

    def test_all_percentages_exactly_100(self):
        """Three percentages summing to exactly 100%: no auto space needed."""
        dash = _minimal_dashboard(
            orientation="horizontal",
            contains=[
                _sheet("a", width="25%"),
                _sheet("b", width="50%"),
                _sheet("c", width="25%"),
            ],
        )
        tree = solve_layout(dash)

        assert tree.children[0].outer_width == 250
        assert tree.children[1].outer_width == 500
        assert tree.children[2].outer_width == 250


# ─── Full Dashboard YAML Integration ────────────────────────────────


class TestFullDashboardIntegration:
    """End-to-end test with a realistic dashboard YAML."""

    def test_kpi_dashboard_layout(self):
        """KPI dashboard: header + KPI row + chart row."""
        yaml_str = """
dashboard: "Sales"
canvas: { width: 1200, height: 800 }

root:
  type: root
  orientation: vertical
  padding: 16
  contains:
    - header:
        type: container
        orientation: horizontal
        height: 48
        contains:
          - type: text
            content: "Sales Dashboard"
            preset: title

    - kpi_row:
        type: container
        orientation: horizontal
        height: 120
        margin: "8 0"
        contains:
          - kpi1:
              type: sheet
              link: "charts/kpi1.yaml"
              margin: "0 4 0 0"
          - kpi2:
              type: sheet
              link: "charts/kpi2.yaml"
              margin: "0 4 0 4"
          - kpi3:
              type: sheet
              link: "charts/kpi3.yaml"
              margin: "0 0 0 4"

    - chart_area:
        type: container
        orientation: horizontal
        contains:
          - main:
              type: sheet
              link: "charts/main.yaml"
              width: "65%"
              margin: "0 8 0 0"
          - side:
              type: sheet
              link: "charts/side.yaml"
"""
        dash = parse_dashboard(yaml_str)
        tree = solve_layout(dash)

        # Root content: 1200-32=1168 wide, 800-32=768 tall
        assert tree.content_width == 1168
        assert tree.content_height == 768

        header = tree.children[0]
        kpi_row = tree.children[1]
        chart_area = tree.children[2]

        # Header: 48px tall
        assert header.outer_height == 48
        assert header.outer_width == 1168

        # KPI row: 120px tall, margin "8 0" = 8 top, 0 right, 8 bottom, 0 left
        assert kpi_row.outer_height == 120

        # Chart area: auto height
        # Distributable vertical: 768 - 48 (header) - 8 - 8 (kpi margins) - 120 (kpi) = 584
        # (margin "8 0" on kpi_row = 8 top + 8 bottom on main axis)
        assert chart_area.outer_height == 584

        # KPI children: 3 auto children with margins
        # Margins on main axis: (0+4) + (4+4) + (4+0) = 16
        # Distributable: 1168 - 16 = 1152, split 3 ways
        kpi_total = sum(c.outer_width for c in kpi_row.children)
        assert kpi_total == 1152  # accounts for rounding

    def test_sidebar_layout(self):
        """Horizontal root: fixed sidebar + auto main content."""
        yaml_str = """
dashboard: "Executive"
canvas: { width: 1440, height: 900 }

root:
  type: root
  orientation: horizontal
  contains:
    - sidebar:
        type: container
        orientation: vertical
        width: 220
        padding: "24 16"
        contains:
          - type: text
            content: "Menu"
            preset: heading
    - main:
        type: container
        orientation: vertical
        padding: 24
        contains:
          - type: text
            content: "Content"
            preset: title
"""
        dash = parse_dashboard(yaml_str)
        tree = solve_layout(dash)

        sidebar = tree.children[0]
        main = tree.children[1]

        assert sidebar.outer_width == 220
        assert sidebar.outer_height == 900
        assert sidebar.content_width == 188  # 220 - 32

        assert main.outer_width == 1220  # 1440 - 220
        assert main.outer_height == 900
        assert main.content_width == 1172  # 1220 - 48
