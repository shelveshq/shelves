"""
preview.js missing-renderer guard (SHE-77).

If the vega/vega-lite/vega-embed scripts fail to load (CDN blip, ad-blocker),
`window.vegaEmbed` is undefined and calling it used to surface as a bare
"TypeError: undefined is not an object" in the error overlay. The guard must
instead paint a named error card telling the user what failed and what to do.

The scenario runs inside the shared broadcast-guard harness
(tests/support/run_broadcast_guard.mjs), whose window stub never defines
vegaEmbed — exactly the failure mode under test.
"""

from __future__ import annotations

from tests.test_studio_broadcast_guard import run_scenarios


def test_missing_vega_embed_paints_error_overlay():
    out = run_scenarios()
    assert out["rendererGuardOverlayShown"] is True


def test_missing_vega_embed_message_names_cause_and_fix():
    html = run_scenarios()["rendererGuardHtml"]
    assert "Chart renderer failed to load" in html
    assert "ad-blocker" in html
    assert "reload" in html
