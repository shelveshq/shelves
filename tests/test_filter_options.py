"""
Filter options resolution tests — SHE-81.

Part 1: Happy path — dimension, quantitative, temporal, wildcard.
Part 2: Adapter parity — inline vs DuckDB yield identical options.
Part 3: Cardinality guard — truncate at 500, warning emitted.
Part 4: Default validation against resolved options.
Part 5: Edge cases — inferred mode, measure bounds, multiple filters.
Part 6: Error cases — bad default, no source.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
import yaml

from shelves.data.domains import MAX_DOMAIN_CARDINALITY, clear_domain_cache
from tests.conftest import FIXTURES_DIR, LAYOUT_DIR, MODELS_DIR, YAML_DIR


def _compose(fixture_name: str, **kwargs) -> str:
    from shelves.compose.dashboard import compose_dashboard

    clear_domain_cache()
    return compose_dashboard(
        dashboard_path=LAYOUT_DIR / fixture_name,
        chart_base_dir=YAML_DIR,
        data_dir=FIXTURES_DIR,
        models_dir=kwargs.pop("models_dir", MODELS_DIR),
        **kwargs,
    )


def _parse_filter_div(html_str: str, dom_id: str) -> dict[str, str]:
    from html.parser import HTMLParser

    class _AttrParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.attrs: dict[str, str] = {}
            self.found = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
            if self.found:
                return
            for k, v in attrs:
                if k == "id" and v == f"filter-{dom_id}":
                    self.found = True
                    break
            if self.found:
                for k, v in attrs:
                    if k.startswith("data-") and v is not None:
                        self.attrs[k[5:]] = v

    parser = _AttrParser()
    parser.feed(html_str)
    return parser.attrs


def _write_inline_model(
    tmp_path: Path,
    name: str,
    dimensions: dict,
    rows: list[dict],
    *,
    measures: dict | None = None,
    data_name: str = "gen_data.json",
) -> None:
    model_def: dict = {
        "model": name,
        "label": name,
        "source": {"type": "inline", "path": data_name},
        "dimensions": dimensions,
        "measures": measures or {"m": {"label": "M"}},
    }
    (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(model_def))
    (tmp_path / data_name).write_text(json.dumps(rows))


def _write_file_model(
    tmp_path: Path,
    name: str,
    dimensions: dict,
    csv_text: str,
    *,
    measures: dict | None = None,
    data_name: str = "gen_data.csv",
) -> None:
    model_def: dict = {
        "model": name,
        "label": name,
        "source": {"type": "file", "path": data_name},
        "dimensions": dimensions,
        "measures": measures or {"m": {"label": "M", "column": "m", "aggregation": "sum"}},
    }
    (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(model_def))
    (tmp_path / data_name).write_text(csv_text)


def _write_chart(tmp_path: Path, name: str, model: str, *, dim: str = "id") -> None:
    (tmp_path / name).write_text(
        yaml.safe_dump(
            {
                "sheet": "Test",
                "data": model,
                "cols": dim,
                "rows": "m",
                "marks": "bar",
            }
        )
    )


def _write_dashboard(tmp_path: Path, name: str, content: dict) -> None:
    (tmp_path / name).write_text(yaml.safe_dump(content))


# ─── Part 1: Happy Path ─────────────────────────────────────────────


class TestDimensionFilterOptions:
    def test_multi_mode_resolves_sorted_distinct_values(self):
        html = _compose("compose_filter_options.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs.get("options") is not None
        options = json.loads(attrs["options"])
        values = [o["value"] for o in options]
        assert values == ["DE", "FR", "JP", "UK", "US"]
        for o in options:
            assert o["value"] == o["label"]

    def test_single_mode_resolves_distinct_values(self):
        html = _compose("compose_filter_options.yaml")
        attrs = _parse_filter_div(html, "auto-2")
        options = json.loads(attrs["options"])
        values = [o["value"] for o in options]
        assert "APAC" in values
        assert "EMEA" in values
        assert "NA" in values


class TestQuantitativeFilterOptions:
    def test_range_mode_resolves_min_max_bounds(self):
        html = _compose("compose_filter_options_quant.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        options = json.loads(attrs["options"])
        assert isinstance(options, list)
        assert len(options) == 2
        assert options[0] <= options[1]


class TestTemporalFilterOptions:
    def test_range_mode_resolves_date_bounds(self):
        html = _compose("compose_filter_options_temporal.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        options = json.loads(attrs["options"])
        assert isinstance(options, list)
        assert len(options) == 2
        assert isinstance(options[0], str)
        assert isinstance(options[1], str)


class TestWildcardFilterOptions:
    def test_wildcard_mode_options_null(self):
        html = _compose("compose_filter_options_wildcard.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs.get("options") == "null"


# ─── Part 2: Adapter Parity ─────────────────────────────────────────


class TestAdapterParity:
    def test_inline_and_duckdb_yield_identical_dimension_options(self, tmp_path: Path):
        rows = [{"id": "b"}, {"id": "a"}, {"id": "c"}, {"id": "b"}]
        _write_inline_model(tmp_path, "gen", {"id": {"label": "Id"}}, rows)
        _write_chart(tmp_path, "chart.yaml", "gen")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "Parity",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "id", "model": "gen", "mode": "multi", "height": 48},
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        html_inline = compose_dashboard(
            dashboard_path=tmp_path / "dash.yaml",
            chart_base_dir=tmp_path,
            data_dir=tmp_path,
            models_dir=tmp_path,
        )
        inline_attrs = _parse_filter_div(html_inline, "auto-1")
        inline_options = json.loads(inline_attrs["options"])

        _write_file_model(
            tmp_path,
            "genf",
            {"id": {"column": "id", "label": "Id"}},
            "id,m\na,1\nb,2\nc,3\nb,4\n",
        )
        _write_chart(tmp_path, "chartf.yaml", "genf")
        _write_dashboard(
            tmp_path,
            "dashf.yaml",
            {
                "dashboard": "Parity File",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "id", "model": "genf", "mode": "multi", "height": 48},
                        {"sheet": "chartf.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        html_duckdb = compose_dashboard(
            dashboard_path=tmp_path / "dashf.yaml",
            chart_base_dir=tmp_path,
            data_dir=tmp_path,
            models_dir=tmp_path,
        )
        duckdb_attrs = _parse_filter_div(html_duckdb, "auto-1")
        duckdb_options = json.loads(duckdb_attrs["options"])

        assert inline_options == duckdb_options
        assert [o["value"] for o in inline_options] == ["a", "b", "c"]


# ─── Part 3: Cardinality Guard ──────────────────────────────────────


class TestCardinalityGuard:
    def test_501_values_truncates_with_warning(self, tmp_path: Path):
        rows = [{"id": f"v{i:04d}"} for i in range(MAX_DOMAIN_CARDINALITY + 1)]
        _write_inline_model(tmp_path, "gen", {"id": {"label": "Id"}}, rows)
        _write_chart(tmp_path, "chart.yaml", "gen")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "Cardinality",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "id", "model": "gen", "mode": "multi", "height": 48},
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            html = compose_dashboard(
                dashboard_path=tmp_path / "dash.yaml",
                chart_base_dir=tmp_path,
                data_dir=tmp_path,
                models_dir=tmp_path,
            )

        cardinality_warnings = [x for x in w if "distinct values" in str(x.message)]
        assert len(cardinality_warnings) >= 1
        assert "501" in str(cardinality_warnings[0].message)

        attrs = _parse_filter_div(html, "auto-1")
        options = json.loads(attrs["options"])
        assert len(options) == MAX_DOMAIN_CARDINALITY
        assert attrs["mode"] == "multi"

    def test_500_values_no_warning(self, tmp_path: Path):
        rows = [{"id": f"v{i:04d}"} for i in range(MAX_DOMAIN_CARDINALITY)]
        _write_inline_model(tmp_path, "gen", {"id": {"label": "Id"}}, rows)
        _write_chart(tmp_path, "chart.yaml", "gen")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "NoWarn",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "id", "model": "gen", "mode": "multi", "height": 48},
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            html = compose_dashboard(
                dashboard_path=tmp_path / "dash.yaml",
                chart_base_dir=tmp_path,
                data_dir=tmp_path,
                models_dir=tmp_path,
            )

        cardinality_warnings = [x for x in w if "distinct values" in str(x.message)]
        assert len(cardinality_warnings) == 0

        attrs = _parse_filter_div(html, "auto-1")
        options = json.loads(attrs["options"])
        assert len(options) == MAX_DOMAIN_CARDINALITY

    def test_501_values_duckdb_truncates_with_warning(self, tmp_path: Path):
        csv_rows = "\n".join(f"v{i:04d},1" for i in range(MAX_DOMAIN_CARDINALITY + 1))
        _write_file_model(
            tmp_path,
            "genf",
            {"id": {"column": "id", "label": "Id"}},
            f"id,m\n{csv_rows}\n",
        )
        _write_chart(tmp_path, "chart.yaml", "genf")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "Cardinality DuckDB",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "id", "model": "genf", "mode": "multi", "height": 48},
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            html = compose_dashboard(
                dashboard_path=tmp_path / "dash.yaml",
                chart_base_dir=tmp_path,
                data_dir=tmp_path,
                models_dir=tmp_path,
            )

        cardinality_warnings = [x for x in w if "distinct values" in str(x.message)]
        assert len(cardinality_warnings) >= 1

        attrs = _parse_filter_div(html, "auto-1")
        options = json.loads(attrs["options"])
        assert len(options) == MAX_DOMAIN_CARDINALITY


# ─── Part 4: Default Validation ─────────────────────────────────────


class TestDefaultValidation:
    def test_default_not_in_resolved_values_raises(self, tmp_path: Path):
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        _write_inline_model(tmp_path, "gen", {"id": {"label": "Id"}}, rows)
        _write_chart(tmp_path, "chart.yaml", "gen")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "Bad Default",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {
                            "filter": "id",
                            "model": "gen",
                            "mode": "single",
                            "default": "ZZ",
                            "height": 48,
                        },
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        with pytest.raises(ValueError, match="ZZ"):
            compose_dashboard(
                dashboard_path=tmp_path / "dash.yaml",
                chart_base_dir=tmp_path,
                data_dir=tmp_path,
                models_dir=tmp_path,
            )

    def test_range_default_outside_bounds_raises(self, tmp_path: Path):
        rows = [{"cat": "a", "val": 10}, {"cat": "b", "val": 100}]
        _write_inline_model(
            tmp_path,
            "gen",
            {"cat": {"label": "Cat"}},
            rows,
            measures={"val": {"label": "Val"}, "m": {"label": "M"}},
        )
        _write_chart(tmp_path, "chart.yaml", "gen", dim="cat")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "Bad Range Default",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {
                            "filter": "val",
                            "model": "gen",
                            "mode": "range",
                            "default": [10, 200],
                            "height": 48,
                        },
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        with pytest.raises(ValueError, match="outside"):
            compose_dashboard(
                dashboard_path=tmp_path / "dash.yaml",
                chart_base_dir=tmp_path,
                data_dir=tmp_path,
                models_dir=tmp_path,
            )

    def test_null_default_skips_validation(self):
        html = _compose("compose_filter_options.yaml")
        attrs = _parse_filter_div(html, "auto-1")
        assert attrs.get("options") is not None


# ─── Part 5: Edge Cases ─────────────────────────────────────────────


class TestEdgeCases:
    def test_inferred_mode_resolves_options(self, tmp_path: Path):
        """mode omitted on dimension → inferred multi → options resolved."""
        rows = [{"id": "x"}, {"id": "y"}]
        _write_inline_model(tmp_path, "gen", {"id": {"label": "Id"}}, rows)
        _write_chart(tmp_path, "chart.yaml", "gen")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "Inferred",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "id", "model": "gen", "height": 48},
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        html = compose_dashboard(
            dashboard_path=tmp_path / "dash.yaml",
            chart_base_dir=tmp_path,
            data_dir=tmp_path,
            models_dir=tmp_path,
        )
        attrs = _parse_filter_div(html, "auto-1")
        options = json.loads(attrs["options"])
        assert [o["value"] for o in options] == ["x", "y"]

    def test_measure_filter_resolves_bounds(self, tmp_path: Path):
        rows = [{"cat": "a", "val": 10}, {"cat": "b", "val": 50}, {"cat": "c", "val": 100}]
        _write_inline_model(
            tmp_path,
            "gen",
            {"cat": {"label": "Cat"}},
            rows,
            measures={"val": {"label": "Val"}, "m": {"label": "M"}},
        )
        _write_chart(tmp_path, "chart.yaml", "gen", dim="cat")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "Measure Bounds",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "val", "model": "gen", "mode": "range", "height": 48},
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        html = compose_dashboard(
            dashboard_path=tmp_path / "dash.yaml",
            chart_base_dir=tmp_path,
            data_dir=tmp_path,
            models_dir=tmp_path,
        )
        attrs = _parse_filter_div(html, "auto-1")
        options = json.loads(attrs["options"])
        assert options == [10, 100]

    def test_multiple_filters_resolve_independently(self):
        html = _compose("compose_filter_options.yaml")
        country_attrs = _parse_filter_div(html, "auto-1")
        region_attrs = _parse_filter_div(html, "auto-2")
        country_options = json.loads(country_attrs["options"])
        region_options = json.loads(region_attrs["options"])
        assert [o["value"] for o in country_options] == ["DE", "FR", "JP", "UK", "US"]
        assert sorted([o["value"] for o in region_options]) == ["APAC", "EMEA", "NA"]


# ─── Part 6: Error Cases ────────────────────────────────────────────


class TestErrorCases:
    def test_no_source_warns_and_options_null(self, tmp_path: Path):
        (tmp_path / "nosrc.yaml").write_text(
            yaml.safe_dump(
                {
                    "model": "nosrc",
                    "label": "No Source",
                    "dimensions": {"id": {"label": "Id"}},
                    "measures": {"m": {"label": "M"}},
                }
            )
        )
        _write_chart(tmp_path, "chart.yaml", "nosrc")
        _write_dashboard(
            tmp_path,
            "dash.yaml",
            {
                "dashboard": "No Source",
                "canvas": {"width": 800, "height": 600},
                "root": {
                    "orientation": "vertical",
                    "contains": [
                        {"filter": "id", "model": "nosrc", "mode": "multi", "height": 48},
                        {"sheet": "chart.yaml", "name": "s1"},
                    ],
                },
            },
        )
        clear_domain_cache()
        from shelves.compose.dashboard import compose_dashboard

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            html = compose_dashboard(
                dashboard_path=tmp_path / "dash.yaml",
                chart_base_dir=tmp_path,
                data_dir=tmp_path,
                models_dir=tmp_path,
            )

        option_warnings = [x for x in w if "could not be resolved" in str(x.message)]
        assert len(option_warnings) >= 1
        assert "source" in str(option_warnings[0].message)

        attrs = _parse_filter_div(html, "auto-1")
        assert attrs.get("options") == "null"


# ─── Part 7: Parameter domain cardinality parity ────────────────────


class TestParameterCardinalityParity:
    """Ensure parameter domains also truncate + warn (SHE-102 parity)."""

    def test_parameter_501_values_truncates_with_warning(self, tmp_path: Path):
        from shelves.data.domains import resolve_parameter_domains
        from shelves.params.loader import load_parameters

        rows = [{"id": f"v{i:04d}"} for i in range(MAX_DOMAIN_CARDINALITY + 1)]
        _write_inline_model(tmp_path, "gen", {"id": {"label": "Id"}}, rows)
        (tmp_path / "parameters.yaml").write_text(
            yaml.safe_dump(
                {
                    "parameters": {
                        "big": {
                            "type": "string",
                            "values": [{"model": "gen", "field": "id"}],
                            "default": None,
                        }
                    }
                }
            )
        )
        params = load_parameters(tmp_path / "parameters.yaml")
        clear_domain_cache()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            domains = resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)

        assert len(domains["big"].values or []) == MAX_DOMAIN_CARDINALITY
        cardinality_warnings = [x for x in w if "distinct values" in str(x.message)]
        assert len(cardinality_warnings) >= 1
