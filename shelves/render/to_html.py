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
# The JS lives in exactly one file (no f-string brace escaping, no copy to keep
# in sync). It is read fresh on every render so a long-running dev/studio server
# picks up edits without a restart.
PATCH_JS_PATH = Path(__file__).parent / "charter_patch.js"


def load_charter_patch_js() -> str:
    """Read the canonical label-patch JS from disk (fresh, no import-time cache)."""
    return PATCH_JS_PATH.read_text(encoding="utf-8")


# Snapshot for tests/back-compat; render paths call load_charter_patch_js().
CHARTER_PATCH_JS = load_charter_patch_js()


def render_html(spec: dict, title: str | None = None) -> str:
    """Generate a standalone HTML page embedding a Vega-Lite spec."""
    spec_json = json.dumps(spec, indent=2).replace("</", r"<\/")
    page_title = title or spec.get("title", "Charter -- Chart Preview")
    page_title = html.escape(str(page_title), quote=True)
    patch_js = load_charter_patch_js()

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
{patch_js}
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
