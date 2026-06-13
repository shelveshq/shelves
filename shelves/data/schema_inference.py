"""
Schema Inference

Infers a data model schema from a flat file (CSV, Parquet, JSON) using DuckDB.
Maps DuckDB column types to Shelves model field types (nominal, temporal, measure).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, TypedDict

from shelves.data.duckdb_adapter import _file_reader_fn


class _InferredFieldOptional(TypedDict, total=False):
    column: str
    aggregation: str
    defaultGrain: str


class InferredField(_InferredFieldOptional):
    type: Literal["nominal", "temporal", "measure"]
    label: str


_MEASURE_TYPES = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "FLOAT",
        "DOUBLE",
    }
)

_TEMPORAL_TYPES = frozenset(
    {
        "DATE",
        "TIMESTAMP",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMP_S",
        "TIMESTAMP_MS",
        "TIMESTAMP_NS",
    }
)


def _slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    s = s[:64]
    return s or "column"


def _make_label(original_name: str) -> str:
    if " " in original_name or original_name != original_name.lower():
        return original_name
    return re.sub(r"_", " ", original_name).title()


def _classify_dtype(dtype_str: str) -> tuple[Literal["nominal", "temporal", "measure"], dict]:
    upper = dtype_str.upper()

    if upper in _MEASURE_TYPES or upper.startswith("DECIMAL"):
        return "measure", {"aggregation": "sum"}

    if upper in _TEMPORAL_TYPES:
        return "temporal", {"defaultGrain": "day"}

    return "nominal", {}


def infer_schema(file_path: str | Path) -> dict[str, InferredField]:
    try:
        import duckdb
    except ImportError:
        raise ImportError(
            "duckdb is required for schema inference. "
            "Install with: pip install 'shelves-bi[duckdb]'"
        ) from None

    path = Path(file_path)
    reader = _file_reader_fn(str(path))
    escaped = str(path).replace("'", "''")

    conn = duckdb.connect(":memory:")
    try:
        result = conn.execute(f"SELECT * FROM {reader}('{escaped}') LIMIT 0")
        columns = result.description
    finally:
        conn.close()

    schema: dict[str, InferredField] = {}
    seen_keys: dict[str, int] = {}

    for col_desc in columns:
        original_name = col_desc[0]
        dtype_str = str(col_desc[1])

        key = _slugify(original_name)

        if key in seen_keys:
            seen_keys[key] += 1
            key = f"{key}_{seen_keys[key]}"
        else:
            seen_keys[key] = 1

        field_type, extras = _classify_dtype(dtype_str)
        label = _make_label(original_name)

        entry = InferredField(type=field_type, label=label, **extras)

        if key != original_name:
            entry["column"] = original_name

        schema[key] = entry

    return schema
