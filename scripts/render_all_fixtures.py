#!/usr/bin/env python3
"""
Batch render all YAML chart fixtures with the default theme applied.

Outputs themed HTML files to output/theme_qa/ with an index page for
visual review. Skips Cube-dependent fixtures and layer/dual-axis
fixtures that aren't compilable yet (Phase 1a deferred).

Usage:
    .venv/bin/python scripts/render_all_fixtures.py
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from shelves.schema.chart_schema import parse_chart
from shelves.translator.translate import translate_chart
from shelves.theme.merge import merge_theme, load_theme
from shelves.data.bind import bind_data
from shelves.render.to_html import render_html

FIXTURES_DIR = Path("tests/fixtures/yaml")
DATA_PATH = Path("tests/fixtures/data/orders.json")
MODELS_DIR = Path("tests/fixtures/models")
OUTPUT_DIR = Path("output/theme_qa")

# Fixtures that require Cube.dev — skip (no local data)
SKIP_CUBE = {"cube_filtered.yaml", "cube_sales_by_category.yaml", "cube_sales_over_time.yaml"}

# Fixtures with layers/dual-axis — Phase 1a deferred, may not compile cleanly
SKIP_LAYERS = {"dual_axis.yaml", "triple_axis.yaml", "stacked_layers.yaml", "layers_faceted.yaml"}

SKIP = SKIP_CUBE | SKIP_LAYERS


def render_fixture(yaml_path: Path, data_rows: list[dict], theme) -> str | None:
    """
    Render a single YAML fixture to HTML string.

    Returns HTML string on success, None on error (prints warning).
    """
    try:
        yaml_string = yaml_path.read_text()
        spec = parse_chart(yaml_string)
        vl_spec = translate_chart(spec, models_dir=MODELS_DIR)
        themed = merge_theme(vl_spec, theme)
        bound = bind_data(themed, data_rows)
        return render_html(bound, title=spec.sheet)
    except Exception as e:
        print(f"  WARNING: {yaml_path.name} failed: {e}")
        return None


def build_index(results: list[tuple[str, str]]) -> str:
    """
    Build an index.html page linking to all rendered charts.

    Args:
        results: list of (fixture_name, html_filename) tuples

    Returns:
        HTML string for the index page.
    """
    if not results:
        cards = '<p style="color: #666; text-align: center;">No charts rendered.</p>'
    else:
        card_items = []
        for name, filename in results:
            safe_name = html.escape(name)
            safe_file = html.escape(filename)
            card_items.append(
                f'<a href="{safe_file}" class="card">'
                f'<span class="name">{safe_name}</span>'
                f'<span class="arrow">&#8594;</span>'
                f"</a>"
            )
        cards = "\n      ".join(card_items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Charter Theme QA — Fixture Gallery</title>
  <style>
    body {{
      margin: 0; padding: 32px;
      font-family: Inter, system-ui, sans-serif;
      background: #f5f5f5;
      color: #1a1a1a;
    }}
    h1 {{
      font-size: 24px; font-weight: 600;
      margin: 0 0 8px 0;
    }}
    .subtitle {{
      font-size: 14px; color: #666666;
      margin: 0 0 24px 0;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
    }}
    .card {{
      display: flex; justify-content: space-between; align-items: center;
      background: #ffffff; border: 1px solid #e5e7eb;
      border-radius: 8px; padding: 16px 20px;
      text-decoration: none; color: #1a1a1a;
      transition: box-shadow 0.15s;
    }}
    .card:hover {{
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }}
    .name {{
      font-size: 14px; font-weight: 500;
    }}
    .arrow {{
      font-size: 18px; color: #999999;
    }}
  </style>
</head>
<body>
  <h1>Charter Theme QA</h1>
  <p class="subtitle">{len(results)} fixture{"s" if len(results) != 1 else ""} rendered with default theme</p>
  <div class="grid">
      {cards}
  </div>
</body>
</html>"""


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data_rows = json.loads(DATA_PATH.read_text())
    theme = load_theme()

    fixtures = sorted(FIXTURES_DIR.glob("*.yaml"))
    results: list[tuple[str, str]] = []
    skipped = 0
    errors = 0

    for yaml_path in fixtures:
        if yaml_path.name in SKIP:
            print(f"  SKIP: {yaml_path.name}")
            skipped += 1
            continue

        html_content = render_fixture(yaml_path, data_rows, theme)
        if html_content is None:
            errors += 1
            continue

        html_filename = yaml_path.name.replace(".yaml", ".html")
        (OUTPUT_DIR / html_filename).write_text(html_content)
        results.append((yaml_path.stem, html_filename))

    index_html = build_index(results)
    (OUTPUT_DIR / "index.html").write_text(index_html)

    print(f"\n  {len(results)} rendered, {skipped} skipped, {errors} errors")
    print(f"  Gallery: {OUTPUT_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
