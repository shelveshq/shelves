"""
Model YAML Generator

Generates a data model YAML string from an inferred schema.
Uses ruamel.yaml for clean output (block style, preserved key order).
"""

from __future__ import annotations

import re
from io import StringIO

from ruamel.yaml import YAML

from shelves.data.schema_inference import InferredField


def _make_model_label(model_name: str) -> str:
    return re.sub(r"_", " ", model_name).title()


def generate_model_yaml(
    schema: dict[str, InferredField],
    model_name: str,
    file_path: str,
) -> str:
    dimensions: dict[str, InferredField] = {}
    measures: dict[str, InferredField] = {}

    for key, field in schema.items():
        if field["type"] in ("nominal", "temporal"):
            dimensions[key] = field
        elif field["type"] == "measure":
            measures[key] = field

    # Determine the first column name for _row_count
    all_keys = list(schema.keys())
    first_col = all_keys[0] if all_keys else "id"
    first_col_original = schema[first_col].get("column", first_col) if all_keys else first_col

    dim_section: dict = {}
    for key, field in dimensions.items():
        entry: dict = {}
        col = field.get("column", key)
        entry["column"] = col
        if field["type"] == "temporal":
            entry["type"] = "temporal"
        entry["label"] = field["label"]
        if field["type"] == "temporal":
            entry["defaultGrain"] = field.get("defaultGrain", "day")
        dim_section[key] = entry

    measure_section: dict = {}
    for key, field in measures.items():
        entry = {}
        col = field.get("column", key)
        entry["column"] = col
        entry["aggregation"] = field.get("aggregation", "sum")
        entry["label"] = field["label"]
        measure_section[key] = entry

    measure_section["_row_count"] = {
        "column": first_col_original,
        "aggregation": "count",
        "label": "Row Count",
    }

    doc: dict = {
        "model": model_name,
        "label": _make_model_label(model_name),
        "source": {
            "type": "file",
            "path": file_path,
        },
    }

    if dim_section:
        doc["dimensions"] = dim_section
    doc["measures"] = measure_section

    yml = YAML()
    yml.default_flow_style = False
    yml.allow_unicode = True

    buf = StringIO()
    yml.dump(doc, buf)
    return buf.getvalue()
