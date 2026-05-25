"""
Tests for loader error wrapping — YAML parse errors and Pydantic validation errors
should include the file path in the error message.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shelves.models.loader import load_model, clear_model_cache

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "models"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def test_yaml_parse_error_includes_path():
    with pytest.raises(ValueError, match="invalid_yaml"):
        load_model("invalid_yaml", models_dir=FIXTURES_DIR)


def test_validation_error_includes_path():
    with pytest.raises(ValueError, match="invalid_schema"):
        load_model("invalid_schema", models_dir=FIXTURES_DIR)


def test_invalid_model_not_cached():
    """Bad models must NOT be cached — calling twice should raise both times."""
    with pytest.raises(ValueError):
        load_model("invalid_yaml", models_dir=FIXTURES_DIR)
    with pytest.raises(ValueError):
        load_model("invalid_yaml", models_dir=FIXTURES_DIR)
