"""
CLI: Render a chart YAML file to HTML

Usage:
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --data tests/fixtures/data/orders.json
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --out output/chart.html
  python -m src.cli.render tests/fixtures/yaml/simple_bar.yaml --no-theme

Development/debugging tool, not part of the production API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.schema.chart_schema import parse_chart
from src.translator.translate import translate_chart
from src.theme.merge import merge_theme
from src.data.bind import bind_data
from src.render.to_html import render_html


def main():
    parser = argparse.ArgumentParser(description="Render a chart YAML to HTML")
    parser.add_argument("yaml_path", help="Path to chart YAML file")
    parser.add_argument("--data", help="Path to JSON data file (array of row objects)")
    parser.add_argument("--out", help="Output HTML file path")
    parser.add_argument("--no-theme", action="store_true", help="Skip theme merging")
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
    if args.data:
        rows = json.loads(Path(args.data).read_text())
        vl_spec = bind_data(vl_spec, rows)

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
