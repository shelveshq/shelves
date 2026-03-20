"""
CLI: Render a chart YAML file to HTML

Usage:
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --out output/chart.html
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --no-theme

When --data is omitted, fetches data from Cube.dev using CUBE_API_URL and
CUBE_API_TOKEN environment variables. Pass --data for inline JSON or --no-data
to render without data.

Development/debugging tool, not part of the production API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.schema.chart_schema import parse_chart
from src.translator.translate import translate_chart
from src.theme.merge import merge_theme
from src.data.bind import resolve_data
from src.render.to_html import render_html


def main():
    parser = argparse.ArgumentParser(description="Render a chart YAML to HTML")
    parser.add_argument("yaml_path", help="Path to chart YAML file")
    parser.add_argument("--data", help="Path to JSON data file (array of row objects)")
    parser.add_argument("--out", help="Output HTML file path")
    parser.add_argument("--no-theme", action="store_true", help="Skip theme merging")
    parser.add_argument("--no-data", action="store_true", help="Render without data")
    args = parser.parse_args()

    # Parse YAML
    yaml_string = Path(args.yaml_path).read_text()
    spec = parse_chart(yaml_string)

    # Translate
    vl_spec = translate_chart(spec)

    # Theme
    if not args.no_theme:
        vl_spec = merge_theme(vl_spec)

    # Data
    if args.no_data:
        pass  # render spec structure only
    elif args.data:
        rows = json.loads(Path(args.data).read_text())
        vl_spec = resolve_data(vl_spec, spec, rows=rows)
    else:
        # Try to auto-load from model's configured source
        from src.models.loader import load_model

        model = load_model(spec.data)
        if model.source and model.source.type == "inline":
            data_path = Path(model.source.path)
            if data_path.exists():
                rows = json.loads(data_path.read_text())
                vl_spec = resolve_data(vl_spec, spec, rows=rows)
            else:
                print(f"Warning: model source path {data_path} not found")
        else:
            # Cube source or no source — try Cube.dev
            vl_spec = resolve_data(vl_spec, spec)

    # Render
    html = render_html(vl_spec, title=spec.sheet)

    # Write output
    slug = spec.sheet.lower().replace(" ", "-")
    out_path = Path(args.out) if args.out else Path("output") / f"{slug}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)

    print(f"Rendered: {out_path}")


if __name__ == "__main__":
    main()
