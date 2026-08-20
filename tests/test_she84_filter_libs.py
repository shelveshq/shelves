"""
SHE-84: filter widget libraries (noUiSlider, flatpickr, Tom Select) load only on
the interactive (Studio) path where a filter exists. Exported HTML renders
static values and needs no library.

Studio serves the vendored copies same-origin (`vega_src_base="/static/vendor"`,
the SHE-77 path that also vendors Vega); the pinned CDN + SRI URLs are the
fallback for any surface that emits these without a vendored base.
"""

from shelves.schema.layout_schema import Canvas
from shelves.theme.merge import load_theme
from shelves.translator.layout import FILTER_LIB_CDN, wrap_html_page


def _wrap(*, interactive: bool, has_filters: bool, vega_src_base: str | None = None) -> str:
    return wrap_html_page(
        dashboard_name="D",
        body_html="",
        chart_specs={},
        theme=load_theme(),
        canvas=Canvas(width=800, height=600),
        has_controls=True,
        has_filters=has_filters,
        interactive=interactive,
        vega_src_base=vega_src_base,
    )


# The inlined control_render.js mentions library names (flatpickr, …) in its
# feature-detect code, so assert on the CDN URL or vendored filename, which
# appear only in the tags.
_CDN = "cdn.jsdelivr.net/npm/"
_VENDOR = "/static/vendor"


class TestFilterLibEmission:
    def test_interactive_dashboard_with_filters_loads_libs(self):
        # No src_base → the CDN fallback tags are emitted.
        html = _wrap(interactive=True, has_filters=True)
        assert f"{_CDN}nouislider@15.8.1" in html
        assert f"{_CDN}flatpickr@4.6.13" in html
        assert f"{_CDN}tom-select@2.3.1" in html

    def test_fallback_libs_carry_sri_and_pinned_versions(self):
        # Without a vendored base every lib loads from the pinned CDN URL + SRI.
        html = _wrap(interactive=True, has_filters=True)
        for url, sri, _fname in FILTER_LIB_CDN:
            assert url in html
            assert f'integrity="{sri}"' in html

    def test_studio_serves_vendored_copies_same_origin(self):
        # Studio's src_base → same-origin vendored filenames, no CDN, no SRI.
        html = _wrap(interactive=True, has_filters=True, vega_src_base=_VENDOR)
        for _url, sri, fname in FILTER_LIB_CDN:
            assert f"{_VENDOR}/{fname}" in html
            assert f'integrity="{sri}"' not in html
        assert _CDN not in html

    def test_restyle_css_ships_with_libs_and_reads_tokens(self):
        html = _wrap(interactive=True, has_filters=True)
        # Library classes are repainted from the filter tokens (no hardcoded colors).
        assert ".noUi-connect{background:var(--shelves-filter-accent" in html
        assert ".ts-control" in html
        assert "var(--shelves-filter-text" in html
        # SHE-103: Tom Select controls are height-matched to the native inputs.
        assert "min-height:var(--shelves-filter-height" in html
        # Gated: export never ships the restyle.
        assert ".noUi-connect" not in _wrap(interactive=False, has_filters=True)

    def test_export_never_loads_filter_libs(self):
        # control_render.js (inlined) names the libs in its feature-detect, so
        # assert on the tag-only tokens: no CDN URL and no vendored <script>/<link>.
        html = _wrap(interactive=False, has_filters=True, vega_src_base=_VENDOR)
        for url, _sri, fname in FILTER_LIB_CDN:
            assert url not in html
            assert f"{_VENDOR}/{fname}" not in html

    def test_no_filters_no_libs_even_interactive(self):
        html = _wrap(interactive=True, has_filters=False, vega_src_base=_VENDOR)
        for url, _sri, fname in FILTER_LIB_CDN:
            assert url not in html
            assert f"{_VENDOR}/{fname}" not in html
