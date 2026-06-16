"""
HTML Renderer

Produces a standalone HTML page that renders a Vega-Lite spec
using vegaEmbed from CDN.

Phase 1 rendering approach -- open in browser for visual verification.
Phase 6 replaces this with a web app component.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

# Canonical browser-side label renderer, shared with the studio pipeline.
# Read once at import; inlined into the standalone page so the JS lives in
# exactly one place (no f-string brace escaping, no copy to keep in sync).
PATCH_JS_PATH = Path(__file__).parent / "charter_patch.js"
CHARTER_PATCH_JS = PATCH_JS_PATH.read_text(encoding="utf-8")


def render_html(spec: dict, title: str | None = None) -> str:
    """Generate a standalone HTML page embedding a Vega-Lite spec."""
    spec_json = json.dumps(spec, indent=2).replace("</", r"<\/")
    page_title = title or spec.get("title", "Charter -- Chart Preview")
    page_title = html.escape(str(page_title), quote=True)

    head = f"""<!DOCTYPE html>
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
{CHARTER_PATCH_JS}
  </script>
  <script>
    const spec = {spec_json};
    vegaEmbed('#chart', spec, {{
      renderer: 'canvas',
      patch: charterPatch,
      actions: {{ export: true, source: true, compiled: false, editor: true }}
    }}).catch(console.error);
  </script>
</body>
</html>"""
    return head
