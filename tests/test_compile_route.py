"""Tests for structured validation errors from the /compile endpoint (KAN-263)."""

from __future__ import annotations

import shutil
from pathlib import Path

from shelves.studio.server import create_app
from tests.conftest import DATA_DIR, MODELS_DIR, YAML_DIR
from tests.conftest import LoopbackTestClient as TestClient


def _make_client(tmp_path: Path) -> TestClient:
    """Create a TestClient with a minimal Studio app pointing at tmp_path."""
    models = tmp_path / "models"
    models.mkdir()
    shutil.copy(MODELS_DIR / "orders.yaml", models / "orders.yaml")
    # The orders model's inline source is data/orders.json relative to the
    # project dir — copy it so compiles resolve rows (SHE-43 Data view).
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(DATA_DIR / "orders.json", data / "orders.json")
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
            "model": None,
        }


class TestCompileModelKey:
    """The compile payload names the chart's model so the Data view can label
    the resolved-rows table (SHE-43)."""

    def test_success_response_includes_model(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        assert data["model"] == "orders"
        assert len(data["vega_lite_spec"]["data"]["values"]) == 12

    def test_error_response_model_is_null(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = "sheet: test\nmarks: 12345\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["vega_lite_spec"] is None
        assert len(data["errors"]) >= 1
        assert data["model"] is None

    def test_skipped_resolution_still_reports_model(self, tmp_path: Path):
        """A successful compile whose data binding is skipped keeps the model
        name — only data resolution failed, not the compile."""
        models = tmp_path / "models"
        models.mkdir()
        shutil.copy(MODELS_DIR / "orders.yaml", models / "orders.yaml")
        # No data/orders.json: the inline source is a silent no-op, so the
        # spec compiles with no data.values and model stays set.
        app = create_app(project_dir=tmp_path, models_dir=models)
        client = TestClient(app, raise_server_exceptions=False)
        yaml_body = "sheet: test\ndata: orders\ncols: country\nrows: revenue\nmarks: bar\n"
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        assert data["model"] == "orders"
        assert "data" not in data["vega_lite_spec"] or "values" not in data["vega_lite_spec"].get(
            "data", {}
        )


class TestCompileWarnings:
    """Compile warnings are structured objects with line/col like errors, so
    Studio can place them inline at the offending field (SHE-101)."""

    def _file_client(self, tmp_path: Path) -> TestClient:
        """A client with a file-backed (DuckDB) model so field collection runs —
        the tooltip disaggregation warning only fires on the adapter path."""
        models = tmp_path / "models"
        models.mkdir()
        shutil.copy(MODELS_DIR / "duckdb_orders.yaml", models / "duckdb_orders.yaml")
        data = tmp_path / "data"
        data.mkdir()
        shutil.copy(DATA_DIR / "orders.csv", data / "orders.csv")
        app = create_app(project_dir=tmp_path, models_dir=models)
        return TestClient(app, raise_server_exceptions=False)

    def test_kpi_warning_is_positioned(self, tmp_path: Path):
        client = _make_client(tmp_path)
        yaml_body = (
            "sheet: Revenue KPI\ndata: orders\ncols: country\n"
            'kpi:\n  value: revenue\n  format: "$,.0f"\n'
        )
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        assert len(data["warnings"]) == 1
        warn = data["warnings"][0]
        assert isinstance(warn, dict)
        assert warn["source"] == "warning"
        assert warn["code"] == "kpi_shelves_ignored"
        assert "ignored when kpi is present" in warn["msg"]
        # Placed at the `kpi:` key (key position, like errors), not a subfield.
        assert warn["line"] == 4
        assert warn["col"] == 1

    def test_tooltip_warning_is_positioned(self, tmp_path: Path):
        client = self._file_client(tmp_path)
        yaml_body = (Path(YAML_DIR) / "tooltip_disaggregation.yaml").read_text()
        resp = client.post("/compile", content=yaml_body)
        data = resp.json()

        assert data["errors"] == []
        warns = [w for w in data["warnings"] if w["code"] == "tooltip_disaggregation"]
        assert len(warns) == 1
        warn = warns[0]
        assert warn["source"] == "warning"
        assert warn["line"] == 7
        assert warn["col"] == 5
        assert warn["loc"] == ["tooltip", 0]

    def test_locless_warning_has_null_position(self):
        """A warning the compile route appends directly (no loc) resolves to a
        null line/col — editor.js falls back to the top of the file."""
        from shelves.studio.routes.compile import _format_warnings

        out = _format_warnings(
            [{"msg": "Data resolution skipped: boom", "loc": None, "code": None}],
            "sheet: t\n",
        )
        assert out == [
            {
                "loc": [],
                "display_loc": [],
                "msg": "Data resolution skipped: boom",
                "code": "warning",
                "source": "warning",
                "line": None,
                "col": None,
            }
        ]

    def test_unresolvable_loc_falls_back_to_null(self):
        """A loc pointing at a key absent from the parsed document resolves to
        null rather than raising."""
        from shelves.studio.routes.compile import _format_warnings

        out = _format_warnings(
            [{"msg": "gone", "loc": ("nonexistent",), "code": "x"}],
            "sheet: t\ndata: orders\n",
        )
        assert out[0]["line"] is None
        assert out[0]["col"] is None
        assert out[0]["code"] == "x"


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


class TestIndexSidebarToggle:
    """A collapsed sidebar must keep a reopen affordance: the narrow rail
    strip that stands in for it and restores the full width (SHE-41)."""

    def test_index_has_sidebar_rail(self, tmp_path: Path):
        client = _make_client(tmp_path)
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'id="sidebar-rail"' in resp.text


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
