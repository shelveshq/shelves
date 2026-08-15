"""
Filter injection tests — SHE-80.

Part 1: Compose-time filter injection (mode→operator, ShelfFilter construction,
         injection into target sheets, mode inference).
Part 2: Control placeholder emission (data-* attributes on rendered HTML).
Part 3: Edge cases (no filters, coexistence, multiple filters, etc.).
Part 4: Error cases (bad defaults for mode).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shelves.data.domains import clear_domain_cache
from tests.conftest import DATA_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR

# ─── Helpers ──────────────────────────────────────────────────────────


def _compose(fixture_name: str, **kwargs) -> str:
    from shelves.compose.dashboard import compose_dashboard

    clear_domain_cache()
    return compose_dashboard(
        dashboard_path=LAYOUT_DIR / fixture_name,
        chart_base_dir=YAML_DIR,
        data_dir=DATA_DIR,
        models_dir=MODELS_DIR,
        **kwargs,
    )


def _get_vl_transforms(html: str, sheet_id: str) -> list[dict]:
    """Extract VL transforms for a sheet from the compiled HTML."""
    import re

    specs_match = re.search(r"const specs = ({.*?});", html, re.DOTALL)
    if not specs_match:
        return []
    specs = json.loads(specs_match.group(1))
    spec = specs.get(f"sheet-{sheet_id}", {})
    return spec.get("transform", [])


def _parse_filter_div(html_str: str, dom_id: str) -> dict[str, str]:
    """Extract data-* attributes from a filter div in the HTML."""
    from html.parser import HTMLParser

    class _AttrParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.attrs: dict[str, str] = {}
            self.found = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
            for k, v in attrs:
                if k == "id" and v == f"filter-{dom_id}":
                    self.found = True
            if self.found:
                for k, v in attrs:
                    if k.startswith("data-") and v is not None:
                        self.attrs[k[5:]] = v

    parser = _AttrParser()
    parser.feed(html_str)
    return parser.attrs


# ─── Part 1: Filter Injection Logic ──────────────────────────────────


class TestFilterInjectionNullDefault:
    """default: null → no filter injected, sheets compile identically."""

    def test_null_default_no_transforms(self):
        html = _compose("filter_null_default.yaml")
        transforms_1 = _get_vl_transforms(html, "chart_1")
        transforms_2 = _get_vl_transforms(html, "chart_2")
        filter_transforms_1 = [t for t in transforms_1 if "filter" in t]
        filter_transforms_2 = [t for t in transforms_2 if "filter" in t]
        assert filter_transforms_1 == []
        assert filter_transforms_2 == []

    def test_null_default_placeholder_still_rendered(self):
        html = _compose("filter_null_default.yaml")
        assert 'id="filter-' in html


class TestFilterInjectionSingleMode:
    """mode: single, default: "EMEA" → eq transform on target sheets."""

    def test_single_default_injects_eq_transform(self):
        html = _compose("filter_single_default.yaml")
        transforms = _get_vl_transforms(html, "chart_1")
        eq_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and t["filter"].get("equal") is not None
        ]
        assert any(f.get("field") == "region" and f.get("equal") == "EMEA" for f in eq_filters)

    def test_single_default_also_targets_chart_2(self):
        """targets: all means both sheets get the filter."""
        html = _compose("filter_single_default.yaml")
        transforms = _get_vl_transforms(html, "chart_2")
        eq_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and t["filter"].get("equal") is not None
        ]
        assert any(f.get("field") == "region" for f in eq_filters)


class TestFilterInjectionAllModes:
    """Test mode→operator mapping for each mode via direct unit tests."""

    def test_multi_mode(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="region", model="orders", mode="multi", default=["US", "UK"]
        )
        transforms = _get_vl_transforms(html, "chart_1")
        in_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and "oneOf" in t["filter"]
        ]
        assert any(f["field"] == "region" and f["oneOf"] == ["US", "UK"] for f in in_filters)

    def test_wildcard_mode(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="product", model="orders", mode="wildcard", default="wid"
        )
        transforms = _get_vl_transforms(html, "chart_1")
        expr_filters = [t["filter"] for t in transforms if isinstance(t.get("filter"), str)]
        assert any("indexof" in f and "wid" in f for f in expr_filters)

    def test_range_mode_quantitative(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="revenue", model="orders", mode="range", default=[100, 500]
        )
        transforms = _get_vl_transforms(html, "chart_1")
        range_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and "range" in t["filter"]
        ]
        assert any(f["field"] == "revenue" and f["range"] == [100, 500] for f in range_filters)

    def test_at_least_mode(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="revenue", model="orders", mode="at_least", default=100
        )
        transforms = _get_vl_transforms(html, "chart_1")
        gte_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and "gte" in t["filter"]
        ]
        assert any(f["field"] == "revenue" and f["gte"] == 100 for f in gte_filters)

    def test_at_most_mode(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="revenue", model="orders", mode="at_most", default=500
        )
        transforms = _get_vl_transforms(html, "chart_1")
        lte_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and "lte" in t["filter"]
        ]
        assert any(f["field"] == "revenue" and f["lte"] == 500 for f in lte_filters)

    def test_after_mode_temporal(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="week", model="orders", mode="after", default="2024-01-01"
        )
        transforms = _get_vl_transforms(html, "chart_1")
        gte_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and "gte" in t["filter"]
        ]
        assert any(f["field"] == "week" and f["gte"] == "2024-01-01" for f in gte_filters)

    def test_before_mode_temporal(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="week", model="orders", mode="before", default="2024-12-31"
        )
        transforms = _get_vl_transforms(html, "chart_1")
        lte_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and "lte" in t["filter"]
        ]
        assert any(f["field"] == "week" and f["lte"] == "2024-12-31" for f in lte_filters)

    def test_range_mode_temporal(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path,
            field="week",
            model="orders",
            mode="range",
            default=["2024-01-01", "2024-12-31"],
        )
        transforms = _get_vl_transforms(html, "chart_1")
        range_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and "range" in t["filter"]
        ]
        assert any(f["field"] == "week" for f in range_filters)


class TestFilterInjectionTargets:
    def test_explicit_target_only_injects_named_sheet(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path,
            field="region",
            model="orders",
            mode="single",
            default="EMEA",
            targets=["chart_1"],
        )
        transforms_1 = _get_vl_transforms(html, "chart_1")
        transforms_2 = _get_vl_transforms(html, "chart_2")
        eq_1 = [
            t["filter"]
            for t in transforms_1
            if isinstance(t.get("filter"), dict) and t["filter"].get("equal") is not None
        ]
        eq_2 = [
            t["filter"]
            for t in transforms_2
            if isinstance(t.get("filter"), dict) and t["filter"].get("equal") is not None
        ]
        assert any(f.get("field") == "region" for f in eq_1)
        assert not any(f.get("field") == "region" for f in eq_2)


class TestFilterInjectionCoexistence:
    def test_coexists_with_chart_level_filters(self, tmp_path: Path):
        """Dashboard filter + chart-level filter → both appear as transforms."""
        chart_yaml = (
            "sheet: Filtered Chart\n"
            "data: orders\n"
            "cols: region\n"
            "rows: revenue\n"
            "marks: bar\n"
            "filters:\n"
            "  - field: country\n"
            "    operator: eq\n"
            "    value: US\n"
        )
        chart_path = tmp_path / "filtered_chart.yaml"
        chart_path.write_text(chart_yaml)

        dashboard_yaml = (
            "dashboard: Coexistence Test\n"
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - filter: region\n"
            "      model: orders\n"
            "      mode: single\n"
            "      default: EMEA\n"
            "    - sheet: filtered_chart.yaml\n"
            "      name: chart_1\n"
        )
        dashboard_path = tmp_path / "dashboard.yaml"
        dashboard_path.write_text(dashboard_yaml)

        from shelves.compose.dashboard import compose_dashboard

        html = compose_dashboard(dashboard_path, chart_base_dir=tmp_path, models_dir=MODELS_DIR)
        transforms = _get_vl_transforms(html, "chart_1")
        filter_preds = [t["filter"] for t in transforms if "filter" in t]
        # Chart-level: country eq US
        assert any(
            isinstance(f, dict) and f.get("field") == "country" and f.get("equal") == "US"
            for f in filter_preds
        )
        # Dashboard-level: region eq EMEA
        assert any(
            isinstance(f, dict) and f.get("field") == "region" and f.get("equal") == "EMEA"
            for f in filter_preds
        )


# ─── Part 2: Placeholder Emission ────────────────────────────────────


class TestFilterPlaceholderAttributes:
    def test_placeholder_has_all_data_attributes(self):
        html = _compose("filter_single_default.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["type"] == "filter"
        assert attrs["field"] == "region"
        assert attrs["model"] == "orders"
        assert attrs["mode"] == "single"
        assert attrs["operator"] == "eq"
        assert attrs["control"] == "dropdown"
        assert "targets" in attrs
        assert "title" in attrs

    def test_placeholder_default_present(self):
        html = _compose("filter_single_default.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert "default" in attrs

    def test_placeholder_null_default_omits_data_default(self):
        html = _compose("filter_null_default.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert "default" not in attrs

    def test_placeholder_options_null(self):
        """data-options is null until SHE-81."""
        html = _compose("filter_single_default.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs.get("options") == "null"

    def test_placeholder_targets_json(self):
        html = _compose("filter_single_default.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        targets = json.loads(attrs["targets"])
        assert isinstance(targets, list)
        assert "sheet-chart_1" in targets
        assert "sheet-chart_2" in targets

    def test_placeholder_label_override(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path,
            field="region",
            model="orders",
            mode="single",
            default="EMEA",
            label="My Region Filter",
        )
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["title"] == "My Region Filter"


class TestFilterDropdownWidget:
    """SHE-8x: the `dropdown` flag picks the widget for single/multi modes."""

    def test_single_defaults_to_dropdown(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="region", model="orders", mode="single", default=None
        )
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["control"] == "dropdown"

    def test_single_dropdown_false_uses_single_list(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="region", model="orders", mode="single", default=None, dropdown=False
        )
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["control"] == "single_list"

    def test_multi_defaults_to_native_dropdown(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="region", model="orders", mode="multi", default=None
        )
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["control"] == "multi_dropdown"

    def test_multi_dropdown_false_uses_open_list(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="region", model="orders", mode="multi", default=None, dropdown=False
        )
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["control"] == "multi_select"


# ─── Part 3: Edge Cases ──────────────────────────────────────────────


class TestFilterEdgeCases:
    def test_no_filters_dashboard_unchanged(self):
        """Dashboard without filters produces identical output to before."""
        html = _compose("compose_minimal.yaml")
        assert 'id="filter-' not in html

    def test_mode_inferred_dimension(self):
        """mode: null on a dimension field → inferred as multi."""
        html = _compose("filter_null_default.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["mode"] == "multi"
        # dropdown defaults to True → compact native multi-select widget.
        assert attrs["control"] == "multi_dropdown"

    def test_mode_inferred_quantitative(self, tmp_path: Path):
        html = _compose_with_filter(
            tmp_path, field="revenue", model="orders", mode=None, default=None
        )
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["mode"] == "range"

    def test_mode_inferred_temporal(self, tmp_path: Path):
        html = _compose_with_filter(tmp_path, field="week", model="orders", mode=None, default=None)
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs["mode"] == "range"

    def test_multiple_filters_same_sheet(self, tmp_path: Path):
        """Two filters targeting the same sheet → both injected as transforms."""
        dashboard_yaml = (
            "dashboard: Multi Filter\n"
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - filter: region\n"
            "      model: orders\n"
            "      mode: single\n"
            "      default: EMEA\n"
            "    - filter: product\n"
            "      model: orders\n"
            "      mode: single\n"
            "      default: Widget\n"
            "    - sheet: revenue_by_region.yaml\n"
            "      name: chart_1\n"
        )
        dashboard_path = tmp_path / "dashboard.yaml"
        dashboard_path.write_text(dashboard_yaml)

        from shelves.compose.dashboard import compose_dashboard

        html = compose_dashboard(dashboard_path, chart_base_dir=YAML_DIR, models_dir=MODELS_DIR)
        transforms = _get_vl_transforms(html, "chart_1")
        filter_preds = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and t["filter"].get("equal") is not None
        ]
        fields = {f["field"] for f in filter_preds}
        assert "region" in fields
        assert "product" in fields

    def test_filter_and_parameter_coexist(self, tmp_path: Path):
        """Dashboard with both filter and parameter controls."""
        dashboard_yaml = (
            "dashboard: Mixed Controls\n"
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - filter: region\n"
            "      model: orders\n"
            "    - sheet: revenue_by_region.yaml\n"
            "      name: chart_1\n"
        )
        dashboard_path = tmp_path / "dashboard.yaml"
        dashboard_path.write_text(dashboard_yaml)

        from shelves.compose.dashboard import compose_dashboard

        html = compose_dashboard(dashboard_path, chart_base_dir=YAML_DIR, models_dir=MODELS_DIR)
        assert 'id="filter-' in html


# ─── Part 4: Error Cases ─────────────────────────────────────────────


class TestFilterInjectionErrors:
    def test_multi_mode_scalar_default_raises(self, tmp_path: Path):
        """mode: multi with a scalar default (not a list) → validation error."""
        with pytest.raises(ValueError, match="requires a list default"):
            _compose_with_filter(
                tmp_path, field="region", model="orders", mode="multi", default="scalar"
            )

    def test_range_mode_non_list_default_raises(self, tmp_path: Path):
        """mode: range with a non-list default → validation error."""
        with pytest.raises(ValueError, match="requires a list default"):
            _compose_with_filter(
                tmp_path, field="revenue", model="orders", mode="range", default="not-a-range"
            )


# ─── Part 5: Studio Surface Parity ───────────────────────────────────


FIXTURES_DIR = LAYOUT_DIR.parent


class TestStudioFilterInjection:
    """The Studio route must produce the same filter injection as compose."""

    def test_studio_dashboard_injects_filter(self):
        from shelves.studio.routes.dashboard import run_dashboard_pipeline

        dashboard_yaml = (
            "dashboard: Studio Filter Test\n"
            "canvas: { width: 800, height: 600 }\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            "    - filter: region\n"
            "      model: orders\n"
            "      mode: single\n"
            "      default: EMEA\n"
            "    - sheet: revenue_by_region.yaml\n"
            "      name: chart_1\n"
        )
        import asyncio

        result = asyncio.run(
            run_dashboard_pipeline(
                dashboard_yaml,
                project_dir=FIXTURES_DIR,
                charts_dir=YAML_DIR,
                theme_path=None,
                models_dir=MODELS_DIR,
            )
        )
        assert result["errors"] == [], result["errors"]
        html = result["html"]
        transforms = _get_vl_transforms(html, "chart_1")
        eq_filters = [
            t["filter"]
            for t in transforms
            if isinstance(t.get("filter"), dict) and t["filter"].get("equal") is not None
        ]
        assert any(f.get("field") == "region" and f.get("equal") == "EMEA" for f in eq_filters)


# ─── Test Helper: Compose With Inline Filter ─────────────────────────


def _compose_with_filter(
    tmp_path: Path,
    *,
    field: str,
    model: str,
    mode: str | None,
    default: object,
    targets: list[str] | str = "all",
    label: str | None = None,
    dropdown: bool | None = None,
) -> str:
    """Build a minimal dashboard YAML with one filter and compose it."""
    import yaml

    filter_def: dict = {"filter": field, "model": model}
    if mode is not None:
        filter_def["mode"] = mode
    if default is not None:
        filter_def["default"] = default
    if targets != "all":
        filter_def["targets"] = targets
    if label is not None:
        filter_def["label"] = label
    if dropdown is not None:
        filter_def["dropdown"] = dropdown

    dashboard = {
        "dashboard": "Inline Filter Test",
        "canvas": {"width": 800, "height": 600},
        "root": {
            "orientation": "vertical",
            "contains": [
                filter_def,
                {"sheet": "revenue_by_region.yaml", "name": "chart_1"},
                {"sheet": "simple_bar.yaml", "name": "chart_2"},
            ],
        },
    }

    dashboard_path = tmp_path / "dashboard.yaml"
    dashboard_path.write_text(yaml.dump(dashboard, default_flow_style=False))

    from shelves.compose.dashboard import compose_dashboard

    return compose_dashboard(
        dashboard_path, chart_base_dir=YAML_DIR, data_dir=DATA_DIR, models_dir=MODELS_DIR
    )


# ─── Part 5: Filter Overrides (_build_filter_injections) ──────────────


class TestFilterOverrides:
    """SHE-82: filter_overrides change the injected value at recompile time."""

    def test_override_replaces_default(self):
        """An override changes the injected filter value."""
        from shelves.compose.dashboard import _build_filter_injections
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode="single", default="EMEA")
        sheets = {"sheet-chart_1": "simple_bar.yaml"}
        sheet_models = {"sheet-chart_1": "orders"}
        overrides = {"orders.region": "APAC"}

        injections = _build_filter_injections(
            [filt], sheets, sheet_models, MODELS_DIR, filter_overrides=overrides
        )
        assert "sheet-chart_1" in injections
        assert injections["sheet-chart_1"][0]["value"] == "APAC"

    def test_override_null_skips_injection(self):
        """A null override means 'unfiltered' — no injection emitted."""
        from shelves.compose.dashboard import _build_filter_injections
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode="single", default="EMEA")
        sheets = {"sheet-chart_1": "simple_bar.yaml"}
        sheet_models = {"sheet-chart_1": "orders"}
        overrides = {"orders.region": None}

        injections = _build_filter_injections(
            [filt], sheets, sheet_models, MODELS_DIR, filter_overrides=overrides
        )
        assert injections.get("sheet-chart_1", []) == []

    def test_override_not_matching_uses_default(self):
        """Overrides for unrelated fields don't affect other filters."""
        from shelves.compose.dashboard import _build_filter_injections
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode="single", default="EMEA")
        sheets = {"sheet-chart_1": "simple_bar.yaml"}
        sheet_models = {"sheet-chart_1": "orders"}
        overrides = {"orders.product": "Widget"}

        injections = _build_filter_injections(
            [filt], sheets, sheet_models, MODELS_DIR, filter_overrides=overrides
        )
        assert injections["sheet-chart_1"][0]["value"] == "EMEA"

    def test_override_multi_mode_with_list(self):
        """Multi-mode override with a list value injects oneOf."""
        from shelves.compose.dashboard import _build_filter_injections
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode="multi", default=["US", "UK"])
        sheets = {"sheet-chart_1": "simple_bar.yaml"}
        sheet_models = {"sheet-chart_1": "orders"}
        overrides = {"orders.region": ["DE", "FR"]}

        injections = _build_filter_injections(
            [filt], sheets, sheet_models, MODELS_DIR, filter_overrides=overrides
        )
        assert injections["sheet-chart_1"][0]["values"] == ["DE", "FR"]

    def test_no_overrides_param_uses_default(self):
        """When filter_overrides is None, behaviour is unchanged."""
        from shelves.compose.dashboard import _build_filter_injections
        from shelves.schema.layout_schema import FilterComponent

        filt = FilterComponent(field="region", model="orders", mode="single", default="EMEA")
        sheets = {"sheet-chart_1": "simple_bar.yaml"}
        sheet_models = {"sheet-chart_1": "orders"}

        injections = _build_filter_injections(
            [filt], sheets, sheet_models, MODELS_DIR, filter_overrides=None
        )
        assert injections["sheet-chart_1"][0]["value"] == "EMEA"


class TestFilterOverrideHeaderParsing:
    """SHE-82: the Studio route parses X-Shelves-Filters header."""

    def test_parse_valid_header(self):
        from shelves.studio.routes.dashboard import _parse_filter_header

        result = _parse_filter_header('{"orders.region": "APAC"}')
        assert result == {"orders.region": "APAC"}

    def test_parse_null_value_in_header(self):
        from shelves.studio.routes.dashboard import _parse_filter_header

        result = _parse_filter_header('{"orders.region": null}')
        assert result == {"orders.region": None}

    def test_parse_malformed_header_returns_none(self):
        from shelves.studio.routes.dashboard import _parse_filter_header

        result = _parse_filter_header("not json at all")
        assert result is None

    def test_parse_non_object_header_returns_none(self):
        from shelves.studio.routes.dashboard import _parse_filter_header

        result = _parse_filter_header("[1, 2, 3]")
        assert result is None
