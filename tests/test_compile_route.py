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

    def test_non_pydantic_error_structured(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: [\ninvalid yaml"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["vega_lite_spec"] is None
        assert len(data["errors"]) >= 1
        err = data["errors"][0]
        assert isinstance(err, dict)
        assert err["source"] == "yaml"

    def test_empty_body(self, tmp_path: Path):
        client = _make_client(tmp_path)
        resp = client.post("/compile", content="")
        data = resp.json()

        assert data == {
            "vega_lite_spec": None,
            "errors": ["Empty YAML body"],
            "warnings": [],
        }


class TestLabelPatchAsset:
    """The studio must serve the same label-patch JS the CLI renderer inlines."""

    def test_serves_canonical_patch_js(self, tmp_path: Path):
        from shelves.render.to_html import LABEL_PATCH_JS

        client = _make_client(tmp_path)
        resp = client.get("/label-patch.js")

        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]
        # Byte-identical to the source the standalone renderer inlines.
        assert resp.text == LABEL_PATCH_JS
        assert "window.labelPatch" in resp.text

    def test_index_loads_patch_and_preview_uses_it(self):
        from pathlib import Path as _Path

        static = _Path("shelves/studio/static")
        index_html = (static / "index.html").read_text()
        preview_js = (static / "js" / "preview.js").read_text()

        assert "/label-patch.js" in index_html
        assert "patch: window.labelPatch" in preview_js


class TestFriendlyErrors:
    """Tests for friendly error messages and source tagging (KAN-266-B)."""

    def test_dsl_error_friendly_msg_literal(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: 12345\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        errs = [e for e in data["errors"] if e["type"] == "literal_error"]
        assert len(errs) >= 1
        err = errs[0]
        assert err["source"] == "dsl"
        assert err["friendly_msg"].startswith("Invalid value")
        assert "bar" in err["friendly_msg"]

    def test_dsl_error_friendly_msg_missing(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\ncols: week\nrows: revenue\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        err = data["errors"][0]
        assert err["source"] == "dsl"
        assert err["type"] == "missing"
        assert err["friendly_msg"] == "Required field"

    def test_dsl_error_friendly_msg_model_type(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: 12345\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        errs = [e for e in data["errors"] if e["type"] == "model_type"]
        assert len(errs) >= 1
        err = errs[0]
        assert err["source"] == "dsl"
        assert "Expected" in err["friendly_msg"]
        assert "MarkObject" not in err["friendly_msg"]

    def test_dsl_error_clean_loc(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: week\nrows: revenue\nmarks: 12345\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        for err in data["errors"]:
            assert "display_loc" in err
            for seg in err["display_loc"]:
                if isinstance(seg, str):
                    assert not seg.startswith("literal[")
                    assert not (seg[0:1].isupper() and seg.isidentifier())
                    assert not seg.startswith("list[")

        literal_err = next(e for e in data["errors"] if e["type"] == "literal_error")
        assert literal_err["display_loc"] == ["marks"]

    def test_yaml_error_structured(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: [\ninvalid yaml"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert len(data["errors"]) == 1
        err = data["errors"][0]
        assert isinstance(err, dict)
        assert err["source"] == "yaml"
        assert err["type"] == "yaml_syntax"
        assert err["line"] == 2
        assert err["col"] is not None
        assert "friendly_msg" in err
        assert "msg" in err

    def test_yaml_error_friendly_msg(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: [\ninvalid yaml"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        err = data["errors"][0]
        assert "expected" in err["friendly_msg"].lower() or "Expected" in err["friendly_msg"]
        assert "\n" not in err["friendly_msg"]

    def test_yaml_mapping_error(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\n  bad: indent\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert len(data["errors"]) >= 1
        err = data["errors"][0]
        assert isinstance(err, dict)
        assert err["source"] == "yaml"
        assert err["line"] == 2
        assert "friendly_msg" in err

    def test_schema_requires_sheet_and_data(self, tmp_path: Path):
        """Pin the premise behind Studio's schema routing (SHE-48).

        editor.js attaches the ChartSpec schema only to chart buffers because
        its required set would flag every dashboard/model YAML. If the
        required set changes, that routing rationale changed — revisit it.
        """
        client = _make_client(tmp_path)
        resp = client.get("/schema")
        assert resp.status_code == 200
        schema = resp.json()
        assert set(schema["required"]) == {"sheet", "data"}

    def test_runtime_error_structured(self, tmp_path: Path):
        models = tmp_path / "models"
        models.mkdir(exist_ok=True)
        app = create_app(project_dir=tmp_path, models_dir=models)
        client = TestClient(app, raise_server_exceptions=False)
        yaml_body = "sheet: test\ndata: nonexistent_model\ncols: x\nrows: y\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["vega_lite_spec"] is None
        assert len(data["errors"]) >= 1
        err = data["errors"][0]
        assert isinstance(err, dict)
        assert err["source"] == "runtime"
        assert err["type"] == "runtime_error"
        assert err["friendly_msg"] == err["msg"]
        assert err["line"] is None
