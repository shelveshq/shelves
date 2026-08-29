"""`python -m shelves.schema` — regenerate the committed JSON Schema artifacts.

Pass `--out DIR` to instead drop the schemas into your own project (e.g. so a
`# yaml-language-server: $schema=...` comment can point at a local file)."""

from __future__ import annotations

import argparse
from pathlib import Path

from shelves.schema.json_schema import write_schemas

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regenerate Shelves JSON Schema artifacts.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: the bundled schemas inside the package).",
    )
    args = parser.parse_args()
    for path in write_schemas(args.out):
        print(f"wrote {path}")
