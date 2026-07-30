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
LABEL_PATCH_JS_PATH = Path(__file__).parent / "label_patch.js"

# Canonical browser-side compound-spec sizer (window.compoundFit), shared with the
# dashboard render path the same way label_patch.js is. Read fresh per render.
COMPOUND_FIT_JS_PATH = Path(__file__).parent / "compound_fit.js"

# Canonical browser-side legend renderer (window.legendRender), shared like
# label_patch.js / compound_fit.js. Read fresh per render.
LEGEND_RENDER_JS_PATH = Path(__file__).parent / "legend_render.js"

# Canonical browser-side control renderer (window.controlRender), shared like
# legend_render.js. Read fresh per render.
CONTROL_RENDER_JS_PATH = Path(__file__).parent / "control_render.js"


def load_label_patch_js() -> str:
    """Read the canonical label-patch JS from disk (fresh, no import-time cache)."""
    return LABEL_PATCH_JS_PATH.read_text(encoding="utf-8")


def load_compound_fit_js() -> str:
    """Read the canonical compound-fit JS from disk (fresh, no import-time cache)."""
    return COMPOUND_FIT_JS_PATH.read_text(encoding="utf-8")


def load_legend_render_js() -> str:
    """Read the canonical legend-render JS from disk (fresh, no import-time cache)."""
    return LEGEND_RENDER_JS_PATH.read_text(encoding="utf-8")


def load_control_render_js() -> str:
    """Read the canonical control-render JS from disk (fresh, no import-time cache)."""
    return CONTROL_RENDER_JS_PATH.read_text(encoding="utf-8")


# Snapshot for tests/back-compat; render paths call load_label_patch_js().
LABEL_PATCH_JS = load_label_patch_js()


# ─── Browser render libs (vega / vega-lite / vega-embed) ────────────────────
# Single source of truth for the three libs every render surface loads.
# Studio serves the vendored copies (shelves/studio/static/vendor/) same-origin
# so a CDN blip or content blocker can't break the editor (SHE-77); standalone
# CLI HTML falls back to the pinned CDN URLs — exact versions with explicit
# file paths, because bare `@major` URLs hit jsDelivr's default-file resolver,
# which has served cached 400s that nosniff then refuses to execute.
# The vendored filenames must stay in lockstep with these versions.
VEGA_LIB_FILES: tuple[str, ...] = (
    "vega-5.33.1.min.js",
    "vega-lite-6.4.3.min.js",
    "vega-embed-6.29.0.min.js",
)
VEGA_LIB_CDN_URLS: tuple[str, ...] = (
    "https://cdn.jsdelivr.net/npm/vega@5.33.1/build/vega.min.js",
    "https://cdn.jsdelivr.net/npm/vega-lite@6.4.3/build/vega-lite.min.js",
    "https://cdn.jsdelivr.net/npm/vega-embed@6.29.0/build/vega-embed.min.js",
)


def vega_script_tags(src_base: str | None = None) -> str:
    """`<script>` tags for the render libs — vendored under `src_base`, else CDN."""
    srcs = [f"{src_base}/{f}" for f in VEGA_LIB_FILES] if src_base else list(VEGA_LIB_CDN_URLS)
    return "\n".join(f'  <script src="{s}"></script>' for s in srcs)


def render_html(spec: dict, title: str | None = None) -> str:
    """Generate a standalone HTML page embedding a Vega-Lite spec."""
    spec_json = json.dumps(spec, indent=2).replace("</", r"<\/")
    page_title = title or spec.get("title", "Shelves -- Chart Preview")
    page_title = html.escape(str(page_title), quote=True)
    patch_js = load_label_patch_js()

    head = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{page_title}</title>
{vega_script_tags()}
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
      patch: labelPatch,
      actions: {{ export: true, source: true, compiled: false, editor: true }}
    }}).catch(console.error);
  </script>
</body>
</html>"""
    return head
