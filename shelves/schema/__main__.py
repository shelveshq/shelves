"""`python -m shelves.schema` — regenerate the committed JSON Schema artifacts."""

from __future__ import annotations

from shelves.schema.json_schema import write_schemas

if __name__ == "__main__":
    for path in write_schemas():
        print(f"wrote {path}")
