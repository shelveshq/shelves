"""
Validation Tests (SHE-54)

The unified error renderer is an API contract: every error must be paste-able
into an LLM context and fixable in one turn. These tests pin the structured
error shape produced by `shelves.validation.validate_chart_yaml`.

Fixtures are inline YAML strings — these are contract tests, so the input sits
next to its expected output. All examples use the `orders` fixture model
(measures: revenue, order_count, arpu, cost, margin_pct; dimensions: country,
region, product, week, month).
"""

from __future__ import annotations

from typing import get_args

import pytest
import yaml

from shelves.models.loader import clear_model_cache
from shelves.schema.chart_schema import MarkType
from shelves.validation import validate_chart_yaml
from tests.conftest import MODELS_DIR


@pytest.fixture(autouse=True)
def _clear_model_cache():
    clear_model_cache()
    yield
    clear_model_cache()


# ─── Happy path ───────────────────────────────────────────────────


def test_valid_spec_normalized():
    yaml_text = (
        "sheet: Revenue by country\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
    )
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is True
    assert result.kind == "chart"
    assert result.errors == []
    assert result.model_checked is True
    assert result.normalized is not None
    assert yaml.safe_load(result.normalized) == {
        "sheet": "Revenue by country",
        "data": "orders",
        "cols": "country",
        "rows": "revenue",
        "marks": "bar",
    }


def test_unknown_field_did_you_mean():
    yaml_text = "sheet: Revenue\ndata: orders\ncols: country\nrows: revnue\nmarks: bar\n"
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.path == "rows"
    assert err.line == 4
    assert isinstance(err.col, int)
    assert err.code == "unknown_field"
    assert err.source == "model"
    assert err.message == "Unknown field 'revnue' in model 'orders'."
    assert err.did_you_mean == "revenue"
    # measures first (sorted), then dimensions (sorted)
    assert err.valid_options == [
        "arpu",
        "cost",
        "margin_pct",
        "order_count",
        "revenue",
        "country",
        "month",
        "product",
        "region",
        "week",
    ]
    assert err.fix_hint == "Replace 'revnue' with one of valid_options (see did_you_mean)."


def test_invalid_mark_valid_options():
    yaml_text = "sheet: Revenue\ndata: orders\ncols: country\nrows: revenue\nmarks: candle\n"
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    marks_errs = [e for e in result.errors if e.path == "marks"]
    assert len(marks_errs) == 1
    err = marks_errs[0]
    assert err.code == "invalid_enum"
    assert err.source == "schema"
    assert err.valid_options == list(get_args(MarkType))
    assert err.did_you_mean is None
    assert err.message.startswith("'candle' is not a valid value for 'marks'.")


def test_three_mistakes_three_errors():
    yaml_text = "sheet: ''\ndata: orders\ncols: country\nrows: revnue\nmarks: candle\n"
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    assert len(result.errors) == 3

    codes = [(e.source, e.code, e.path) for e in result.errors]
    # Model errors rank first, then schema errors.
    assert codes[0] == ("model", "unknown_field", "rows")
    schema_codes = {(c, p) for src, c, p in codes if src == "schema"}
    assert ("string_too_short", "sheet") in schema_codes
    assert ("invalid_enum", "marks") in schema_codes


# ─── Edge cases ───────────────────────────────────────────────────


def test_yaml_syntax_error():
    yaml_text = "sheet: [\ninvalid yaml"
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.code == "yaml_syntax"
    assert err.source == "yaml"
    assert err.line is not None


def test_empty_input():
    result = validate_chart_yaml("   \n  ", models_dir=MODELS_DIR)

    assert result.valid is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.code == "empty_input"
    assert err.message == (
        "The file is empty — a chart spec needs at least sheet, data, and rows/cols."
    )


def test_not_a_mapping():
    result = validate_chart_yaml("- a\n- b\n", models_dir=MODELS_DIR)

    assert result.valid is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.code == "not_a_mapping"
    assert err.fix_hint is not None
    assert "sheet:" in err.fix_hint


def test_missing_model_file():
    yaml_text = "sheet: test\ndata: nonexistent\ncols: country\nrows: revenue\nmarks: bar\n"
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    model_errs = [e for e in result.errors if e.code == "unknown_model"]
    assert len(model_errs) == 1
    err = model_errs[0]
    assert err.source == "model"
    assert err.valid_options is not None
    assert "orders" in err.valid_options


def test_no_models_dir_skips_model_checks():
    yaml_text = "sheet: test\ndata: orders\ncols: country\nrows: revnue\nmarks: bar\n"
    result = validate_chart_yaml(yaml_text, models_dir=None)

    assert result.model_checked is False
    # No model check → the misspelled field is NOT caught, spec is structurally valid.
    assert [e for e in result.errors if e.code == "unknown_field"] == []


def test_dot_notation_grain_error():
    yaml_text = "sheet: test\ndata: orders\ncols: country.month\nrows: revenue\nmarks: bar\n"
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    grain_errs = [e for e in result.errors if e.code == "invalid_grain"]
    assert len(grain_errs) == 1
    assert grain_errs[0].path == "cols"


def test_multi_measure_entry_field():
    yaml_text = (
        "sheet: test\ndata: orders\ncols: country\nrows:\n  - measure: revnue\n    mark: bar\n"
    )
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    errs = [e for e in result.errors if e.code == "unknown_field"]
    assert len(errs) == 1
    assert errs[0].path == "rows[0].measure"
    assert errs[0].did_you_mean == "revenue"


def test_filter_field_unknown():
    yaml_text = (
        "sheet: test\n"
        "data: orders\n"
        "cols: country\n"
        "rows: revenue\n"
        "marks: bar\n"
        "filters:\n"
        "  - field: contry\n"
        "    operator: eq\n"
        "    value: US\n"
    )
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    errs = [e for e in result.errors if e.code == "unknown_field"]
    assert len(errs) == 1
    assert errs[0].path == "filters[0].field"
    assert errs[0].did_you_mean == "country"


def test_unknown_top_level_key():
    yaml_text = (
        "sheet: test\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\ncolour: country\n"
    )
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    errs = [e for e in result.errors if e.code == "unknown_key"]
    assert len(errs) == 1
    assert errs[0].path == "colour"
    assert errs[0].did_you_mean == "color"


def test_parameter_reference_not_flagged_as_unknown_field():
    # `$name` / `${name}` are resolved before parse; the semantic pass runs on
    # the RAW dict, so it must skip them rather than flag them unknown_field.
    yaml_text = (
        "sheet: ${title}\ndata: orders\ncols: country\nrows: $revenue\nmarks: bar\n"
        "filters:\n  - field: region\n    operator: eq\n    value: $region\n"
    )
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert [e for e in result.errors if e.code == "unknown_field"] == []
    assert result.valid is True


def test_nested_union_typo_reports_single_error():
    # A typo inside a `str | ColorFieldMapping` object fails the str arm
    # (string_type at color.str) AND the object arm (unknown_key at color.tpe).
    # Only the informative one should survive — one mistake, one error, with a line.
    yaml_text = (
        "sheet: test\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
        "color:\n  field: region\n  tpe: nominal\n"
    )
    result = validate_chart_yaml(yaml_text, models_dir=MODELS_DIR)

    assert result.valid is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.code == "unknown_key"
    assert err.path == "color.tpe"
    assert err.line == 8
    assert "str" not in {e.path for e in result.errors}
