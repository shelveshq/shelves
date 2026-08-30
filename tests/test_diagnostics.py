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

from shelves.diagnostics import (
    PositionedWarning,
    capture_structured_warnings,
    capture_warnings,
)
from shelves.schema.chart_schema import parse_chart
from shelves.studio.server import create_app
from tests.conftest import MODELS_DIR
from tests.conftest import LoopbackTestClient as TestClient


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


class TestPositionedWarning:
    """A PositionedWarning carries a `loc` (and `code`) from the emission site to
    the surface so warnings can be placed inline like errors (SHE-101)."""

    def test_str_is_the_bare_message(self):
        w = PositionedWarning("KPI cols ignored", loc=("kpi",), code="kpi_shelves_ignored")
        assert str(w) == "KPI cols ignored"
        assert w.loc == ("kpi",)
        assert w.code == "kpi_shelves_ignored"

    def test_loc_and_code_default_to_none(self):
        w = PositionedWarning("plain")
        assert w.loc is None
        assert w.code is None

    def test_structured_capture_records_loc_and_code(self):
        out: list[dict] = []
        with capture_structured_warnings(out):
            warnings.warn(
                PositionedWarning("tooltip disaggregates", loc=("tooltip", 0), code="tt"),
                stacklevel=2,
            )
        assert out == [{"msg": "tooltip disaggregates", "loc": ("tooltip", 0), "code": "tt"}]

    def test_structured_capture_plain_warning_has_null_loc(self):
        out: list[dict] = []
        with capture_structured_warnings(out):
            warnings.warn("just a string", UserWarning, stacklevel=2)
        assert out == [{"msg": "just a string", "loc": None, "code": None}]

    def test_structured_capture_prefix_is_prepended(self):
        out: list[dict] = []
        with capture_structured_warnings(out, prefix="Sheet 'x': "):
            warnings.warn("boom", UserWarning, stacklevel=2)
        assert out[0]["msg"] == "Sheet 'x': boom"


class TestTooltipWarningLoc:
    """collect_chart_fields tags the tooltip disaggregation warning with the loc
    of the offending tooltip entry (SHE-101)."""

    def _capture_fields(self, yaml_body: str) -> list[dict]:
        from shelves.data.fields import collect_chart_fields

        spec = parse_chart(yaml_body)
        out: list[dict] = []
        with capture_structured_warnings(out):
            collect_chart_fields(spec)
        return out

    def test_string_tooltip_entry_loc(self):
        out = self._capture_fields(
            "sheet: t\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\ntooltip: [region]\n"
        )
        assert len(out) == 1
        assert out[0]["loc"] == ("tooltip", 0)
        assert out[0]["code"] == "tooltip_disaggregation"

    def test_object_tooltip_entry_loc(self):
        out = self._capture_fields(
            "sheet: t\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
            "tooltip:\n  - field: region\n"
        )
        assert len(out) == 1
        assert out[0]["loc"] == ("tooltip", 0, "field")

    def test_referenced_tooltip_field_does_not_warn(self):
        out = self._capture_fields(
            "sheet: t\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\ntooltip: [country]\n"
        )
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
        assert any("ignored when kpi is present" in w["msg"] for w in data["warnings"])

    def test_clean_chart_has_no_warnings(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        assert data["warnings"] == []
