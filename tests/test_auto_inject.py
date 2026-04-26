"""
Tests for auto-injection of labels, formats, grid defaults, legend titles,
tooltip titles/formats, and default sort from the data model.

All tests use the fixture orders model (tests/fixtures/models/orders.yaml).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from shelves.models.loader import clear_model_cache

from tests.conftest import load_yaml

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MODELS_DIR = FIXTURES_DIR / "models"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    yield
    clear_model_cache()


class TestAutoInject:
    def test_axis_titles_from_model(self):
        """Axis titles auto-injected from model labels; grid defaults applied; revenue format injected."""
        yaml_str = load_yaml("auto_inject_titles.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        x = vl["encoding"]["x"]
        assert x["field"] == "country"
        assert x["type"] == "nominal"
        assert x["title"] == "Country"
        assert x["axis"]["grid"] is False

        y = vl["encoding"]["y"]
        assert y["field"] == "revenue"
        assert y["type"] == "quantitative"
        assert y["title"] == "Revenue"
        assert y["axis"]["format"] == "$,.0f"
        assert y["axis"]["grid"] is True

    def test_explicit_title_overrides_model(self):
        """Explicit axis.y.title overrides model label; format still auto-injected."""
        yaml_str = load_yaml("auto_inject_title_override.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        y = vl["encoding"]["y"]
        assert y["title"] == "Total Rev ($)"
        assert y["axis"]["format"] == "$,.0f"
        assert y["axis"]["grid"] is True

    def test_measure_format_auto_injected(self):
        """encoding.y.axis.format is auto-injected from model's revenue format."""
        yaml_str = load_yaml("auto_inject_titles.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert vl["encoding"]["y"]["axis"]["format"] == "$,.0f"

    def test_explicit_format_overrides_model(self):
        """Chart-level axis format overrides model format."""
        yaml_str = load_yaml("auto_inject_format_override.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert vl["encoding"]["y"]["axis"]["format"] == ".2f"

    def test_temporal_dot_notation_format(self):
        """Temporal dot notation gets per-grain format and model title."""
        yaml_str = load_yaml("model_temporal_dot.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        x = vl["encoding"]["x"]
        assert x["axis"]["format"] == "%b %Y"
        assert x["title"] == "Week"

    def test_tooltip_auto_labels_and_formats(self):
        """Tooltip entries auto-get title from model label and format from model format."""
        yaml_str = load_yaml("auto_inject_tooltip.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        tooltip = vl["encoding"]["tooltip"]
        assert len(tooltip) == 2

        country_entry = next(e for e in tooltip if e["field"] == "country")
        assert country_entry["title"] == "Country"
        assert "format" not in country_entry

        revenue_entry = next(e for e in tooltip if e["field"] == "revenue")
        assert revenue_entry["title"] == "Revenue"
        assert revenue_entry["format"] == "$,.0f"

    def test_tooltip_explicit_format_overrides_model(self):
        """Explicit tooltip format overrides model format; title still auto-injected."""
        yaml_str = load_yaml("auto_inject_tooltip_override.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        tooltip = vl["encoding"]["tooltip"]
        revenue_entry = next(e for e in tooltip if e["field"] == "revenue")
        assert revenue_entry["format"] == ".2f"
        assert revenue_entry["title"] == "Revenue"

        country_entry = next(e for e in tooltip if e["field"] == "country")
        assert country_entry["title"] == "Country"

    def test_default_sort_from_measure(self):
        """When no explicit sort and x-field has no sortOrder, y-axis measure's defaultSort applies."""
        yaml_str = load_yaml("auto_inject_default_sort.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        x_sort = vl["encoding"]["x"].get("sort")
        assert x_sort == {"encoding": "y", "order": "descending"}

    def test_default_sort_order_from_dimension(self):
        """Dimension sortOrder on x-axis field takes precedence over measure defaultSort."""
        yaml_str = load_yaml("auto_inject_sort_order.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        x_sort = vl["encoding"]["x"].get("sort")
        assert x_sort == ["US", "UK", "FR", "DE", "JP"]

    def test_explicit_sort_overrides_model(self):
        """Explicit chart sort always wins over model defaults."""
        yaml_str = load_yaml("auto_inject_sort_explicit.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        x_sort = vl["encoding"]["x"].get("sort")
        assert x_sort == {"field": "revenue", "order": "ascending"}

    def test_legend_title_from_model(self):
        """Color field's model label auto-populates legend title."""
        yaml_str = load_yaml("auto_inject_legend.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        assert vl["encoding"]["color"]["legend"]["title"] == "Country"

    def test_stacked_panel_titles(self):
        """Each stacked panel gets measure label as axis title; format auto-injected."""
        yaml_str = load_yaml("auto_inject_stacked.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        panels = vl["vconcat"]
        assert len(panels) == 2

        # Revenue panel (bar) — top panel: shared x-axis is suppressed (KAN-232)
        revenue_panel = panels[0]
        x = revenue_panel["encoding"]["x"]
        assert x["axis"] is None
        assert "title" not in x
        y = revenue_panel["encoding"]["y"]
        assert y["title"] == "Revenue"
        assert y["axis"]["format"] == "$,.0f"

        # Orders panel (line) — bottom panel: shared x-axis shown
        orders_panel = panels[1]
        x = orders_panel["encoding"]["x"]
        assert x["title"] == "Week"
        assert x["axis"]["format"] == "%b %Y"
        y = orders_panel["encoding"]["y"]
        assert y["title"] == "Orders"
        assert y["axis"]["format"] == ",.0f"

    def test_stacked_vconcat_shared_axis_title(self):
        """Bottom stacked panel shows shared axis title; non-edge panels suppress it (KAN-232)."""
        yaml_str = load_yaml("model_stacked.yaml")
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)

        # Default axis hiding degrades repeat to vconcat
        assert "vconcat" in vl
        panels = vl["vconcat"]
        # Top panel: x axis suppressed
        assert panels[0]["encoding"]["x"]["axis"] is None
        # Bottom panel: x axis shown with title and format
        x_enc = panels[1]["encoding"]["x"]
        assert x_enc["title"] == "Week"
        assert x_enc["axis"]["format"] == "%b %Y"
