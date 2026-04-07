"""
HTML Renderer

Produces a standalone HTML page that renders a Vega-Lite spec
using vegaEmbed from CDN.

Phase 1 rendering approach -- open in browser for visual verification.
Phase 6 replaces this with a web app component.
"""

from __future__ import annotations

import json
import html


def render_html(spec: dict, title: str | None = None) -> str:
    """Generate a standalone HTML page embedding a Vega-Lite spec."""
    spec_json = json.dumps(spec, indent=2)
    page_title = title or spec.get("title", "Charter -- Chart Preview")
    page_title = html.escape(str(page_title), quote=True)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{page_title}</title>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@6"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <style>
    body {{
      margin: 0; padding: 24px;
      font-family: Inter, system-ui, sans-serif;
      background: #f5f5f5;
    }}
    #chart {{
      background: #ffffff; border-radius: 8px;
      padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
  </style>
</head>
<body>
  <div id="chart"></div>
  <script>
    const spec = {spec_json};
    vegaEmbed('#chart', spec, {{
      renderer: 'canvas',
      actions: {{ export: true, source: true, compiled: false, editor: true }}
    }}).catch(console.error);
  </script>
</body>
</html>"""
