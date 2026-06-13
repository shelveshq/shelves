"""
CLI: Import a flat file and generate a data model YAML

Usage:
  shelves-import sales.csv
  shelves-import sales.csv --name orders
  shelves-import sales.csv --models-dir path/to/models/
  shelves-import sales.csv --overwrite
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".json"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a flat file and generate a data model")
    parser.add_argument("file_path", help="Path to CSV, Parquet, or JSON file")
    parser.add_argument("--name", help="Model name (default: file stem)")
    parser.add_argument(
        "--models-dir", default="models", help="Output directory (default: models/)"
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing model file")
    args = parser.parse_args()

    file_path = Path(args.file_path)

    if not file_path.exists():
        print(f"File not found: {args.file_path}", file=sys.stderr)
        sys.exit(1)

    ext = file_path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        print(
            f"Unsupported file format: {ext}. Supported: .csv, .parquet, .json",
            file=sys.stderr,
        )
        sys.exit(1)

    model_name = args.name or file_path.stem

    models_dir = Path(args.models_dir)
    model_path = models_dir / f"{model_name}.yaml"

    if model_path.exists() and not args.overwrite:
        print(
            f"Model '{model_name}' already exists at {model_path}. Use --overwrite to replace.",
            file=sys.stderr,
        )
        sys.exit(1)

    from shelves.data.schema_inference import infer_schema

    try:
        schema = infer_schema(file_path)
    except Exception as e:
        print(f"Failed to read {args.file_path}: {e}", file=sys.stderr)
        sys.exit(1)

    relative_path = os.path.relpath(file_path.resolve())

    from shelves.data.model_generator import generate_model_yaml

    yaml_str = generate_model_yaml(schema, model_name, relative_path)

    models_dir.mkdir(parents=True, exist_ok=True)
    model_path.write_text(yaml_str)

    print(f"Created model: {model_path}")


if __name__ == "__main__":
    main()
