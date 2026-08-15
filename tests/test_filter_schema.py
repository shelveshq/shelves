"""
Filter schema tests — SHE-79.

Part 1: `contains` operator (schema validation + VL translation).
Part 2: Compose-time filter validation (mode↔field-type, model/field existence,
         target sheet existence, same-model constraint).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from shelves.schema.chart_schema import ShelfFilter
from shelves.schema.layout_schema import FilterMode
from shelves.translator.filters import _translate_filter
from tests.conftest import MODELS_DIR

# ─── Contains Operator: Schema Validation ──────────────────────────────


class TestContainsOperatorSchema:
    def test_contains_parses(self):
        f = ShelfFilter(field="name", operator="contains", value="foo")
        assert f.operator == "contains"
        assert f.value == "foo"

    def test_contains_forbids_values(self):
        with pytest.raises(ValidationError, match="values"):
            ShelfFilter(field="name", operator="contains", value="foo", values=["a", "b"])

    def test_contains_forbids_range(self):
        with pytest.raises(ValidationError, match="range"):
            ShelfFilter(field="name", operator="contains", value="foo", range=[1, 2])

    def test_contains_requires_value(self):
        with pytest.raises(ValidationError, match="value"):
            ShelfFilter(field="name", operator="contains")


# ─── Contains Operator: VL Translation ─────────────────────────────────


class TestContainsOperatorTranslation:
    def test_contains_produces_expression_filter(self):
        f = ShelfFilter(field="name", operator="contains", value="foo")
        result = _translate_filter(f)
        assert isinstance(result, str)
        assert "indexof" in result
        assert "lower" in result
        assert "foo" in result

    def test_contains_escapes_single_quotes(self):
        f = ShelfFilter(field="name", operator="contains", value="it's")
        result = _translate_filter(f)
        assert isinstance(result, str)
        assert "\\'" in result

    def test_contains_escapes_backslashes(self):
        f = ShelfFilter(field="name", operator="contains", value="a\\b")
        result = _translate_filter(f)
        assert isinstance(result, str)
        assert "a\\\\b" in result


# ─── Operator ↔ Field Type Warnings ───────────────────────────────────


class TestOperatorFieldTypeWarnings:
    """Warn when an operator doesn't match the field's semantic type."""

    @pytest.fixture()
    def _resolver(self):
        from shelves.models.resolver import ModelResolver
        from shelves.models.schema import DataModel

        model = DataModel.model_validate(
            {
                "model": "test",
                "label": "Test",
                "measures": {"revenue": {"label": "Revenue", "aggregation": "sum"}},
                "dimensions": {
                    "region": {"label": "Region"},
                    "week": {
                        "type": "temporal",
                        "label": "Week",
                        "defaultGrain": "week",
                    },
                },
            }
        )
        return ModelResolver(model)

    def test_contains_on_quantitative_warns(self, _resolver):
        from shelves.translator.filters import build_transforms

        f = ShelfFilter(field="revenue", operator="contains", value="foo")
        with pytest.warns(UserWarning, match="string operation"):
            build_transforms([f], _resolver)

    def test_contains_on_temporal_warns(self, _resolver):
        from shelves.translator.filters import build_transforms

        f = ShelfFilter(field="week", operator="contains", value="foo")
        with pytest.warns(UserWarning, match="string operation"):
            build_transforms([f], _resolver)

    def test_contains_on_nominal_no_warning(self, _resolver):
        from shelves.translator.filters import build_transforms

        f = ShelfFilter(field="region", operator="contains", value="foo")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            build_transforms([f], _resolver)
        assert not [w for w in caught if "string operation" in str(w.message)]

    def test_gt_on_nominal_warns(self, _resolver):
        from shelves.translator.filters import build_transforms

        f = ShelfFilter(field="region", operator="gt", value="A")
        with pytest.warns(UserWarning, match="numeric/temporal operation"):
            build_transforms([f], _resolver)

    def test_between_on_nominal_warns(self, _resolver):
        from shelves.translator.filters import build_transforms

        f = ShelfFilter(field="region", operator="between", range=[1, 10])
        with pytest.warns(UserWarning, match="numeric/temporal operation"):
            build_transforms([f], _resolver)

    def test_gt_on_quantitative_no_warning(self, _resolver):
        from shelves.translator.filters import build_transforms

        f = ShelfFilter(field="revenue", operator="gt", value=100)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            build_transforms([f], _resolver)
        assert not [w for w in caught if "numeric/temporal operation" in str(w.message)]

    def test_eq_on_any_type_no_warning(self, _resolver):
        from shelves.translator.filters import build_transforms

        for field in ("region", "revenue", "week"):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                build_transforms([ShelfFilter(field=field, operator="eq", value="x")], _resolver)
            type_warnings = [
                w
                for w in caught
                if "operation" in str(w.message) and "unexpected" in str(w.message)
            ]
            assert not type_warnings, f"Unexpected warning for eq on {field}"


# ─── Compose-Time Validation ───────────────────────────────────────────


class TestFilterValidation:
    """Compose-time validation: mode↔field-type, model/field, targets, same-model."""

    @pytest.fixture()
    def _chart_dir(self, tmp_path: Path) -> Path:
        """Create minimal chart YAML files referencing model 'orders'."""
        chart = tmp_path / "revenue_by_region.yaml"
        chart.write_text(
            "sheet: Revenue by Region\ndata: orders\ncols: region\nrows: revenue\nmarks: bar\n"
        )
        return tmp_path

    # --- Mode ↔ field type: valid combos ---

    @pytest.mark.parametrize("mode", ["multi", "single", "wildcard"])
    def test_mode_valid_for_dimension(self, mode: FilterMode, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode=mode)
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert not errors

    @pytest.mark.parametrize("mode", ["range", "at_least", "at_most"])
    def test_mode_valid_for_quantitative(self, mode: FilterMode, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="revenue", model="orders", mode=mode)
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert not errors

    @pytest.mark.parametrize("mode", ["range", "after", "before"])
    def test_mode_valid_for_temporal(self, mode: FilterMode, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="week", model="orders", mode=mode)
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert not errors

    # --- Mode ↔ field type: invalid combos ---

    @pytest.mark.parametrize("mode", ["range", "at_least", "at_most", "after", "before"])
    def test_mode_invalid_for_dimension(self, mode: FilterMode, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode=mode)
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("region" in e for e in errors)

    @pytest.mark.parametrize("mode", ["multi", "single", "wildcard", "after", "before"])
    def test_mode_invalid_for_quantitative(self, mode: FilterMode, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="revenue", model="orders", mode=mode)
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("revenue" in e for e in errors)

    @pytest.mark.parametrize("mode", ["multi", "single", "wildcard", "at_least", "at_most"])
    def test_mode_invalid_for_temporal(self, mode: FilterMode, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="week", model="orders", mode=mode)
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("week" in e for e in errors)

    # --- Duplicate (model, field, mode) uniqueness (SHE-82 review) ---

    def test_duplicate_model_field_mode_rejected(self, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filts = [
            FilterComponent(field="region", model="orders", mode="single"),
            FilterComponent(field="region", model="orders", mode="single"),
        ]
        errors = _validate_filters(
            filts,
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("Duplicate filter" in e for e in errors)

    def test_same_field_different_mode_allowed(self, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filts = [
            FilterComponent(field="region", model="orders", mode="single"),
            FilterComponent(field="region", model="orders", mode="wildcard"),
        ]
        errors = _validate_filters(
            filts,
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert not any("Duplicate filter" in e for e in errors)

    def test_duplicate_inferred_mode_rejected(self, _chart_dir: Path):
        """Two mode-less filters on one dimension both infer 'multi' → clash."""
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filts = [
            FilterComponent(field="region", model="orders"),
            FilterComponent(field="region", model="orders"),
        ]
        errors = _validate_filters(
            filts,
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("Duplicate filter" in e for e in errors)

    # --- Model / field existence ---

    def test_nonexistent_model(self, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="no_such_model")
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("no_such_model" in e for e in errors)

    def test_nonexistent_field(self, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="no_such_field", model="orders")
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("no_such_field" in e for e in errors)

    # --- Target sheet existence ---

    def test_nonexistent_target_sheet(self, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", targets=["no_such_sheet"])
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert any("no_such_sheet" in e for e in errors)

    # --- Same-model constraint ---

    def test_same_model_violation(self, tmp_path: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        chart = tmp_path / "chart.yaml"
        chart.write_text("sheet: Chart\ndata: minimal\ncols: d1\nrows: m1\nmarks: bar\n")
        filt = FilterComponent(field="region", model="orders", targets=["sheet_a"])
        errors = _validate_filters(
            [filt],
            sheets={"sheet_a": "chart.yaml"},
            charts_dir=tmp_path,
            models_dir=MODELS_DIR,
        )
        assert any("orders" in e or "minimal" in e for e in errors)

    def test_targets_all_matching_zero_sheets(self, tmp_path: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        chart = tmp_path / "chart.yaml"
        chart.write_text("sheet: Chart\ndata: minimal\ncols: d1\nrows: m1\nmarks: bar\n")
        filt = FilterComponent(field="region", model="orders", targets="all")
        errors = _validate_filters(
            [filt],
            sheets={"sheet_a": "chart.yaml"},
            charts_dir=tmp_path,
            models_dir=MODELS_DIR,
        )
        assert any("orders" in e for e in errors)

    # --- Mode=None passes (inferred later) ---

    def test_mode_none_passes(self, _chart_dir: Path):
        from shelves.compose.dashboard import _validate_filters
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode=None)
        errors = _validate_filters(
            [filt],
            sheets={"chart_1": "revenue_by_region.yaml"},
            charts_dir=_chart_dir,
            models_dir=MODELS_DIR,
        )
        assert not errors


class TestFilterValidationIntegration:
    """Integration tests that go through compose_dashboard, not direct calls."""

    def test_compose_dashboard_runs_filter_validation(self, tmp_path: Path):
        """Filters with a bad model should raise when composed through the public API."""
        from shelves.compose.dashboard import compose_dashboard

        chart = tmp_path / "chart.yaml"
        chart.write_text("sheet: Chart\ndata: orders\ncols: region\nrows: revenue\nmarks: bar\n")
        dashboard = tmp_path / "dashboard.yaml"
        dashboard.write_text(
            "dashboard: Test\n"
            "canvas:\n  width: 800\n  height: 600\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - filter: region\n"
            "      model: no_such_model\n"
            "    - sheet: chart.yaml\n"
            "      name: chart_1\n"
        )
        with pytest.raises(ValueError, match="no_such_model"):
            compose_dashboard(
                dashboard,
                chart_base_dir=tmp_path,
                models_dir=MODELS_DIR,
            )

    def test_compose_dashboard_valid_filter_passes(self, tmp_path: Path):
        """A valid filter should not block dashboard composition."""
        from shelves.compose.dashboard import compose_dashboard

        chart = tmp_path / "chart.yaml"
        chart.write_text("sheet: Chart\ndata: orders\ncols: region\nrows: revenue\nmarks: bar\n")
        dashboard = tmp_path / "dashboard.yaml"
        dashboard.write_text(
            "dashboard: Test\n"
            "canvas:\n  width: 800\n  height: 600\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - filter: region\n"
            "      model: orders\n"
            "    - sheet: chart.yaml\n"
            "      name: chart_1\n"
        )
        html = compose_dashboard(
            dashboard,
            chart_base_dir=tmp_path,
            models_dir=MODELS_DIR,
        )
        assert "filter-" in html
