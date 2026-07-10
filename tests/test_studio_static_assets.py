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
