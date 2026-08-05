"""
Filter operator parity tests.

Every FilterOperator member must produce a non-empty result (or raise a typed
backend error) at each of the four dispatch sites: Vega-Lite translator, DuckDB
adapter, Cube client, and schema validator.

The parity parametrization fails by name on any (operator, site) gap.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from shelves.data.cube_client import CubeQueryError, _translate_filters
from shelves.data.duckdb_adapter import (
    DuckDBQueryError,
    _build_filter_conditions,
)
from shelves.models.resolver import ModelResolver
from shelves.models.schema import DataModel
from shelves.schema.chart_schema import (
    _OPERATOR_RULES,
    FilterOperator,
    ShelfFilter,
)
from shelves.translator.filters import _translate_filter

# ─── Shared fixtures ────────────────────────────────────────────────

_PARITY_MODEL = DataModel.model_validate(
    {
        "model": "parity",
        "label": "Parity Test",
        "measures": {"_dummy": {"label": "Dummy", "column": "x", "aggregation": "sum"}},
        "dimensions": {"test_field": {"label": "Test Field"}},
    }
)
_PARITY_RESOLVER = ModelResolver(_PARITY_MODEL)

_TYPED_ERRORS = (DuckDBQueryError, CubeQueryError)


def _make_filter(op: str) -> ShelfFilter:
    """Build a valid ShelfFilter for *op*, deriving value shape from _OPERATOR_RULES."""
    required, _ = _OPERATOR_RULES[op]
    kwargs: dict[str, Any] = {"field": "test_field", "operator": op}
    if required == "value":
        kwargs["value"] = 42
    elif required == "values":
        kwargs["values"] = ["a", "b"]
    elif required == "range":
        kwargs["range"] = [10, 20]
    return ShelfFilter(**kwargs)


# ─── Dispatch sites ─────────────────────────────────────────────────


def _site_vegalite(f: ShelfFilter) -> Any:
    return _translate_filter(f)


def _site_duckdb(f: ShelfFilter) -> list[str]:
    return _build_filter_conditions([f], _PARITY_MODEL, _PARITY_RESOLVER)


def _site_cube(f: ShelfFilter) -> list[dict[str, Any]]:
    return _translate_filters([f], "parity_cube", _PARITY_RESOLVER)


def _site_schema(f: ShelfFilter) -> tuple[str, list[str]]:
    return _OPERATOR_RULES[f.operator]


_SITES: dict[str, Any] = {
    "vegalite": _site_vegalite,
    "duckdb": _site_duckdb,
    "cube": _site_cube,
    "schema": _site_schema,
}


# ─── Parity test ────────────────────────────────────────────────────


@pytest.mark.parametrize("op", get_args(FilterOperator))
@pytest.mark.parametrize("site", list(_SITES))
class TestFilterOperatorParity:
    def test_operator_reaches_site(self, op: str, site: str) -> None:
        """Every FilterOperator must produce a non-empty result at every site."""
        f = _make_filter(op)
        dispatch = _SITES[site]
        try:
            result = dispatch(f)
        except _TYPED_ERRORS:
            return
        assert result, (
            f"Operator {op!r} produced empty result at {site!r} — "
            f"the dispatch site must either emit a non-empty result or raise a typed error"
        )


# ─── Unsupported-operator error paths ───────────────────────────────


class TestContainsEscaping:
    """Contains operator must escape SQL wildcards and backslashes."""

    def test_duckdb_contains_escapes_percent(self) -> None:
        f = ShelfFilter(field="test_field", operator="contains", value="50%")
        conditions = _build_filter_conditions([f], _PARITY_MODEL, _PARITY_RESOLVER)
        sql = conditions[0]
        assert "\\%" in sql
        assert "ESCAPE" in sql

    def test_duckdb_contains_escapes_underscore(self) -> None:
        f = ShelfFilter(field="test_field", operator="contains", value="a_b")
        conditions = _build_filter_conditions([f], _PARITY_MODEL, _PARITY_RESOLVER)
        sql = conditions[0]
        assert "\\_" in sql

    def test_duckdb_contains_escapes_backslash(self) -> None:
        f = ShelfFilter(field="test_field", operator="contains", value="a\\b")
        conditions = _build_filter_conditions([f], _PARITY_MODEL, _PARITY_RESOLVER)
        sql = conditions[0]
        assert "\\\\" in sql

    def test_vegalite_contains_escapes_backslash(self) -> None:
        f = ShelfFilter(field="test_field", operator="contains", value="a\\b")
        result = _translate_filter(f)
        assert isinstance(result, str)
        assert "a\\\\b" in result


class TestUnsupportedOperatorErrors:
    def test_duckdb_raises_on_unknown_operator(self) -> None:
        """An operator not in the DuckDB dispatch table must raise DuckDBQueryError."""
        f = ShelfFilter.model_construct(field="test_field", operator="__unsupported__", value="x")
        with pytest.raises(DuckDBQueryError, match="__unsupported__"):
            _build_filter_conditions([f], _PARITY_MODEL, _PARITY_RESOLVER)

    def test_cube_raises_on_unknown_operator(self) -> None:
        """An operator not in the Cube dispatch table must raise CubeQueryError."""
        f = ShelfFilter.model_construct(field="test_field", operator="__unsupported__", value="x")
        with pytest.raises(CubeQueryError, match="__unsupported__"):
            _translate_filters([f], "parity_cube", _PARITY_RESOLVER)
