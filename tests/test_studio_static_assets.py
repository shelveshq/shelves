"""
Static-asset hygiene for Shelves Studio (PR #59 review).

shelves-tokens.css is a verbatim mirror of the design-system source of truth
and carries the Google Fonts @import; index.html must not load the same
stylesheet a second time via <link> (preconnect hints are fine and expected).
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parent.parent / "shelves" / "studio" / "static"

FONT_CSS_URL = "fonts.googleapis.com/css2"


def test_google_fonts_css_loaded_exactly_once():
    index = (STATIC / "index.html").read_text()
    tokens = (STATIC / "shelves-tokens.css").read_text()
    total = index.count(FONT_CSS_URL) + tokens.count(FONT_CSS_URL)
    assert total == 1, (
        "Google Fonts CSS must be loaded exactly once — the @import in "
        "shelves-tokens.css (the DS mirror) is the source of truth; "
        "index.html must not add a duplicate <link>."
    )


def test_tokens_mirror_keeps_font_import():
    tokens = (STATIC / "shelves-tokens.css").read_text()
    assert FONT_CSS_URL in tokens, (
        "shelves-tokens.css must keep its @import — it is a verbatim mirror "
        "of docs/design-system/colors_and_type.css (re-sync = re-copy)."
    )


def test_index_keeps_font_preconnects():
    index = (STATIC / "index.html").read_text()
    assert 'rel="preconnect" href="https://fonts.googleapis.com"' in index
    assert 'rel="preconnect" href="https://fonts.gstatic.com"' in index


# ─── Vendored render libs (SHE-77) ───────────────────────────────────────────
# Studio must never load vega/vega-lite/vega-embed from a CDN at runtime — a
# jsDelivr edge 400 and a content blocker each broke every chart in one week.
# The pinned UMD builds are committed under static/vendor/ and served
# same-origin; VEGA_LIB_FILES in shelves/render/to_html.py is the canon.


def test_vendored_vega_libs_present_and_plausible():
    from shelves.render.to_html import VEGA_LIB_FILES

    for name in VEGA_LIB_FILES:
        path = STATIC / "vendor" / name
        assert path.is_file(), f"missing vendored lib: {name}"
        # A CDN error page cached into the file would be tiny; the real
        # bundles are 60KB–520KB.
        assert path.stat().st_size > 50_000, f"{name} looks truncated/corrupt"


def test_index_loads_vendored_libs_not_cdn():
    from shelves.render.to_html import VEGA_LIB_FILES

    index = (STATIC / "index.html").read_text()
    for name in VEGA_LIB_FILES:
        assert f'src="/static/vendor/{name}"' in index
    assert "jsdelivr.net/npm/vega" not in index
