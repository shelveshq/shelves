"""
Studio dashboard route tests — KAN-298

The Studio dashboard preview must render the dashboard on its declared canvas
size. The backend contract for that is: the /compile-dashboard pipeline returns
the declared (or default) canvas dimensions so the frontend can pin the iframe.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from shelves.studio.routes.dashboard import run_dashboard_pipeline


def _run(coro):
    return asyncio.run(coro)


class TestCompileDashboardCanvas:
    def test_compile_dashboard_returns_declared_canvas(self, tmp_path: Path):
        yaml_body = (
            'dashboard: "Canvas Test"\n'
            "canvas:\n"
            "  width: 1024\n"
            "  height: 768\n"
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            '    - text: "Hello"\n'
            "      preset: title\n"
        )

        async def _test():
            return await run_dashboard_pipeline(
                yaml_body,
                project_dir=tmp_path,
                charts_dir=tmp_path,
                theme_path=None,
                models_dir=None,
            )

        result = _run(_test())
        assert result["html"] is not None
        assert result["canvas"] == {"width": 1024, "height": 768}

    def test_compile_dashboard_default_canvas(self, tmp_path: Path):
        yaml_body = (
            'dashboard: "Default Canvas"\n'
            "root:\n"
            "  orientation: vertical\n"
            "  contains:\n"
            '    - text: "Hi"\n'
            "      preset: title\n"
        )

        async def _test():
            return await run_dashboard_pipeline(
                yaml_body,
                project_dir=tmp_path,
                charts_dir=tmp_path,
                theme_path=None,
                models_dir=None,
            )

        result = _run(_test())
        assert result["canvas"] == {"width": 1440, "height": 900}
