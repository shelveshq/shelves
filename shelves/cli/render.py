"""
CLI: Render a chart YAML file to HTML

Usage:
  shelves-render chart.yaml --models-dir models/
  shelves-render chart.yaml --models-dir models/ --out output/chart.html
  shelves-render chart.yaml --models-dir models/ --no-theme
  shelves-render dashboard.yaml --chart-dir charts/ --models-dir models/

When --data is omitted, fetches data from Cube.dev using CUBE_API_URL and
CUBE_API_TOKEN environment variables. Pass --data for inline JSON or --no-data
to render without data.

Development/debugging tool, not part of the production API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml as yaml_lib
from dotenv import load_dotenv

from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from shelves.theme.merge import merge_theme, load_theme
from shelves.data.bind import resolve_data
from shelves.render.to_html import render_html


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Render a chart or dashboard YAML to HTML")
    parser.add_argument("yaml_path", help="Path to chart or dashboard YAML file")
    parser.add_argument("--data", help="Path to JSON data file (array of row objects)")
    parser.add_argument("--out", help="Output HTML file path")
    parser.add_argument(
        "--no-theme", action="store_true", help="Skip theme merging (takes priority over --theme)"
    )
    parser.add_argument("--theme", help="Path to custom theme YAML file")
    parser.add_argument("--no-data", action="store_true", help="Render without data")
    parser.add_argument(
        "--chart-dir", help="Base directory for resolving chart link paths in dashboards"
    )
    parser.add_argument(
        "--data-dir",
        help="Base directory for resolving inline data source paths in dashboards (default: CWD)",
    )
    parser.add_argument(
        "--models-dir",
        help="Directory containing model YAML files for dashboards",
    )
    args = parser.parse_args()

    # Detect dashboard vs chart YAML
    yaml_string = Path(args.yaml_path).read_text()
    raw = yaml_lib.safe_load(yaml_string)

    if isinstance(raw, dict) and "dashboard" in raw:
        _render_dashboard(args, raw)
    else:
        _render_chart(args, yaml_string)


def _render_dashboard(args, raw):
    """Render a dashboard YAML file."""
    from shelves.compose.dashboard import compose_dashboard

    theme_path = Path(args.theme) if args.theme else None
    theme = load_theme(theme_path) if not args.no_theme else None

    html = compose_dashboard(
        dashboard_path=Path(args.yaml_path),
        theme=theme,
        chart_base_dir=Path(args.chart_dir) if args.chart_dir else None,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        models_dir=Path(args.models_dir) if args.models_dir else None,
        no_theme=args.no_theme,
    )

    slug = raw["dashboard"].lower().replace(" ", "-")
    out_path = Path(args.out) if args.out else Path("output") / f"{slug}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"Rendered: {out_path}")


def _render_chart(args, yaml_string):
    """Render a chart YAML file (existing pipeline)."""
    spec = parse_chart(yaml_string)
    models_dir = Path(args.models_dir) if args.models_dir else None

    # Translate
    vl_spec = translate_chart(spec, models_dir=models_dir)

    # Theme
    if not args.no_theme:
        theme_path = Path(args.theme) if args.theme else None
        theme = load_theme(theme_path)
        vl_spec = merge_theme(vl_spec, theme)

    # Data
    if args.no_data:
        pass  # render spec structure only
    elif args.data:
        rows = json.loads(Path(args.data).read_text())
        vl_spec = resolve_data(vl_spec, spec, rows=rows)
    else:
        # Try to auto-load from model's configured source
        from shelves.models.loader import load_model

        model = load_model(spec.data, models_dir=models_dir)
        if model.source and model.source.type == "inline":
            data_path = Path(model.source.path)
            if data_path.exists():
                rows = json.loads(data_path.read_text())
                vl_spec = resolve_data(vl_spec, spec, rows=rows)
            else:
                print(f"Warning: model source path {data_path} not found")
        else:
            # Cube source or no source — try Cube.dev
            vl_spec = resolve_data(vl_spec, spec, models_dir=models_dir)

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
