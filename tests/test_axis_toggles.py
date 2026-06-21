"""
Tests for per-channel axis toggles (grid/ruler/ticks/labels), the bool
shorthand (axis off / on), the theme-default grid migration and its precedence,
and composition with data labels.

All translation tests use the fixture orders model
(tests/fixtures/models/orders.yaml).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shelves.models.loader import clear_model_cache
from shelves.schema.chart_schema import parse_chart
from shelves.theme.merge import merge_theme
from shelves.translator.translate import translate_chart
from tests.conftest import load_yaml

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MODELS_DIR = FIXTURES_DIR / "models"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def _compile(name: str) -> dict:
    spec = parse_chart(load_yaml(name))
    return translate_chart(spec, models_dir=MODELS_DIR)


class TestAxisToggles:
    def test_granular_toggles(self):
        """Each DSL toggle maps to the correct VL axis property; ruler→domain."""
        vl = _compile("axis_toggles.yaml")

        x_axis = vl["encoding"]["x"]["axis"]
        assert x_axis["grid"] is True
        assert x_axis["domain"] is False  # ruler → domain
        assert x_axis["ticks"] is False
        assert x_axis["labels"] is False

        y_axis = vl["encoding"]["y"]["axis"]
        assert y_axis["grid"] is False
        assert y_axis["domain"] is True  # ruler → domain
        assert y_axis["ticks"] is True
        assert "labels" not in y_axis  # not set → not emitted (inherits theme)
        assert y_axis["format"] == "$,.0f"  # model format still auto-injected

    def test_x_axis_off_shorthand(self):
        """axis.x: false sets encoding.x.axis = null and skips auto-inject there."""
        vl = _compile("axis_x_off.yaml")

        assert vl["encoding"]["x"]["axis"] is None  # axis removed entirely
        assert "title" not in vl["encoding"]["x"]  # auto-inject skipped when axis off
        assert vl["encoding"]["y"]["axis"]["grid"] is True
        assert vl["encoding"]["y"]["axis"]["format"] == "$,.0f"
        assert vl["encoding"]["y"]["title"] == "Revenue"

    def test_axis_true_is_noop(self):
        """axis.y: true shows the axis with defaults — same as omitting the block."""
        vl = _compile("axis_y_true.yaml")

        y = vl["encoding"]["y"]
        assert y["title"] == "Revenue"
        assert y["axis"]["format"] == "$,.0f"
        assert "grid" not in y["axis"]  # no override → inherits theme default
        assert "domain" not in y["axis"]
        assert "ticks" not in y["axis"]

    def test_grid_precedence_over_theme(self):
        """Per-chart axis.x.grid overrides the theme default; both coexist."""
        spec = parse_chart(load_yaml("axis_grid_override.yaml"))
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        merged = merge_theme(vl, None)  # default theme

        # Encoding-level override is present (Vega-Lite resolves this first)
        assert merged["encoding"]["x"]["axis"]["grid"] is True
        # Theme still carries the x-off default in config (encoding wins at render)
        assert merged["config"]["axisX"]["grid"] is False
        assert merged["config"]["axisY"]["grid"] is True

    def test_no_axis_block_inherits_theme_grid(self):
        """A chart with no axis block emits no encoding grid; theme supplies it."""
        spec = parse_chart(load_yaml("auto_inject_titles.yaml"))
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Grid is NO LONGER injected at the encoding level...
        assert "grid" not in vl["encoding"]["x"].get("axis", {})
        assert "grid" not in vl["encoding"]["y"].get("axis", {})

        # ...it now comes from the theme after merge.
        merged = merge_theme(vl, None)
        assert merged["config"]["axisX"]["grid"] is False
        assert merged["config"]["axisY"]["grid"] is True

    def test_toggles_compose_with_labels(self):
        """Axis toggles and data-label intent compose without interfering."""
        vl = _compile("axis_toggles_with_label.yaml")

        # Axis toggles applied as usual
        assert vl["encoding"]["x"]["axis"] is None
        assert vl["encoding"]["y"]["axis"]["grid"] is False
        assert vl["encoding"]["y"]["axis"]["ticks"] is True
        # x still carries its field/type/scale-bearing encoding (axis null ≠ field
        # removed), so the label patch can still find the scale for placement.
        assert vl["encoding"]["x"]["field"] == "country"

        # Label intent is still emitted, untouched by the axis changes
        intents = vl["usermeta"]["shelves"]["labels"]
        assert len(intents) == 1
        assert intents[0]["markName"] == "mark_0"
        assert intents[0]["field"] == "revenue"

    def test_invalid_channel_value_type(self):
        """A list value for an axis channel is neither bool nor config object."""
        with pytest.raises(ValidationError):
            parse_chart(load_yaml("axis_invalid_channel.yaml"))

    def test_invalid_toggle_value(self):
        """A non-bool-coercible toggle value is rejected."""
        with pytest.raises(ValidationError):
            parse_chart(load_yaml("axis_invalid_toggle.yaml"))
