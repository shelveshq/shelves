"""
Marks Tests

Tests mark parsing (schema validation) and translation (Vega-Lite output).
All test expectations are derived from the DSL reference (docs/guide/dsl-reference.md),
not from implementation details.

DSL reference says:
- String shorthand: marks: bar (supported types: bar, line, area, circle, square,
  text, point, rule, tick, rect, arc, geoshape)
- Object form: marks: { type: line, style: dashed, point: true, opacity: 0.8 }
- Style patterns: dashed → [6, 4] strokeDash, dotted → [2, 2]
- In multi-measure, each entry can override `mark`
"""

import pytest
from pydantic import ValidationError

from src.schema.chart_schema import parse_chart
from tests.conftest import MODELS_DIR
from src.translator.translate import translate_chart


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_YAML = """\
sheet: "Marks Test"
data: orders
cols: country
rows: revenue
"""


def _make_yaml(marks_block: str) -> str:
    return BASE_YAML + marks_block


def _compile(yaml_str: str) -> dict:
    spec = parse_chart(yaml_str)
    return translate_chart(spec, models_dir=MODELS_DIR)


# ===========================================================================
# Schema validation — string shorthand mark types
# ===========================================================================


class TestMarkSchemaStringShorthand:
    """All supported mark types from the DSL reference should parse."""

    @pytest.mark.parametrize(
        "mark_type",
        [
            "bar",
            "line",
            "area",
            "circle",
            "square",
            "text",
            "point",
            "rule",
            "tick",
            "rect",
            "arc",
            "geoshape",
        ],
    )
    def test_valid_mark_types(self, mark_type):
        spec = parse_chart(_make_yaml(f"marks: {mark_type}"))
        assert spec.marks == mark_type

    def test_rejects_unknown_mark_type(self):
        with pytest.raises(ValidationError):
            parse_chart(_make_yaml("marks: sparkle"))

    def test_rejects_empty_mark(self):
        with pytest.raises(ValidationError):
            parse_chart(_make_yaml("marks: "))


# ===========================================================================
# Schema validation — object form
# ===========================================================================


class TestMarkSchemaObjectForm:
    def test_object_form_with_type_only(self):
        spec = parse_chart(
            _make_yaml("""
marks:
  type: line
""")
        )
        assert spec.marks.type == "line"

    def test_object_form_with_style(self):
        spec = parse_chart(
            _make_yaml("""
marks:
  type: line
  style: dashed
""")
        )
        assert spec.marks.type == "line"
        assert spec.marks.style == "dashed"

    def test_object_form_with_point(self):
        spec = parse_chart(
            _make_yaml("""
marks:
  type: line
  point: true
""")
        )
        assert spec.marks.type == "line"
        assert spec.marks.point is True

    def test_object_form_with_opacity(self):
        spec = parse_chart(
            _make_yaml("""
marks:
  type: line
  opacity: 0.8
""")
        )
        assert spec.marks.type == "line"
        assert spec.marks.opacity == 0.8

    def test_object_form_all_properties(self):
        spec = parse_chart(
            _make_yaml("""
marks:
  type: line
  style: dotted
  point: true
  opacity: 0.5
""")
        )
        assert spec.marks.type == "line"
        assert spec.marks.style == "dotted"
        assert spec.marks.point is True
        assert spec.marks.opacity == 0.5

    @pytest.mark.parametrize("style", ["solid", "dashed", "dotted"])
    def test_valid_style_values(self, style):
        spec = parse_chart(
            _make_yaml(f"""
marks:
  type: line
  style: {style}
""")
        )
        assert spec.marks.style == style

    def test_rejects_invalid_style(self):
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
marks:
  type: line
  style: wavy
""")
            )

    def test_rejects_invalid_object_mark_type(self):
        with pytest.raises(ValidationError):
            parse_chart(
                _make_yaml("""
marks:
  type: sparkle
""")
            )


# ===========================================================================
# Translation — string shorthand
# ===========================================================================


class TestMarkTranslationStringShorthand:
    """String shorthand marks should compile to simple Vega-Lite mark strings."""

    @pytest.mark.parametrize(
        "mark_type",
        [
            "bar",
            "line",
            "area",
            "circle",
            "square",
            "text",
            "point",
            "rule",
            "tick",
            "rect",
            "arc",
            "geoshape",
        ],
    )
    def test_string_mark_compiles_to_vegalite_mark(self, mark_type):
        vl = _compile(_make_yaml(f"marks: {mark_type}"))
        # Vega-Lite mark should be the string or an object with "type"
        mark = vl.get("mark")
        if isinstance(mark, str):
            assert mark == mark_type
        else:
            assert mark["type"] == mark_type


# ===========================================================================
# Translation — object form
# ===========================================================================


class TestMarkTranslationObjectForm:
    def test_object_mark_compiles_type(self):
        vl = _compile(
            _make_yaml("""
marks:
  type: line
""")
        )
        mark = vl["mark"]
        if isinstance(mark, dict):
            assert mark["type"] == "line"
        else:
            assert mark == "line"

    def test_dashed_style_produces_stroke_dash(self):
        """DSL reference: dashed renders as [6, 4] strokeDash."""
        vl = _compile(
            _make_yaml("""
marks:
  type: line
  style: dashed
""")
        )
        mark = vl["mark"]
        assert isinstance(mark, dict)
        assert mark["type"] == "line"
        assert mark["strokeDash"] == [6, 4]

    def test_dotted_style_produces_stroke_dash(self):
        """DSL reference: dotted renders as [2, 2] strokeDash."""
        vl = _compile(
            _make_yaml("""
marks:
  type: line
  style: dotted
""")
        )
        mark = vl["mark"]
        assert isinstance(mark, dict)
        assert mark["type"] == "line"
        assert mark["strokeDash"] == [2, 2]

    def test_solid_style_no_stroke_dash(self):
        """solid style should not produce strokeDash."""
        vl = _compile(
            _make_yaml("""
marks:
  type: line
  style: solid
""")
        )
        mark = vl["mark"]
        if isinstance(mark, dict):
            assert "strokeDash" not in mark or mark.get("strokeDash") is None

    def test_point_true_on_line(self):
        """point: true should show data points on lines."""
        vl = _compile(
            _make_yaml("""
marks:
  type: line
  point: true
""")
        )
        mark = vl["mark"]
        assert isinstance(mark, dict)
        assert mark["type"] == "line"
        assert mark["point"] is True

    def test_opacity_applied(self):
        vl = _compile(
            _make_yaml("""
marks:
  type: bar
  opacity: 0.8
""")
        )
        mark = vl["mark"]
        assert isinstance(mark, dict)
        assert mark["type"] == "bar"
        assert mark["opacity"] == 0.8

    def test_all_properties_combined(self):
        """Object form with all properties should produce correct Vega-Lite mark."""
        vl = _compile(
            _make_yaml("""
marks:
  type: line
  style: dashed
  point: true
  opacity: 0.7
""")
        )
        mark = vl["mark"]
        assert isinstance(mark, dict)
        assert mark["type"] == "line"
        assert mark["strokeDash"] == [6, 4]
        assert mark["point"] is True
        assert mark["opacity"] == 0.7


# ===========================================================================
# Translation — marks required for single-measure string shelves
# ===========================================================================


class TestMarkRequired:
    """DSL reference: marks is required when both shelves are strings."""

    def test_marks_required_with_string_shelves(self):
        """Both cols and rows as strings requires top-level marks."""
        with pytest.raises((ValidationError, ValueError, KeyError)):
            parse_chart("""\
sheet: "Test"
data: orders
cols: country
rows: revenue
""")
