"""
DuckDB Query Adapter

Translates chart field needs + model definitions into SQL, executes against
a local DuckDB in-memory database loaded from a flat file (CSV, Parquet, JSON).

The adapter has three layers:
  1. Measure expression resolution — {{ ref }} substitution via topological sort
  2. SQL assembly — SELECT / FROM / WHERE / GROUP BY
  3. DuckDB execution — file loading and query execution

Layers 1–2 are pure functions (no DuckDB import). Layer 3 imports duckdb lazily.
"""

from __future__ import annotations

import datetime
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from shelves.data.fields import collect_chart_fields
from shelves.errors import ShelvesError
from shelves.models.schema import (
    CALC_REF_RE,
    DataModel,
    FileSource,
)
from shelves.schema.chart_schema import ChartSpec, ShelfFilter
from shelves.schema.field_types import FieldTypeResolver


class DuckDBQueryError(ShelvesError):
    """Error building or executing a DuckDB query."""


_FILE_READERS: dict[str, str] = {
    ".csv": "read_csv_auto",
    ".parquet": "read_parquet",
    ".json": "read_json_auto",
}

_SQL_OPERATORS: dict[str, str] = {
    "eq": "=",
    "neq": "!=",
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
}


def _quote_identifier(name: str) -> str:
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def _quote_value(v: str | int | float) -> str:
    if isinstance(v, str):
        escaped = v.replace("'", "''")
        return f"'{escaped}'"
    return str(v)


def _file_reader_fn(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext not in _FILE_READERS:
        raise DuckDBQueryError(
            f"Unsupported file extension '{ext}' for path '{path}'. "
            f"Supported: {sorted(_FILE_READERS.keys())}"
        )
    return _FILE_READERS[ext]


def _serialize_value(v: Any) -> Any:
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def resolve_measure_expressions(model: DataModel) -> dict[str, str]:
    """
    Resolve all measure definitions in a model to SQL expressions.

    Handles column+aggregation, calculations with {{ ref }} cross-references
    (via topological sort), raw SQL calculations, and bare column references.
    """
    from graphlib import TopologicalSorter

    exprs: dict[str, str] = {}
    calc_graph: dict[str, set[str]] = {}

    for name, measure in model.measures.items():
        if measure.column is not None and measure.aggregation is not None:
            agg = measure.aggregation.upper()
            col = _quote_identifier(measure.column)
            if agg == "COUNT_DISTINCT":
                exprs[name] = f"COUNT(DISTINCT {col})"
            else:
                exprs[name] = f"{agg}({col})"
        elif measure.calculation is not None:
            refs = set(CALC_REF_RE.findall(measure.calculation))
            calc_graph[name] = refs
        elif measure.column is not None:
            exprs[name] = _quote_identifier(measure.column)

    if calc_graph:
        ts = TopologicalSorter(calc_graph)
        for name in ts.static_order():
            if name in exprs:
                continue
            measure = model.measures[name]
            if measure.calculation is None:
                raise DuckDBQueryError(
                    f"Measure '{name}' is referenced in a calculation but has no "
                    "column or calculation of its own, so it cannot be resolved to "
                    "SQL. File source measures require a column+aggregation or a "
                    "calculation."
                )
            resolved = measure.calculation
            for ref in CALC_REF_RE.findall(measure.calculation):
                resolved = re.sub(
                    r"\{\{\s*" + re.escape(ref) + r"\s*\}\}",
                    f"({exprs[ref]})",
                    resolved,
                )
            exprs[name] = resolved

    return exprs


def build_sql(
    file_path: str,
    model: DataModel,
    chart_spec: ChartSpec,
    resolver: FieldTypeResolver,
) -> str:
    """Build a SQL SELECT statement for the fields a chart needs."""
    fields = collect_chart_fields(chart_spec)
    measure_exprs = resolve_measure_expressions(model)

    select_parts: list[str] = []
    group_by_parts: list[str] = []
    has_measures = False
    # base field name → the SQL expression already selected under that alias.
    # Two field refs that resolve to the same base must share one expression;
    # differing expressions (e.g. two grains of one temporal field) would
    # collide on the output alias and silently drop a column when rows are
    # zipped into dicts, so they are rejected.
    selected_exprs: dict[str, str] = {}

    def _select(base: str, expr: str) -> bool:
        """Register a SELECT column for `base`. Returns True if newly added."""
        existing = selected_exprs.get(base)
        if existing is not None:
            if existing != expr:
                raise DuckDBQueryError(
                    f"Field '{base}' is referenced with two different expressions "
                    f"in the same chart ({existing!r} vs {expr!r}) — likely two "
                    "different grains of the same temporal field. Use a single "
                    "grain per field within a chart."
                )
            return False
        selected_exprs[base] = expr
        select_parts.append(f"{expr} AS {_quote_identifier(base)}")
        return True

    for field in sorted(fields):
        base = resolver.resolve_base_field(field)

        if resolver.is_measure(field):
            has_measures = True
            if base not in measure_exprs:
                raise DuckDBQueryError(
                    f"Cannot query measure '{base}': no column or calculation defined. "
                    "File source measures require a column+aggregation or a calculation."
                )
            _select(base, measure_exprs[base])
        else:
            dim_def = model.dimensions.get(base)
            grain = resolver.resolve_grain(field)

            if dim_def is not None and dim_def.calculation is not None:
                dim_sql = dim_def.calculation
            else:
                col = dim_def.column if dim_def is not None and dim_def.column is not None else base
                col_quoted = _quote_identifier(col)

                if grain is not None:
                    dim_sql = f"DATE_TRUNC('{grain}', {col_quoted})"
                else:
                    dim_sql = col_quoted

            if _select(base, dim_sql):
                group_by_parts.append(dim_sql)

    reader = _file_reader_fn(file_path)
    escaped_path = file_path.replace("'", "''")
    from_clause = f"{reader}('{escaped_path}')"

    where_clause = ""
    if chart_spec.filters:
        conditions = _build_filter_conditions(chart_spec.filters, model, resolver)
        if conditions:
            where_clause = f"\nWHERE {' AND '.join(conditions)}"

    group_by_clause = ""
    if has_measures and group_by_parts:
        group_by_clause = f"\nGROUP BY {', '.join(group_by_parts)}"

    select_keyword = "SELECT DISTINCT" if not has_measures else "SELECT"

    sql = f"{select_keyword} {', '.join(select_parts)}\nFROM {from_clause}"
    return f"{sql}{where_clause}{group_by_clause}"


def _build_filter_conditions(
    filters: list[ShelfFilter],
    model: DataModel,
    resolver: FieldTypeResolver,
) -> list[str]:
    conditions: list[str] = []

    for f in filters:
        base = resolver.resolve_base_field(f.field)

        dim = model.dimensions.get(base)
        if dim is not None:
            if dim.calculation is not None:
                col_ref = dim.calculation
            elif dim.column is not None:
                col_ref = _quote_identifier(dim.column)
            else:
                col_ref = _quote_identifier(base)
        else:
            measure = model.measures.get(base)
            if measure is not None and measure.column is not None:
                col_ref = _quote_identifier(measure.column)
            elif measure is not None:
                raise DuckDBQueryError(
                    f"Cannot filter on measure '{base}': it has no underlying column "
                    "(it is a calculation or metadata-only measure). Filters on file "
                    "sources must reference a column-backed dimension or measure."
                )
            else:
                col_ref = _quote_identifier(base)

        if f.operator in _SQL_OPERATORS:
            assert f.value is not None
            conditions.append(f"{col_ref} {_SQL_OPERATORS[f.operator]} {_quote_value(f.value)}")
        elif f.operator == "in":
            assert f.values is not None
            vals = ", ".join(_quote_value(v) for v in f.values)
            conditions.append(f"{col_ref} IN ({vals})")
        elif f.operator == "not_in":
            assert f.values is not None
            vals = ", ".join(_quote_value(v) for v in f.values)
            conditions.append(f"{col_ref} NOT IN ({vals})")
        elif f.operator == "between":
            assert f.range is not None
            conditions.append(
                f"{col_ref} BETWEEN {_quote_value(f.range[0])} AND {_quote_value(f.range[1])}"
            )

    return conditions


class DuckDBAdapter:
    """Data source adapter that queries local flat files via DuckDB."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path.cwd()

    def _resolve_path(self, source: FileSource) -> str:
        p = Path(source.path)
        if p.is_absolute():
            return str(p)
        return str((self._base_dir / p).resolve())

    def fetch(
        self,
        model: DataModel,
        chart_spec: ChartSpec,
        resolver: FieldTypeResolver,
    ) -> list[dict[str, Any]]:
        try:
            import duckdb
        except ImportError:
            raise ImportError(
                "duckdb is required for file source queries. "
                "Install with: pip install 'shelves-bi[duckdb]'"
            ) from None

        if not isinstance(model.source, FileSource):
            raise DuckDBQueryError(
                f"DuckDBAdapter requires a FileSource, got {type(model.source).__name__}"
            )

        file_path = self._resolve_path(model.source)

        if not Path(file_path).exists():
            raise DuckDBQueryError(f"Data file not found: {file_path}")

        sql = build_sql(file_path, model, chart_spec, resolver)

        try:
            conn = duckdb.connect(":memory:")
            try:
                result = conn.execute(sql)
                columns = [desc[0] for desc in result.description]
                raw_rows = result.fetchall()
            finally:
                conn.close()
        except Exception as e:
            if isinstance(e, DuckDBQueryError):
                raise
            raise DuckDBQueryError(f"DuckDB query failed: {e}") from e

        return [
            {col: _serialize_value(val) for col, val in zip(columns, row, strict=True)}
            for row in raw_rows
        ]
