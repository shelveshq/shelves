"""
Parameter Schema Tests (SHE-89)

Validates the project-level `parameters.yaml` file format: the four parameter
types, the `values:` list grammar (literals / field references / range), and
every schema-level validation rule.

Parameters are NOT chart DSL — nothing here touches ChartSpec. Substitution is
covered in test_params_substitute.py.
"""

from __future__ import annotations

import datetime as dt

import pytest
import yaml
from pydantic import ValidationError

from shelves.params.loader import load_parameters
from shelves.params.schema import (
    DateParameter,
    FieldParameter,
    FieldRef,
    NumberParameter,
    ParametersFile,
    RangeBounds,
    StringParameter,
)
from tests.conftest import MODELS_DIR, params_fixture


def _parse(yaml_text: str) -> dict:
    """Validate a parameters block from inline YAML.

    Matches the inline-string style test_schema.py uses for chart specs —
    error cases stay readable next to their assertion.
    """
    return ParametersFile.model_validate(yaml.safe_load(yaml_text)).parameters


class TestFileFormat:
    def test_parameters_file_parses(self):
        params = load_parameters(params_fixture())
        assert set(params) == {
            "metric",
            "region",
            "status",
            "top_n",
            "as_of",
            "lo",
            "hi",
            "maybe_region",
            "week_grain",
        }

    def test_field_parameter_round_trips(self):
        params = load_parameters(params_fixture())
        assert isinstance(params["metric"], FieldParameter)
        assert params["metric"].values == [
            FieldRef(model="orders", field="revenue"),
            FieldRef(model="orders", field="cost"),
            FieldRef(model="orders", field="arpu"),
        ]
        assert params["metric"].default == "revenue"
        assert params["metric"].label == "Metric"

    def test_single_field_reference_is_a_domain(self):
        params = load_parameters(params_fixture())
        assert isinstance(params["region"], StringParameter)
        assert params["region"].values == [FieldRef(model="orders", field="region")]

    def test_literal_list_round_trips(self):
        params = load_parameters(params_fixture())
        assert params["status"].values == ["open", "closed", "pending"]

    def test_range_round_trips(self):
        params = load_parameters(params_fixture())
        assert isinstance(params["top_n"], NumberParameter)
        assert params["top_n"].values == [RangeBounds(min=5, max=50)]

    def test_null_default_parses(self):
        params = load_parameters(params_fixture())
        assert isinstance(params["as_of"], DateParameter)
        assert params["as_of"].default is None
        assert params["maybe_region"].default is None

    def test_date_range_bounds_parse(self):
        """YAML turns unquoted ISO dates into datetime.date — bounds accept it."""
        params = load_parameters(params_fixture())
        bounds = params["as_of"].values[0]
        assert isinstance(bounds, RangeBounds)
        assert bounds.min == dt.date(2024, 1, 1)
        assert bounds.max == dt.date(2026, 12, 31)

    def test_missing_file_is_empty(self, tmp_path):
        """A project without parameters is not an error."""
        assert load_parameters(tmp_path / "nope.yaml") == {}

    def test_empty_file_is_empty(self, tmp_path):
        target = tmp_path / "parameters.yaml"
        target.write_text("")
        assert load_parameters(target) == {}


class TestValuesShapes:
    def test_grain_suffix_preserved(self):
        """Dot notation is the temporal grain suffix — stored verbatim."""
        params = load_parameters(params_fixture())
        assert params["week_grain"].values == [FieldRef(model="orders", field="week.month")]

    def test_bare_model_entry_allows_any_field(self):
        params = _parse("""
parameters:
  anything:
    type: field
    values:
      - model: orders
    default: revenue
""")
        assert params["anything"].values == [FieldRef(model="orders", field=None)]

    def test_values_omitted_is_unconstrained(self):
        params = _parse("""
parameters:
  free_text:
    type: string
    default: hello
""")
        assert params["free_text"].values is None

    def test_numeric_looking_string_stays_string(self):
        params = _parse("""
parameters:
  code:
    type: string
    values:
      - "10"
      - "20"
    default: "10"
""")
        assert params["code"].default == "10"
        assert params["code"].values == ["10", "20"]


class TestValidationErrors:
    def test_e1_field_type_with_literal_entries(self):
        with pytest.raises(ValidationError, match="needs field references"):
            _parse("""
parameters:
  metric:
    type: field
    values:
      - revenue
      - cost
    default: revenue
""")

    def test_e2_field_type_with_range(self):
        with pytest.raises(ValidationError, match="range is not valid when type is 'field'"):
            _parse("""
parameters:
  metric:
    type: field
    values:
      - min: 1
        max: 5
    default: revenue
""")

    def test_e3_field_type_with_null_default(self):
        with pytest.raises(ValidationError, match="requires a non-null default"):
            _parse("""
parameters:
  metric:
    type: field
    values:
      - model: orders
        field: revenue
    default: null
""")

    def test_e4_field_type_with_no_values(self):
        with pytest.raises(ValidationError, match="requires 'values'"):
            _parse("""
parameters:
  metric:
    type: field
    default: revenue
""")

    def test_e5_default_outside_literal_list(self):
        with pytest.raises(ValidationError, match="is not in values"):
            _parse("""
parameters:
  region:
    type: string
    values:
      - EMEA
      - APAC
    default: LATAM
""")

    def test_e6_default_outside_range(self):
        with pytest.raises(ValidationError, match="is outside the range"):
            _parse("""
parameters:
  top_n:
    type: number
    values:
      - min: 5
        max: 50
    default: 99
""")

    def test_e7_default_not_among_field_references(self):
        with pytest.raises(ValidationError, match="is not in values"):
            _parse("""
parameters:
  metric:
    type: field
    values:
      - model: orders
        field: revenue
      - model: orders
        field: cost
    default: arpu
""")

    def test_e8_literal_type_with_multiple_field_references(self):
        with pytest.raises(ValidationError, match="at most one field reference"):
            _parse("""
parameters:
  region:
    type: string
    values:
      - model: orders
        field: region
      - model: orders
        field: country
    default: EMEA
""")

    def test_e9_mixing_entry_kinds(self):
        with pytest.raises(ValidationError, match="mixes entry kinds"):
            _parse("""
parameters:
  region:
    type: string
    values:
      - EMEA
      - model: orders
        field: region
    default: EMEA
""")

    def test_e9b_unrecognized_mapping_entry(self):
        with pytest.raises(ValidationError, match="unrecognized 'values' entry"):
            _parse("""
parameters:
  region:
    type: string
    values:
      - foo: bar
    default: EMEA
""")

    def test_e9c_values_not_a_list(self):
        """The likeliest authoring slip — omitting the dash."""
        with pytest.raises(ValidationError, match="must be a list"):
            _parse("""
parameters:
  region:
    type: string
    values:
      model: orders
      field: region
    default: EMEA
""")

    def test_e9c_message_shows_the_dashed_form(self):
        with pytest.raises(ValidationError) as exc:
            _parse("""
parameters:
  region:
    type: string
    values:
      model: orders
      field: region
    default: EMEA
""")
        assert "- model:" in str(exc.value)

    def test_e9d_multiple_range_entries(self):
        with pytest.raises(ValidationError, match="at most one min/max range"):
            _parse("""
parameters:
  top_n:
    type: number
    values:
      - min: 5
        max: 50
      - min: 60
        max: 90
    default: 10
""")

    def test_e10_default_missing(self):
        with pytest.raises(ValidationError, match="default"):
            _parse("""
parameters:
  region:
    type: string
    values:
      - EMEA
""")

    def test_empty_values_list(self):
        with pytest.raises(ValidationError, match="must not be an empty list"):
            _parse("""
parameters:
  region:
    type: string
    values: []
    default: EMEA
""")

    def test_unknown_type(self):
        with pytest.raises(ValidationError):
            _parse("""
parameters:
  region:
    type: boolean
    default: true
""")

    def test_bare_model_entry_rejected_on_literal_type(self):
        with pytest.raises(ValidationError, match="needs 'field'"):
            _parse("""
parameters:
  region:
    type: string
    values:
      - model: orders
    default: EMEA
""")


class TestFieldNameValidation:
    """E15/E16 — only run when models_dir is supplied."""

    def test_e15_unknown_field_in_model(self):
        with pytest.raises(ValueError, match="profitt"):
            load_parameters(
                params_fixture("parameters_invalid_unknown_field.yaml"),
                models_dir=MODELS_DIR,
                validate_fields=True,
            )

    def test_e16_unknown_model(self):
        with pytest.raises(ValueError, match="nope"):
            load_parameters(
                params_fixture("parameters_invalid_unknown_model.yaml"),
                models_dir=MODELS_DIR,
                validate_fields=True,
            )

    def test_field_check_skipped_without_flag(self):
        """Default is off, so the loader works with no model directory."""
        params = load_parameters(params_fixture("parameters_invalid_unknown_field.yaml"))
        assert "metric" in params

    def test_valid_fields_pass_validation(self):
        params = load_parameters(params_fixture(), models_dir=MODELS_DIR, validate_fields=True)
        assert "metric" in params
