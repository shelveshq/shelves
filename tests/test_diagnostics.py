"""
Structured diagnostics tests.

capture_warnings bridges Python's warnings machinery to the structured
`warnings: [...]` lists that Studio responses return — emission sites keep
using warnings.warn, capture happens at the surface boundary.
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from shelves.diagnostics import capture_warnings
from shelves.studio.server import create_app
from tests.conftest import MODELS_DIR


class TestCaptureWarnings:
    def test_records_messages_into_list(self):
        out: list[str] = []
        with capture_warnings(out):
            warnings.warn("hello", UserWarning, stacklevel=2)
        assert out == ["hello"]

    def test_prefix_is_prepended(self):
        out: list[str] = []
        with capture_warnings(out, prefix="Sheet 'kpi': "):
            warnings.warn("cols ignored", UserWarning, stacklevel=2)
        assert out == ["Sheet 'kpi': cols ignored"]

    def test_records_survive_an_exception_in_the_block(self):
        out: list[str] = []
        with pytest.raises(RuntimeError), capture_warnings(out):
            warnings.warn("emitted before the crash", UserWarning, stacklevel=2)
            raise RuntimeError("boom")
        assert out == ["emitted before the crash"]

    def test_no_warnings_appends_nothing(self):
        out: list[str] = []
        with capture_warnings(out):
            pass
        assert out == []


class TestStudioWarningCapture:
    """Python warnings emitted during compile must reach the Studio response —
    warnings.warn alone is stderr-only and invisible in the browser."""

    def _make_client(self, tmp_path: Path) -> TestClient:
        models = tmp_path / "models"
        models.mkdir()
        shutil.copy(MODELS_DIR / "orders.yaml", models / "orders.yaml")
        app = create_app(project_dir=tmp_path, models_dir=models)
        return TestClient(app, raise_server_exceptions=False)

    def test_kpi_shelf_conflict_warning_in_compile_response(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        yaml_body = (
            "sheet: Revenue KPI\n"
            "data: orders\n"
            "cols: country\n"  # ignored when kpi is present → validator warns
            "kpi:\n"
            "  value: revenue\n"
            '  format: "$,.0f"\n'
        )
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        assert data["vega_lite_spec"] is not None
        assert any("ignored when kpi is present" in w for w in data["warnings"])

    def test_clean_chart_has_no_warnings(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        assert data["warnings"] == []
