"""
Pipeline Tests

Tests for shelves/pipeline.py — the consolidated chart compilation pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest

from tests.conftest import FIXTURES_DIR, MODELS_DIR, load_yaml, params_fixture

THEMES_DIR = Path(__file__).parent / "fixtures" / "themes"
CUSTOM_THEME_PATH = THEMES_DIR / "custom_brand.yaml"


class TestCompileChart:
    def test_returns_themed_vl_spec(self):
        from shelves.pipeline import compile_chart

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, _spec = compile_chart(yaml_text, models_dir=MODELS_DIR)

        assert "$schema" in vl_spec
        assert "mark" in vl_spec
        assert "config" in vl_spec
        assert "data" not in vl_spec

    def test_result_is_dict(self):
        from shelves.pipeline import compile_chart

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, _spec = compile_chart(yaml_text, models_dir=MODELS_DIR)

        assert isinstance(vl_spec, dict)
        assert all(isinstance(k, str) for k in vl_spec)

    def test_no_theme_skips_merge(self):
        from shelves.pipeline import compile_chart

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, _spec = compile_chart(yaml_text, no_theme=True, models_dir=MODELS_DIR)

        assert "config" not in vl_spec

    def test_custom_theme_path(self):
        from shelves.pipeline import compile_chart

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, _spec = compile_chart(
            yaml_text,
            theme_path=CUSTOM_THEME_PATH,
            models_dir=MODELS_DIR,
        )

        # custom_brand.yaml sets mark.color to #e94560
        assert vl_spec["config"]["mark"]["color"] == "#e94560"

    def test_returns_chart_spec(self):
        from shelves.pipeline import compile_chart
        from shelves.schema.chart_schema import ChartSpec

        yaml_text = load_yaml("simple_bar.yaml")
        _vl_spec, spec = compile_chart(yaml_text, models_dir=MODELS_DIR)

        assert isinstance(spec, ChartSpec)
        assert spec.sheet == "Revenue by Country"


class TestCompileChartParameters:
    """SHE-91: `compile_chart` threads a ParameterSet, and NEVER loads one."""

    def test_override_reaches_encoding(self):
        from shelves.params.resolve import load_parameter_set
        from shelves.pipeline import compile_chart

        params = load_parameter_set(
            params_fixture(),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            overrides={"metric": "cost"},
        )
        vl, spec = compile_chart(
            load_yaml("param_field_swap.yaml"),
            no_theme=True,
            models_dir=MODELS_DIR,
            parameters=params,
        )

        # Label and format come from orders.yaml's `cost` measure — proof the
        # swap happened BEFORE parsing, not after.
        assert vl["encoding"]["y"]["field"] == "cost"
        assert vl["encoding"]["y"]["title"] == "Cost"
        assert spec.sheet == "Metric by Country"

    def test_reference_output_matches_every_surface(self):
        """The full no-theme spec the four-surface parity tests compare against."""
        from shelves.params.resolve import load_parameter_set
        from shelves.pipeline import compile_chart

        params = load_parameter_set(
            params_fixture(),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            overrides={"metric": "cost"},
        )
        vl, _spec = compile_chart(
            load_yaml("param_field_swap.yaml"),
            no_theme=True,
            models_dir=MODELS_DIR,
            parameters=params,
        )

        assert vl == {
            "mark": "bar",
            "encoding": {
                "x": {
                    "field": "country",
                    "type": "nominal",
                    "title": "Country",
                    "sort": ["US", "UK", "FR", "DE", "JP"],
                },
                "y": {
                    "field": "cost",
                    "type": "quantitative",
                    "title": "Cost",
                    "axis": {"format": "$,.0f"},
                },
            },
            "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
            "title": "Metric by Country",
        }

    def test_omitted_parameters_is_empty_set(self):
        from shelves.params.substitute import ParameterSet
        from shelves.pipeline import compile_chart

        vl_a, _ = compile_chart(load_yaml("simple_bar.yaml"), models_dir=MODELS_DIR)
        vl_b, _ = compile_chart(
            load_yaml("simple_bar.yaml"),
            models_dir=MODELS_DIR,
            parameters=ParameterSet.empty(),
        )
        assert vl_a == vl_b

    def test_models_dir_containing_parameters_file_is_not_auto_loaded(self):
        """The backward-compatibility rule: compile_chart does no parameter I/O.

        MODELS_DIR contains a parameters.yaml declaring `metric`. If compile_chart
        auto-loaded it, this reference would resolve — silently changing the
        meaning of every existing test that passes models_dir=MODELS_DIR.
        """
        from shelves.pipeline import compile_chart

        with pytest.raises(ValueError, match=r"Declared in models/parameters\.yaml: \(none\)"):
            compile_chart(load_yaml("param_field_swap.yaml"), models_dir=MODELS_DIR)


class TestCompileChartInlineData:
    def test_inline_rows_bound(self):
        from shelves.data.bind import resolve_data
        from shelves.pipeline import compile_chart

        yaml_text = load_yaml("simple_bar.yaml")
        rows = [{"category": "A", "net_sales": 100}]
        vl_spec, spec = compile_chart(yaml_text, models_dir=MODELS_DIR)
        vl_spec = resolve_data(vl_spec, spec, rows=rows)

        assert vl_spec["data"]["values"] == rows

    def test_empty_rows_bound(self):
        from shelves.data.bind import resolve_data
        from shelves.pipeline import compile_chart

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, spec = compile_chart(yaml_text, models_dir=MODELS_DIR)
        vl_spec = resolve_data(vl_spec, spec, rows=[])

        assert vl_spec["data"]["values"] == []


class TestCompileChartToHTML:
    def test_returns_html(self):
        from shelves.pipeline import compile_chart
        from shelves.render.to_html import render_html

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, spec = compile_chart(yaml_text, models_dir=MODELS_DIR)
        html = render_html(vl_spec, title=spec.sheet)

        assert "<!DOCTYPE html>" in html
        assert "vegaEmbed" in html
        assert "bar" in html


class TestCompileChartErrors:
    def test_invalid_yaml_raises(self):
        from shelves.pipeline import compile_chart

        # Valid YAML but missing required `sheet` field → ValidationError
        with pytest.raises(pydantic.ValidationError):
            compile_chart("dashboard: Sales", models_dir=MODELS_DIR)

    def test_empty_yaml_raises(self):
        from shelves.pipeline import compile_chart

        with pytest.raises((ValueError, TypeError, AttributeError)):
            compile_chart("", models_dir=MODELS_DIR)


class TestResolveModelData:
    def test_inline_binds_when_file_exists(self):
        """Inline model with existing data file binds rows onto the spec."""
        from shelves.pipeline import compile_chart, resolve_model_data

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, spec = compile_chart(yaml_text, no_theme=True, models_dir=MODELS_DIR)

        result = resolve_model_data(
            vl_spec,
            spec,
            models_dir=MODELS_DIR,
            data_base_dir=MODELS_DIR.parent,  # tests/fixtures/
        )

        assert "data" in result
        assert isinstance(result["data"]["values"], list)
        assert len(result["data"]["values"]) > 0

    def test_inline_missing_file_returns_spec_unchanged(self):
        """Inline model with non-existent data file returns vl_spec unchanged."""
        from shelves.pipeline import compile_chart, resolve_model_data

        yaml_text = load_yaml("simple_bar.yaml")
        vl_spec, spec = compile_chart(yaml_text, no_theme=True, models_dir=MODELS_DIR)

        result = resolve_model_data(
            vl_spec,
            spec,
            models_dir=MODELS_DIR,
            data_base_dir=Path("/nonexistent/base"),
        )

        assert "data" not in result
        assert result == vl_spec

    def test_cube_delegates_to_resolve_data(self):
        """Cube-source model delegates to resolve_data."""
        from unittest.mock import patch

        from shelves.pipeline import compile_chart, resolve_model_data

        yaml_text = (
            'sheet: "Cube Test"\ndata: cube_orders\ncols: category\nrows: net_sales\nmarks: bar\n'
        )
        vl_spec, spec = compile_chart(yaml_text, no_theme=True, models_dir=MODELS_DIR)

        fake_rows = [{"category": "A", "net_sales": 100}]
        with patch(
            "shelves.data.bind.resolve_data",
            return_value={**vl_spec, "data": {"values": fake_rows}},
        ) as mock_rd:
            result = resolve_model_data(vl_spec, spec, models_dir=MODELS_DIR)

        assert mock_rd.called
        assert result["data"]["values"] == fake_rows
