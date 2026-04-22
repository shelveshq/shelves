"""
Chart Title and Subtitle Tests (KAN-222)

Tests that translate_chart() injects title/subtitle from spec.sheet/description,
and that show_title in the dashboard Layout DSL correctly suppresses them.
"""

from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from shelves.compose.dashboard import compose_dashboard
from tests.conftest import compile_fixture, MODELS_DIR, YAML_DIR, DATA_DIR


class TestChartTitle:
    def test_single_measure_has_title(self):
        vl = compile_fixture("simple_bar.yaml")
        assert vl["title"] == "Revenue by Country"

    def test_title_with_subtitle(self):
        vl = compile_fixture("title_with_subtitle.yaml")
        assert vl["title"] == {
            "text": "Revenue by Country",
            "subtitle": "Weekly aggregate revenue across all product lines",
        }

    def test_stacked_repeat_has_title(self):
        vl = compile_fixture("stacked_panels.yaml")
        assert vl["title"] == "Key Metrics by Week"

    def test_stacked_concat_has_title(self):
        vl = compile_fixture("stacked_diff_marks.yaml")
        assert vl["title"] == "Revenue and Orders"

    def test_faceted_chart_has_title(self):
        vl = compile_fixture("facet_wrap.yaml")
        assert vl["title"] == "Revenue Trend by Country"

    def test_empty_description_gives_plain_title(self):
        yaml_str = """\
sheet: "My Chart"
description: ""
data: orders
cols: country
rows: revenue
marks: bar
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert vl["title"] == "My Chart"

    def test_special_chars_in_title(self):
        yaml_str = """\
sheet: "Revenue & Forecast"
data: orders
cols: country
rows: revenue
marks: bar
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert vl["title"] == "Revenue & Forecast"

    def test_single_entry_multi_measure_has_title(self):
        yaml_str = """\
sheet: "Single Measure"
data: orders
cols: week
rows:
  - measure: revenue
    mark: line
"""
        spec = parse_chart(yaml_str)
        vl = translate_chart(spec, models_dir=MODELS_DIR)
        assert vl["title"] == "Single Measure"


class TestDashboardTitle:
    def _compose(self, yaml_str: str) -> str:
        """Write a temp dashboard file and compose it."""
        tmp_path = DATA_DIR.parent / "_tmp_title_test.yaml"
        tmp_path.write_text(yaml_str)
        try:
            html = compose_dashboard(
                dashboard_path=tmp_path,
                chart_base_dir=YAML_DIR,
                data_dir=DATA_DIR,
                models_dir=MODELS_DIR,
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        return html

    def test_show_title_default_preserves_title(self):
        yaml_str = """\
dashboard: "Title Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: simple_bar.yaml
      name: revenue_chart
"""
        html = self._compose(yaml_str)
        assert '"title": "Revenue by Country"' in html

    def test_show_title_false_suppresses_title(self):
        yaml_str = """\
dashboard: "No Title Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: simple_bar.yaml
      name: revenue_chart
      show_title: false
"""
        html = self._compose(yaml_str)
        assert '"title": null' in html or '"title":null' in html

    def test_subtitle_in_dashboard(self):
        yaml_str = """\
dashboard: "Subtitle Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: title_with_subtitle.yaml
      name: revenue_chart
"""
        html = self._compose(yaml_str)
        assert '"subtitle": "Weekly aggregate revenue across all product lines"' in html

    def test_show_title_false_suppresses_subtitle_too(self):
        yaml_str = """\
dashboard: "No Subtitle Test"
canvas: { width: 800, height: 600 }
root:
  orientation: vertical
  contains:
    - sheet: title_with_subtitle.yaml
      name: revenue_chart
      show_title: false
"""
        html = self._compose(yaml_str)
        assert '"title": null' in html or '"title":null' in html
