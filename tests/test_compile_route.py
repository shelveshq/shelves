"""Tests for structured validation errors from the /compile endpoint (KAN-263)."""

from __future__ import annotations

import shutil
from pathlib import Path

from starlette.testclient import TestClient

from shelves.studio.server import create_app
from tests.conftest import MODELS_DIR


def _make_client(tmp_path: Path) -> TestClient:
    """Create a TestClient with a minimal Studio app pointing at tmp_path."""
    models = tmp_path / "models"
    models.mkdir()
    shutil.copy(MODELS_DIR / "orders.yaml", models / "orders.yaml")
    app = create_app(project_dir=tmp_path, models_dir=models)
    return TestClient(app, raise_server_exceptions=False)


class TestCompileRoute:
    def test_pydantic_error_structured(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: 12345\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["vega_lite_spec"] is None
        assert len(data["errors"]) >= 2
        for err in data["errors"]:
            assert isinstance(err, dict)
            assert "loc" in err
            assert "msg" in err
            assert "type" in err
            assert "line" in err
            assert "col" in err

        err0 = data["errors"][0]
        assert err0["loc"][0] == "marks"
        assert err0["type"] == "literal_error"
        assert err0["line"] == 5
        assert err0["col"] == 1

    def test_successful_compile(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        assert data["vega_lite_spec"] is not None

    def test_missing_required_fields(self, tmp_path: Path):
        client = _make_client(tmp_path)
        # Must include "sheet" to pass the pre-check; "data" is missing
        yaml_body = "sheet: test\ncols: week\nrows: revenue\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["vega_lite_spec"] is None
        assert len(data["errors"]) >= 1
        err0 = data["errors"][0]
        assert isinstance(err0, dict)
        assert err0["loc"] == ["data"]
        assert err0["type"] == "missing"
        assert err0["line"] is None
        assert err0["col"] is None

    def test_nested_error_line_col(self, tmp_path: Path):
        client = _make_client(tmp_path)
        # marks as a nested object with an invalid type triggers a Pydantic error
        # at loc ("marks", "MarkObject", "type") with a resolvable line/col
        yaml_body = (
            "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks:\n  type: invalid_mark\n"
        )
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["vega_lite_spec"] is None
        assert len(data["errors"]) >= 1
        # Find the nested MarkObject error
        nested = [e for e in data["errors"] if isinstance(e, dict) and len(e["loc"]) >= 3]
        assert len(nested) >= 1
        err = nested[0]
        assert err["loc"] == ["marks", "MarkObject", "type"]
        assert err["line"] == 6
        assert err["col"] == 3

    def test_non_pydantic_error_plain_string(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: [\ninvalid yaml"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["vega_lite_spec"] is None
        assert len(data["errors"]) >= 1
        assert isinstance(data["errors"][0], str)

    def test_empty_body(self, tmp_path: Path):
        client = _make_client(tmp_path)
        resp = client.post("/compile", content="")
        data = resp.json()

        assert data == {
            "vega_lite_spec": None,
            "errors": ["Empty YAML body"],
            "warnings": [],
        }
