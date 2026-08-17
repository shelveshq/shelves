"""Tests for the YAML loc-to-position mapping utility."""

from __future__ import annotations

import shelves.schema.yaml_position as yp
from shelves.schema.yaml_position import resolve_locs, yaml_loc_to_position


class TestYamlLocToPosition:
    """Happy path: loc tuples resolve to correct (line, col) positions."""

    def test_top_level_key(self):
        yaml_text = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: bar\n"
        assert yaml_loc_to_position(yaml_text, ("marks",)) == (5, 1)

    def test_nested_key(self):
        yaml_text = (
            "sheet: test\n"
            "data: orders\n"
            "cols: week\n"
            "rows: revenue\n"
            "marks:\n"
            "  type: bar\n"
            "  tooltip: true\n"
        )
        assert yaml_loc_to_position(yaml_text, ("marks", "type")) == (6, 3)

    def test_list_index_then_key(self):
        yaml_text = (
            "sheet: test\n"
            "data: orders\n"
            "cols: week\n"
            "marks: bar\n"
            "filters:\n"
            "  - field: country\n"
            "    operator: eq\n"
            "    value: US\n"
            "  - field: region\n"
            "    operator: in\n"
            "    value: [East, West]\n"
        )
        assert yaml_loc_to_position(yaml_text, ("filters", 1, "operator")) == (10, 5)

    def test_list_item_position(self):
        yaml_text = (
            "sheet: test\n"
            "data: orders\n"
            "cols: week\n"
            "marks: bar\n"
            "rows:\n"
            "  - measure: revenue\n"
            "  - measure: orders\n"
        )
        assert yaml_loc_to_position(yaml_text, ("rows", 1)) == (7, 5)

    def test_multi_measure_entry_field(self):
        yaml_text = (
            "sheet: test\n"
            "data: orders\n"
            "cols: week\n"
            "marks: bar\n"
            "rows:\n"
            "  - measure: revenue\n"
            "    color: region\n"
            "  - measure: orders\n"
            "    color:\n"
            "      field: category\n"
            "      legend: true\n"
        )
        assert yaml_loc_to_position(yaml_text, ("rows", 1, "color", "field")) == (10, 7)

    def test_value_position(self):
        yaml_text = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: bar\n"
        assert yaml_loc_to_position(yaml_text, ("marks",), position="value") == (5, 8)


class TestYamlLocEdgeCases:
    """Edge cases: discriminator labels, missing keys, bounds, scalars."""

    def test_missing_key_returns_none(self):
        yaml_text = "sheet: test\ndata: orders\n"
        assert yaml_loc_to_position(yaml_text, ("marks",)) is None

    def test_union_discriminator_literal(self):
        yaml_text = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: bar\n"
        loc = (
            "marks",
            "literal['bar','line','area','circle','square','text',"
            "'point','rule','tick','rect','arc','geoshape']",
        )
        assert yaml_loc_to_position(yaml_text, loc) == (5, 1)

    def test_union_discriminator_model_name(self):
        yaml_text = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: bar\n"
        loc = ("marks", "MarkObject")
        assert yaml_loc_to_position(yaml_text, loc) == (5, 1)

    def test_mixed_discriminator_and_real_key(self):
        yaml_text = (
            "sheet: test\n"
            "data: orders\n"
            "cols: week\n"
            "rows: revenue\n"
            "marks:\n"
            "  type: bar\n"
            "  tooltip: true\n"
        )
        loc = ("marks", "MarkObject", "type")
        assert yaml_loc_to_position(yaml_text, loc) == (6, 3)

    def test_empty_loc(self):
        yaml_text = "sheet: test\ndata: orders\n"
        assert yaml_loc_to_position(yaml_text, ()) == (1, 1)

    def test_single_key_yaml(self):
        yaml_text = "sheet: test\n"
        assert yaml_loc_to_position(yaml_text, ("sheet",)) == (1, 1)

    def test_yaml_with_comments(self):
        yaml_text = "# top comment\nsheet: test\n# middle comment\ndata: orders\nmarks: bar\n"
        assert yaml_loc_to_position(yaml_text, ("marks",)) == (5, 1)

    def test_integer_loc_beyond_list_bounds(self):
        yaml_text = "sheet: test\nfilters:\n  - field: country\n  - field: region\n"
        assert yaml_loc_to_position(yaml_text, ("filters", 99)) is None

    def test_loc_walks_into_scalar(self):
        yaml_text = "sheet: test\ndata: orders\n"
        result = yaml_loc_to_position(yaml_text, ("sheet", "nested"))
        assert result == (1, 1)


class TestYamlLocErrors:
    """Error cases: malformed YAML, empty input, non-mapping root."""

    def test_malformed_yaml(self):
        yaml_text = "sheet: [\ninvalid yaml"
        assert yaml_loc_to_position(yaml_text, ("sheet",)) is None

    def test_empty_yaml(self):
        assert yaml_loc_to_position("", ("sheet",)) is None

    def test_non_mapping_root(self):
        yaml_text = "- item1\n- item2\n"
        assert yaml_loc_to_position(yaml_text, ("sheet",)) is None


class TestResolveLocs:
    """Batch resolution: parse the document once for many loc tuples."""

    def test_parses_document_only_once(self, monkeypatch):
        # Resolving many errors must not re-parse the YAML per error.
        calls = {"n": 0}
        original = yp._load_root

        def counting(text):
            calls["n"] += 1
            return original(text)

        monkeypatch.setattr(yp, "_load_root", counting)
        yaml_text = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: bar\n"
        results = resolve_locs(yaml_text, [("sheet",), ("marks",), ("data",)])

        assert calls["n"] == 1
        assert results[0]["position"] == (1, 1)
        assert results[1]["position"] == (5, 1)
        assert results[2]["position"] == (2, 1)

    def test_display_loc_drops_synthetic_labels(self):
        yaml_text = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: 12345\n"
        res = resolve_locs(
            yaml_text,
            [("marks", "MarkObject"), ("marks", "literal['bar','line']")],
        )
        assert res[0]["display_loc"] == ["marks"]
        assert res[1]["display_loc"] == ["marks"]

    def test_display_loc_keeps_present_capitalized_key(self):
        # Regression: a real key that happens to start with an uppercase
        # letter must not be mistaken for a Pydantic union discriminator.
        yaml_text = "sheet: test\nRegion: west\n"
        res = resolve_locs(yaml_text, [("Region",)])
        assert res[0]["display_loc"] == ["Region"]
        assert res[0]["position"] == (2, 1)

    def test_malformed_yaml_falls_back_to_pattern_clean(self):
        # Unparseable YAML → no position, but display_loc still strips labels.
        yaml_text = "sheet: [\ninvalid yaml"
        res = resolve_locs(yaml_text, [("marks", "MarkObject")])
        assert res[0]["position"] is None
        assert res[0]["display_loc"] == ["marks"]
