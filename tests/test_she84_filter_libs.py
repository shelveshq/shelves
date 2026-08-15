"""
SHE-84: filter widget libraries (noUiSlider, flatpickr, Tom Select) load via
pinned CDN + SRI, only on the interactive (Studio) path where a filter exists.
Exported HTML renders static values and needs no library.
"""

from shelves.schema.layout_schema import Canvas
from shelves.theme.merge import load_theme
from shelves.translator.layout import FILTER_LIB_CDN, wrap_html_page


def _wrap(*, interactive: bool, has_filters: bool) -> str:
    return wrap_html_page(
        dashboard_name="D",
        body_html="",
        chart_specs={},
        theme=load_theme(),
        canvas=Canvas(width=800, height=600),
        has_controls=True,
        has_filters=has_filters,
        interactive=interactive,
    )


# The inlined control_render.js mentions library names (flatpickr, …) in its
# feature-detect code, so assert on the CDN URL, which appears only in the tags.
_CDN = "cdn.jsdelivr.net/npm/"


class TestFilterLibEmission:
    def test_interactive_dashboard_with_filters_loads_libs(self):
        html = _wrap(interactive=True, has_filters=True)
        assert f"{_CDN}nouislider@15.8.1" in html
        assert f"{_CDN}flatpickr@4.6.13" in html
        assert f"{_CDN}tom-select@2.3.1" in html

    def test_libs_carry_sri_and_pinned_versions(self):
        html = _wrap(interactive=True, has_filters=True)
        for url, sri in FILTER_LIB_CDN:
            assert url in html
            assert f'integrity="{sri}"' in html

    def test_restyle_css_ships_with_libs_and_reads_tokens(self):
        html = _wrap(interactive=True, has_filters=True)
        # Library classes are repainted from the filter tokens (no hardcoded colors).
        assert ".noUi-connect{background:var(--shelves-filter-accent" in html
        assert ".ts-control" in html
        assert "var(--shelves-filter-text" in html
        # Gated: export never ships the restyle.
        assert ".noUi-connect" not in _wrap(interactive=False, has_filters=True)

    def test_export_never_loads_filter_libs(self):
        html = _wrap(interactive=False, has_filters=True)
        assert _CDN + "nouislider" not in html
        assert _CDN + "flatpickr" not in html
        assert _CDN + "tom-select" not in html

    def test_no_filters_no_libs_even_interactive(self):
        html = _wrap(interactive=True, has_filters=False)
        assert _CDN + "nouislider" not in html
        assert _CDN + "flatpickr" not in html
        assert _CDN + "tom-select" not in html
