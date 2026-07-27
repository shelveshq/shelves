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
import os
import sys
from pathlib import Path

import yaml as yaml_lib
from dotenv import load_dotenv

from shelves.data.bind import resolve_data
from shelves.params.coerce import parse_param_flags
from shelves.params.resolve import load_parameter_set
from shelves.render.to_html import render_html
from shelves.theme.merge import load_theme


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for shelves-render."""
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
        help="Base directory for resolving inline data source paths (default: CWD)",
    )
    parser.add_argument(
        "--models-dir",
        help="Directory containing model YAML files for dashboards",
    )
    parser.add_argument(
        "--assets-dir",
        help="Directory of image assets referenced by dashboards (default: ./assets)",
    )
    parser.add_argument(
        "--parameters-file",
        help="Path to parameters.yaml (default: <models-dir>/parameters.yaml)",
    )
    parser.add_argument(
        "--param",
        action="append",
        # argparse's append action defaults to None, which would make
        # parse_param_flags(args.param) a TypeError when no flag is passed.
        default=[],
        metavar="KEY=VALUE",
        help="Set a parameter value (repeatable), e.g. --param region=EMEA",
    )
    return parser


def main():
    load_dotenv()
    args = build_parser().parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else None

    # Built once, before anything is written: a bad --param should fail before
    # an output file exists. --no-data means touch no data source, so it also
    # skips field-reference domain resolution.
    try:
        parameters = load_parameter_set(
            Path(args.parameters_file) if args.parameters_file else None,
            models_dir=Path(args.models_dir) if args.models_dir else None,
            data_base_dir=data_dir,
            overrides=parse_param_flags(args.param),
            resolve_domains=not args.no_data,
        )
    except ValueError as e:  # ParameterDomainError included
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    # Detect dashboard vs chart YAML
    yaml_string = Path(args.yaml_path).read_text()
    raw = yaml_lib.safe_load(yaml_string)

    if isinstance(raw, dict) and "dashboard" in raw:
        _render_dashboard(args, raw, parameters)
    else:
        _render_chart(args, yaml_string, parameters)


def _asset_url_prefix(assets_dir: Path, output_dir: Path) -> str:
    """URL prefix for image assets in standalone-rendered HTML.

    A relative path (with trailing slash) from the output HTML's directory to
    the assets directory, e.g. "../assets/", so `<img src>` resolves when the
    HTML is opened from disk.
    """
    rel = Path(os.path.relpath(assets_dir, output_dir)).as_posix()
    return rel if rel.endswith("/") else rel + "/"


def _render_dashboard(args, raw, parameters=None):
    """Render a dashboard YAML file."""
    from shelves.compose.dashboard import compose_dashboard

    theme_path = Path(args.theme) if args.theme else None
    theme = load_theme(theme_path) if not args.no_theme else None

    slug = raw["dashboard"].lower().replace(" ", "-")
    out_path = Path(args.out) if args.out else Path("output") / f"{slug}.html"

    assets_dir = Path(args.assets_dir).resolve() if args.assets_dir else Path("assets").resolve()
    asset_url_prefix = _asset_url_prefix(assets_dir, out_path.parent.resolve())

    html = compose_dashboard(
        dashboard_path=Path(args.yaml_path),
        theme=theme,
        chart_base_dir=Path(args.chart_dir) if args.chart_dir else None,
        data_dir=Path(args.data_dir) if args.data_dir else None,
        models_dir=Path(args.models_dir) if args.models_dir else None,
        no_theme=args.no_theme,
        asset_url_prefix=asset_url_prefix,
        parameters=parameters,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"Rendered: {out_path}")


def _render_chart(args, yaml_string, parameters=None):
    """Render a chart YAML file."""
    from shelves.pipeline import compile_chart, resolve_model_data

    models_dir = Path(args.models_dir) if args.models_dir else None
    data_dir = Path(args.data_dir) if args.data_dir else None
    theme_path = Path(args.theme) if args.theme else None

    vl_spec, spec = compile_chart(
        yaml_string,
        theme_path=theme_path,
        no_theme=args.no_theme,
        models_dir=models_dir,
        parameters=parameters,
    )

    if args.no_data:
        pass
    elif args.data:
        rows = json.loads(Path(args.data).read_text())
        vl_spec = resolve_data(vl_spec, spec, rows=rows)
    else:
        # data_base_dir matters here, not just on the dashboard branch: domain
        # resolution reads --data-dir, so a chart resolving rows from the CWD
        # would validate a parameter against one dataset and chart another.
        vl_spec = resolve_model_data(vl_spec, spec, models_dir=models_dir, data_base_dir=data_dir)

    html = render_html(vl_spec, title=spec.sheet)

    slug = spec.sheet.lower().replace(" ", "-")
    out_path = Path(args.out) if args.out else Path("output") / f"{slug}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"Rendered: {out_path}")


if __name__ == "__main__":
    main()
