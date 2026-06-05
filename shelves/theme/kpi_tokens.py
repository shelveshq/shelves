"""KPI Theme Token Accessor

Extracts the ``kpi`` token dict from a ThemeSpec.  Kept in the theme package so
the translator never imports theme internals directly — ``compile_kpi`` consumes
the returned dict via dependency injection.
"""

from __future__ import annotations

from typing import Any

from shelves.theme.merge import load_theme
from shelves.theme.theme_schema import ThemeSpec


def load_kpi_tokens(theme: ThemeSpec | None = None) -> dict[str, Any]:
    """Return the ``kpi`` token dict from a theme.

    When *theme* is ``None`` the built-in default theme is loaded.
    """
    if theme is None:
        theme = load_theme()
    return theme.chart.kpi
