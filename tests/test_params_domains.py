"""Parameter domain resolution tests (SHE-90)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx
import yaml

from shelves.data.domains import (
    DOMAIN_CACHE_TTL,
    MAX_DOMAIN_CARDINALITY,
    Domain,
    _inline_domain,
    _normalize,
    _to_date,
    _truncate,
    check_value_in_domain,
    clear_domain_cache,
    resolve_field_domain,
    resolve_parameter_domains,
)
from shelves.data.errors import ParameterDomainError
from shelves.models.loader import clear_model_cache
from shelves.params.loader import load_parameters
from shelves.params.schema import FieldRef
from tests.conftest import FIXTURES_DIR, MODELS_DIR, params_fixture

CUBE_URL = "http://localhost:4000"
LOAD_URL = f"{CUBE_URL}/cubejs-api/v1/load"


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_model_cache()
    clear_domain_cache()
    yield
    clear_model_cache()
    clear_domain_cache()


@pytest.fixture
def cube_env(monkeypatch):
    monkeypatch.setenv("CUBE_API_URL", CUBE_URL)
    monkeypatch.setenv("CUBE_API_TOKEN", "test-token")


def _write_params(tmp_path: Path, text: str):
    path = tmp_path / "parameters.yaml"
    path.write_text(text)
    return load_parameters(path)


def _write_inline_model(
    tmp_path: Path,
    name: str,
    dimensions: dict,
    rows: list[dict] | None,
    *,
    data_name: str = "gen_data.json",
) -> None:
    (tmp_path / f"{name}.yaml").write_text(
        yaml.safe_dump(
            {
                "model": name,
                "label": name,
                "source": {"type": "inline", "path": data_name},
                "dimensions": dimensions,
                "measures": {"m": {"label": "M"}},
            }
        )
    )
    if rows is not None:
        (tmp_path / data_name).write_text(json.dumps(rows))


def _write_file_model(
    tmp_path: Path,
    name: str,
    dimensions: dict,
    csv_text: str,
    *,
    data_name: str = "gen_data.csv",
) -> None:
    (tmp_path / f"{name}.yaml").write_text(
        yaml.safe_dump(
            {
                "model": name,
                "label": name,
                "source": {"type": "file", "path": data_name},
                "dimensions": dimensions,
                "measures": {"m": {"label": "M", "column": "m", "aggregation": "sum"}},
            }
        )
    )
    (tmp_path / data_name).write_text(csv_text)


PARITY_PARAMS = """
parameters:
  region:
    type: string
    values:
      - model: {model}
        field: region
    default: EMEA

  as_of:
    type: date
    values:
      - model: {model}
        field: order_date.month
    default: 2024-02-01

  fy:
    type: number
    values:
      - model: {model}
        field: fiscal_year
    default: 2024
"""


def _parity_params(tmp_path: Path, model: str):
    return _write_params(tmp_path, PARITY_PARAMS.format(model=model))


def _cube_parity_responses() -> list[httpx.Response]:
    return [
        httpx.Response(
            200,
            json={
                "data": [
                    {"orders.region": "NA"},
                    {"orders.region": "EMEA"},
                    {"orders.region": "APAC"},
                ]
            },
        ),
        httpx.Response(
            200, json={"data": [{"orders.order_date.month": "2024-01-01T00:00:00.000"}]}
        ),
        httpx.Response(
            200, json={"data": [{"orders.order_date.month": "2024-03-01T00:00:00.000"}]}
        ),
        httpx.Response(200, json={"data": [{"orders.fiscal_year": 2023}]}),
        httpx.Response(200, json={"data": [{"orders.fiscal_year": 2024}]}),
    ]


def _stripped(domains: dict[str, Domain]) -> dict[str, Domain]:
    """Drop the per-backend display `source` so results can be compared."""
    return {name: dataclasses.replace(d, source="") for name, d in domains.items()}


EXPECTED = {
    "region": Domain(
        kind="values",
        param_type="string",
        source="",
        values=["APAC", "EMEA", "NA"],
    ),
    "as_of": Domain(
        kind="bounds",
        param_type="date",
        source="",
        min="2024-01-01",
        max="2024-03-01",
    ),
    "fy": Domain(
        kind="bounds",
        param_type="number",
        source="",
        min=2023,
        max=2024,
    ),
}


class TestToDate:
    @pytest.mark.parametrize(
        "raw",
        [
            dt.datetime(2024, 1, 1, 0, 0),
            dt.datetime(2024, 1, 1, 13, 45, 30),
            dt.date(2024, 1, 1),
            "2024-01-01",
            "2024-01-01T00:00:00.000",
            "2024-01-01T00:00:00",
            "2024-01",
            "2024",
        ],
    )
    def test_every_backend_shape(self, raw):
        assert _to_date(raw) == dt.date(2024, 1, 1)

    def test_datetime_checked_before_date(self):
        # datetime is a subclass of date — the time component must be dropped.
        assert _to_date(dt.datetime(2024, 3, 5, 23, 59)) == dt.date(2024, 3, 5)

    def test_unparseable_raises(self):
        with pytest.raises(ValueError):
            _to_date("not-a-date")


class TestTruncate:
    def test_none_and_day_are_identity(self):
        assert _truncate("2024-03-07", None) == dt.date(2024, 3, 7)
        assert _truncate("2024-03-07", "day") == dt.date(2024, 3, 7)

    def test_week_starts_monday(self):
        # 2024-03-07 is a Thursday; DuckDB and Cube both start weeks on Monday.
        assert _truncate("2024-03-07", "week") == dt.date(2024, 3, 4)

    def test_month(self):
        assert _truncate("2024-03-07", "month") == dt.date(2024, 3, 1)

    def test_quarter(self):
        assert _truncate("2024-05-20", "quarter") == dt.date(2024, 4, 1)
        assert _truncate("2024-01-31", "quarter") == dt.date(2024, 1, 1)
        assert _truncate("2024-12-31", "quarter") == dt.date(2024, 10, 1)

    def test_year(self):
        assert _truncate("2024-05-20", "year") == dt.date(2024, 1, 1)

    def test_unknown_grain_raises(self):
        with pytest.raises(ParameterDomainError, match="fortnight"):
            _truncate("2024-05-20", "fortnight")


class TestNormalize:
    @pytest.mark.parametrize(
        "raw",
        [
            "2024-01-01T00:00:00.000",
            dt.date(2024, 1, 1),
            dt.datetime(2024, 1, 1, 0, 0),
            "2024-01-01T00:00:00",
            "2024-01",
            "2024",
        ],
    )
    def test_temporal_shapes_converge_on_iso(self, raw):
        assert _normalize(raw, "date", True) == "2024-01-01"

    def test_temporal_string_parameter_is_iso_too(self):
        assert _normalize("2024-01-15", "string", True) == "2024-01-15"

    def test_integer_valued_number_stays_int(self):
        assert _normalize(2023, "number", False) == 2023
        assert _normalize(2023.0, "number", False) == 2023
        assert isinstance(_normalize(2023.0, "number", False), int)

    def test_float_stays_float(self):
        assert _normalize(1.5, "number", False) == 1.5

    def test_numeric_string_from_cube_is_coerced(self):
        assert _normalize("2023", "number", False) == 2023

    def test_bool_in_number_domain_raises(self):
        with pytest.raises(ParameterDomainError, match="boolean"):
            _normalize(True, "number", False)

    def test_non_numeric_in_number_domain_raises(self):
        with pytest.raises(ParameterDomainError, match="not a number"):
            _normalize("EMEA", "number", False)

    def test_temporal_field_on_number_parameter_raises(self):
        with pytest.raises(ParameterDomainError):
            _normalize("2024-01-01", "number", True)

    def test_string_passthrough(self):
        assert _normalize("EMEA", "string", False) == "EMEA"

    def test_non_string_stringified(self):
        assert _normalize(7, "string", False) == "7"


class TestAdapterParity:
    def _inline(self, tmp_path):
        return resolve_parameter_domains(
            _parity_params(tmp_path, "parity_inline"),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )

    def _file(self, tmp_path):
        return resolve_parameter_domains(
            _parity_params(tmp_path, "parity_file"),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )

    def _cube(self, tmp_path):
        return resolve_parameter_domains(
            _parity_params(tmp_path, "parity_cube"),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )

    def test_inline_domains(self, tmp_path):
        assert _stripped(self._inline(tmp_path)) == EXPECTED

    def test_duckdb_domains(self, tmp_path):
        assert _stripped(self._file(tmp_path)) == EXPECTED

    @respx.mock
    def test_cube_domains(self, tmp_path, cube_env):
        respx.post(LOAD_URL).mock(side_effect=_cube_parity_responses())
        assert _stripped(self._cube(tmp_path)) == EXPECTED

    @respx.mock
    def test_same_domains_on_all_backends(self, tmp_path, cube_env):
        respx.post(LOAD_URL).mock(side_effect=_cube_parity_responses())
        inline_domains = _stripped(self._inline(tmp_path))
        file_domains = _stripped(self._file(tmp_path))
        cube_domains = _stripped(self._cube(tmp_path))
        assert inline_domains == file_domains == cube_domains

    def test_source_is_a_display_string(self, tmp_path):
        domains = self._inline(tmp_path)
        assert domains["region"].source == "parity_inline.region"
        assert domains["as_of"].source == "parity_inline.order_date.month"


class TestGrainSuffix:
    def test_grain_suffix_resolves_months(self):
        """`week.month` reaches ModelResolver whole — two weeks collapse to one month."""
        domains = resolve_parameter_domains(
            load_parameters(params_fixture()),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )
        assert domains["week_grain"].values == ["2024-01-01"]

    def test_grain_suffix_on_duckdb(self, tmp_path):
        """DATE_TRUNC lands in the SELECT DISTINCT, not only in bounds."""
        params = _write_params(
            tmp_path,
            """
parameters:
  months:
    type: string
    values:
      - model: parity_file
        field: order_date.month
    default: null
""",
        )
        domains = resolve_parameter_domains(
            params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
        )
        assert domains["months"].values == ["2024-01-01", "2024-02-01", "2024-03-01"]


class TestResolveAll:
    def test_fixture_parameters_resolve(self):
        domains = resolve_parameter_domains(
            load_parameters(params_fixture()),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )
        assert set(domains) == {"region", "maybe_region", "week_grain"}
        assert domains["region"].values == ["APAC", "EMEA", "NA"]
        assert domains["maybe_region"].values == ["APAC", "EMEA", "NA"]


class TestNoDataAccess:
    @respx.mock
    def test_literal_values_never_query(self, tmp_path, cube_env):
        route = respx.post(LOAD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        params = _write_params(
            tmp_path,
            """
parameters:
  status:
    type: string
    values:
      - open
      - closed
      - pending
    default: open
""",
        )
        domains = resolve_parameter_domains(
            params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
        )
        assert domains == {}
        assert route.call_count == 0

    @respx.mock
    def test_range_values_never_query(self, tmp_path, cube_env):
        route = respx.post(LOAD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        params = _write_params(
            tmp_path,
            """
parameters:
  top_n:
    type: number
    values:
      - min: 5
        max: 50
    default: 10
""",
        )
        assert (
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
            == {}
        )
        assert route.call_count == 0

    @respx.mock
    def test_field_type_never_queries(self, tmp_path, cube_env):
        route = respx.post(LOAD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        params = _write_params(
            tmp_path,
            """
parameters:
  metric:
    type: field
    values:
      - model: parity_cube
        field: revenue
      - model: parity_cube
        field: region
    default: revenue
""",
        )
        assert (
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
            == {}
        )
        assert route.call_count == 0

    @respx.mock
    def test_omitted_values_never_query(self, tmp_path, cube_env):
        route = respx.post(LOAD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        params = _write_params(
            tmp_path,
            """
parameters:
  free:
    type: string
    default: EMEA
""",
        )
        assert (
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
            == {}
        )
        assert route.call_count == 0

    @respx.mock
    def test_same_field_queried_once(self, tmp_path, cube_env):
        """Two parameters over one field share a single query (the within-call memo)."""
        route = respx.post(LOAD_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"orders.region": "EMEA"}]})
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  a:
    type: string
    values:
      - model: parity_cube
        field: region
    default: EMEA
  b:
    type: string
    values:
      - model: parity_cube
        field: region
    default: null
""",
        )
        domains = resolve_parameter_domains(
            params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
        )
        assert domains["a"].values == ["EMEA"]
        assert domains["b"].values == ["EMEA"]
        assert route.call_count == 1


class TestDomainEdgeCases:
    def test_null_default_is_skipped_not_compared(self, tmp_path):
        """A domain is still resolved (SHE-92 renders a control) but not checked."""
        params = _write_params(
            tmp_path,
            """
parameters:
  maybe:
    type: string
    values:
      - model: parity_inline
        field: region
    default: null
""",
        )
        domains = resolve_parameter_domains(
            params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
        )
        assert domains["maybe"].values == ["APAC", "EMEA", "NA"]

    def test_nulls_dropped_from_a_values_domain(self, tmp_path):
        _write_inline_model(
            tmp_path,
            "gen",
            {"region": {"label": "Region"}},
            [{"region": "EMEA"}, {"region": None}, {"region": "APAC"}],
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  p:
    type: string
    values:
      - model: gen
        field: region
    default: null
""",
        )
        domains = resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        assert domains["p"].values == ["APAC", "EMEA"]

    def test_nulls_ignored_in_a_bounds_domain(self, tmp_path):
        _write_inline_model(
            tmp_path,
            "gen",
            {
                "order_date": {
                    "type": "temporal",
                    "label": "Order Date",
                    "defaultGrain": "day",
                }
            },
            [{"order_date": "2024-01-10"}, {"order_date": None}, {"order_date": "2024-03-05"}],
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  p:
    type: date
    values:
      - model: gen
        field: order_date
    default: null
""",
        )
        domains = resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        assert (domains["p"].min, domains["p"].max) == ("2024-01-10", "2024-03-05")

    def test_duplicates_deduped_on_inline(self, tmp_path):
        """Inline rows are raw JSON — the dedupe happens in domains.py, not a SELECT DISTINCT."""
        domains = resolve_parameter_domains(
            _parity_params(tmp_path, "parity_inline"),
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
        )
        # Five rows, three regions.
        assert domains["region"].values == ["APAC", "EMEA", "NA"]

    @respx.mock
    def test_unsorted_backend_result_is_sorted(self, tmp_path, cube_env):
        respx.post(LOAD_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"orders.region": "NA"},
                        {"orders.region": "EMEA"},
                        {"orders.region": "APAC"},
                    ]
                },
            )
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  p:
    type: string
    values:
      - model: parity_cube
        field: region
    default: null
""",
        )
        domains = resolve_parameter_domains(
            params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
        )
        assert domains["p"].values == ["APAC", "EMEA", "NA"]

    @respx.mock
    def test_numeric_looking_string_from_cube_coerced(self, tmp_path, cube_env):
        respx.post(LOAD_URL).mock(
            side_effect=[
                httpx.Response(200, json={"data": [{"orders.fiscal_year": "2023"}]}),
                httpx.Response(200, json={"data": [{"orders.fiscal_year": "2024"}]}),
            ]
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  fy:
    type: number
    values:
      - model: parity_cube
        field: fiscal_year
    default: null
""",
        )
        domains = resolve_parameter_domains(
            params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
        )
        assert (domains["fy"].min, domains["fy"].max) == (2023, 2024)
        assert isinstance(domains["fy"].min, int)

    def test_exactly_500_distinct_values_passes(self, tmp_path):
        _write_inline_model(
            tmp_path,
            "gen",
            {"id": {"label": "Id"}},
            [{"id": f"v{i:04d}"} for i in range(MAX_DOMAIN_CARDINALITY)],
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  big:
    type: string
    values:
      - model: gen
        field: id
    default: null
""",
        )
        domains = resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        assert len(domains["big"].values or []) == MAX_DOMAIN_CARDINALITY

    def test_501_distinct_values_raises_on_inline(self, tmp_path):
        _write_inline_model(
            tmp_path,
            "gen",
            {"id": {"label": "Id"}},
            [{"id": f"v{i:04d}"} for i in range(MAX_DOMAIN_CARDINALITY + 1)],
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  big:
    type: string
    values:
      - model: gen
        field: id
    default: null
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        assert "parameters.big:" in str(exc.value)
        assert "501 or more distinct values" in str(exc.value)

    def test_501_distinct_values_raises_on_duckdb(self, tmp_path):
        """The DuckDB LIMIT must be 501, not 500 — off-by-one silently accepts 501."""
        rows = "\n".join(f"v{i:04d},1" for i in range(MAX_DOMAIN_CARDINALITY + 1))
        _write_file_model(
            tmp_path,
            "genf",
            {"id": {"column": "id", "label": "Id"}},
            f"id,m\n{rows}\n",
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  big:
    type: string
    values:
      - model: genf
        field: id
    default: null
""",
        )
        with pytest.raises(ParameterDomainError, match="501 or more distinct values"):
            resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)

    def test_500_distinct_values_passes_on_duckdb(self, tmp_path):
        rows = "\n".join(f"v{i:04d},1" for i in range(MAX_DOMAIN_CARDINALITY))
        _write_file_model(
            tmp_path,
            "genf",
            {"id": {"column": "id", "label": "Id"}},
            f"id,m\n{rows}\n",
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  big:
    type: string
    values:
      - model: genf
        field: id
    default: null
""",
        )
        domains = resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        assert len(domains["big"].values or []) == MAX_DOMAIN_CARDINALITY


class TestDomainErrors:
    # D-E1
    def test_default_not_in_values_domain(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: parity_inline
        field: region
    default: LATAM
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert str(exc.value) == (
            "parameters.region: default 'LATAM' is not in the domain of "
            "'parity_inline.region'. Valid values: APAC, EMEA, NA (3 total)."
        )

    # D-E1, truncated form
    def test_default_error_truncates_long_domains(self, tmp_path):
        _write_inline_model(
            tmp_path,
            "gen",
            {"id": {"label": "Id"}},
            [{"id": f"v{i:04d}"} for i in range(23)],
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  p:
    type: string
    values:
      - model: gen
        field: id
    default: nope
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        message = str(exc.value)
        assert "Valid values include: " in message
        assert "(23 total)." in message
        assert "v0009" in message
        assert "v0010" not in message

    # D-E2
    def test_default_outside_bounds(self, tmp_path):
        """A YAML date default arrives as dt.date and must be normalized before comparison."""
        params = _write_params(
            tmp_path,
            """
parameters:
  as_of:
    type: date
    values:
      - model: parity_inline
        field: order_date.month
    default: 2023-06-01
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        message = str(exc.value)
        assert message.startswith("parameters.as_of: default 2023-06-01 is outside the domain of ")
        assert "'parity_inline.order_date.month'" in message
        assert "(min: 2024-01-01, max: 2024-03-01)." in message

    # D-E4
    def test_measure_as_domain_source_inline(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  top_n:
    type: number
    values:
      - model: parity_inline
        field: revenue
    default: 100
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert str(exc.value) == (
            "parameters.top_n: 'revenue' is a measure. A parameter domain can only "
            "be sourced from a dimension — a measure's range depends on how a chart "
            "aggregates it, and the three data backends do not agree on what that "
            "means. Use an explicit min/max range, or point at a dimension."
        )

    def test_measure_as_domain_source_duckdb(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  top_n:
    type: number
    values:
      - model: parity_file
        field: revenue
    default: 100
""",
        )
        with pytest.raises(ParameterDomainError, match="is a measure"):
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)

    @respx.mock
    def test_measure_as_domain_source_cube_makes_no_call(self, tmp_path, cube_env):
        """The rejection happens in domains.py, before any adapter is touched."""
        route = respx.post(LOAD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        params = _write_params(
            tmp_path,
            """
parameters:
  top_n:
    type: number
    values:
      - model: parity_cube
        field: revenue
    default: 100
""",
        )
        with pytest.raises(ParameterDomainError, match="is a measure"):
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert route.call_count == 0

    # D-E5
    def test_field_not_in_model(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: parity_inline
        field: regionn
    default: EMEA
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        message = str(exc.value)
        assert message.startswith("parameters.region: ")
        assert 'Field "regionn" not found in model "parity_inline"' in message
        # the resolver's correction text survives
        assert "Available: measures=['revenue']" in message

    # D-E6
    def test_grain_not_supported(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  p:
    type: string
    values:
      - model: temporal_explicit_grains
        field: year_field.day
    default: null
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert 'Grain "day" is not supported for temporal field "year_field"' in str(exc.value)

    # D-E7
    def test_dot_notation_on_nominal(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  p:
    type: string
    values:
      - model: parity_inline
        field: region.month
    default: null
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert 'Dot notation is not valid for nominal dimension "region"' in str(exc.value)

    # D-E8
    def test_model_has_no_source(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: minimal
        field: d1
    default: null
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert str(exc.value) == (
            "parameters.region: model 'minimal' has no 'source:' block, so its field "
            "domains cannot be resolved from data. Add a source to the model, or list "
            "the parameter's values explicitly."
        )

    # D-E9
    def test_inline_data_file_missing(self, tmp_path):
        _write_inline_model(tmp_path, "gen", {"region": {"label": "Region"}}, None)
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: gen
        field: region
    default: null
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        message = str(exc.value)
        assert message.startswith("parameters.region: data file for model 'gen' not found: ")
        assert "gen_data.json" in message

    # D-E10
    def test_empty_domain(self, tmp_path):
        _write_inline_model(tmp_path, "gen", {"region": {"label": "Region"}}, [])
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: gen
        field: region
    default: null
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)
        assert str(exc.value) == (
            "parameters.region: field 'gen.region' resolved to an empty domain — "
            "the data source returned no values."
        )

    def test_empty_bounds_domain(self, tmp_path):
        _write_inline_model(
            tmp_path,
            "gen",
            {"order_date": {"type": "temporal", "label": "D", "defaultGrain": "day"}},
            [],
        )
        params = _write_params(
            tmp_path,
            """
parameters:
  p:
    type: date
    values:
      - model: gen
        field: order_date
    default: null
""",
        )
        with pytest.raises(ParameterDomainError, match="resolved to an empty domain"):
            resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=tmp_path)

    # D-E11
    @respx.mock
    def test_bare_model_field_parameter_default_checked(self, tmp_path, cube_env):
        """A manifest check, not a data query — SHE-89 deferred exactly this."""
        route = respx.post(LOAD_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        params = _write_params(
            tmp_path,
            """
parameters:
  metric:
    type: field
    values:
      - model: orders
    default: profitt
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert str(exc.value) == (
            "parameters.metric: default 'profitt' is not a field in model 'orders'.\n"
            "Available measures: arpu, cost, margin_pct, order_count, revenue.\n"
            "Available dimensions: country, month, product, region, week."
        )
        assert route.call_count == 0

    def test_bare_model_field_parameter_valid_default_passes(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  metric:
    type: field
    values:
      - model: orders
    default: revenue
""",
        )
        assert (
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
            == {}
        )

    # D-E12
    @respx.mock
    def test_cube_error_is_attributed_to_the_parameter(self, tmp_path, cube_env):
        from shelves.data.cube_client import CubeServerError

        respx.post(LOAD_URL).mock(return_value=httpx.Response(500, text="boom"))
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: parity_cube
        field: region
    default: null
""",
        )
        with pytest.raises(ParameterDomainError) as exc:
            resolve_parameter_domains(params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR)
        assert str(exc.value).startswith("parameters.region: ")
        assert isinstance(exc.value.__cause__, CubeServerError)


class TestValidateDefaultsToggle:
    def test_defaults_not_checked_when_disabled(self, tmp_path):
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: parity_inline
        field: region
    default: LATAM
""",
        )
        domains = resolve_parameter_domains(
            params,
            models_dir=MODELS_DIR,
            data_base_dir=FIXTURES_DIR,
            validate_defaults=False,
        )
        assert domains["region"].values == ["APAC", "EMEA", "NA"]


class TestCheckValueInDomain:
    VALUES = Domain(
        kind="values", param_type="string", source="orders.region", values=["APAC", "EMEA"]
    )
    BOUNDS = Domain(
        kind="bounds",
        param_type="date",
        source="orders.order_date",
        min="2024-01-01",
        max="2024-03-01",
    )

    def test_none_is_always_allowed(self):
        check_value_in_domain("p", None, self.VALUES)

    def test_member_passes(self):
        check_value_in_domain("p", "EMEA", self.VALUES)

    def test_non_member_raises(self):
        with pytest.raises(ParameterDomainError, match=r"parameters\.p: "):
            check_value_in_domain("p", "LATAM", self.VALUES)

    def test_date_object_normalized_before_comparison(self):
        check_value_in_domain("p", dt.date(2024, 2, 1), self.BOUNDS)

    def test_out_of_bounds_raises(self):
        with pytest.raises(ParameterDomainError, match="is outside the domain"):
            check_value_in_domain("p", dt.date(2023, 6, 1), self.BOUNDS)


class TestDataBaseDir:
    def test_relative_path_used_as_is_when_no_base_dir(self, tmp_path, monkeypatch):
        """Matches resolve_model_data (pipeline.py) — relative to CWD, not invented."""
        _write_inline_model(tmp_path, "gen", {"region": {"label": "Region"}}, [{"region": "EMEA"}])
        params = _write_params(
            tmp_path,
            """
parameters:
  region:
    type: string
    values:
      - model: gen
        field: region
    default: null
""",
        )
        monkeypatch.chdir(tmp_path)
        domains = resolve_parameter_domains(params, models_dir=tmp_path, data_base_dir=None)
        assert domains["region"].values == ["EMEA"]


class TestDomainCache:
    def test_cache_hit(self, tmp_path):
        """Second call returns the cached Domain without re-querying the backend."""
        _write_inline_model(
            tmp_path,
            "gen",
            {"region": {"label": "Region"}},
            [{"region": "EMEA"}, {"region": "NA"}],
        )
        ref = FieldRef(model="gen", field="region")
        with patch("shelves.data.domains._inline_domain", wraps=_inline_domain) as spy:
            d1 = resolve_field_domain(ref, "string", models_dir=tmp_path, data_base_dir=tmp_path)
            d2 = resolve_field_domain(ref, "string", models_dir=tmp_path, data_base_dir=tmp_path)
            assert d1 == d2
            assert spy.call_count == 1

    def test_ttl_expiry(self, tmp_path):
        """After TTL expires, the second call re-queries the backend."""
        _write_inline_model(
            tmp_path,
            "gen",
            {"region": {"label": "Region"}},
            [{"region": "EMEA"}],
        )
        ref = FieldRef(model="gen", field="region")
        with (
            patch("shelves.data.domains._inline_domain", wraps=_inline_domain) as spy,
            patch("shelves.data.domains.time") as mock_time,
        ):
            mock_time.monotonic.side_effect = [0.0, 0.0 + DOMAIN_CACHE_TTL + 1, 100.0]
            resolve_field_domain(ref, "string", models_dir=tmp_path, data_base_dir=tmp_path)
            resolve_field_domain(ref, "string", models_dir=tmp_path, data_base_dir=tmp_path)
            assert spy.call_count == 2

    def test_explicit_clear(self, tmp_path):
        """clear_domain_cache() forces a re-query even within the TTL."""
        _write_inline_model(
            tmp_path,
            "gen",
            {"region": {"label": "Region"}},
            [{"region": "EMEA"}],
        )
        ref = FieldRef(model="gen", field="region")
        with patch("shelves.data.domains._inline_domain", wraps=_inline_domain) as spy:
            resolve_field_domain(ref, "string", models_dir=tmp_path, data_base_dir=tmp_path)
            clear_domain_cache()
            resolve_field_domain(ref, "string", models_dir=tmp_path, data_base_dir=tmp_path)
            assert spy.call_count == 2

    def test_end_to_end_cross_compile_cache(self, tmp_path):
        """Two resolve_parameter_domains calls share cached domains across invocations."""
        params = _write_params(
            tmp_path,
            """
parameters:
  a:
    type: string
    values:
      - model: parity_inline
        field: region
    default: EMEA
  b:
    type: string
    values:
      - model: parity_inline
        field: region
    default: null
""",
        )
        with patch("shelves.data.domains._inline_domain", wraps=_inline_domain) as spy:
            d1 = resolve_parameter_domains(
                params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
            )
            d2 = resolve_parameter_domains(
                params, models_dir=MODELS_DIR, data_base_dir=FIXTURES_DIR
            )
            assert spy.call_count == 1
            assert d1 == d2

    def test_different_param_type_separate_entries(self, tmp_path):
        """string and number on the same (model, field) produce separate cache entries."""
        _write_inline_model(
            tmp_path,
            "gen",
            {"fy": {"label": "Fiscal Year"}},
            [{"fy": 2023}, {"fy": 2024}],
        )
        ref = FieldRef(model="gen", field="fy")
        with patch("shelves.data.domains._inline_domain", wraps=_inline_domain) as spy:
            d1 = resolve_field_domain(ref, "string", models_dir=tmp_path, data_base_dir=tmp_path)
            d2 = resolve_field_domain(ref, "number", models_dir=tmp_path, data_base_dir=tmp_path)
            assert d1.kind == "values"
            assert d2.kind == "bounds"
            assert spy.call_count == 2
