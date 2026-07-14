"""
Studio File CRUD Tests — SHE-42

POST /file (create, templated by configured dir), POST /file/rename,
DELETE /file. Every endpoint goes through resolve_safe, is restricted to
tree-visible extensions, and broadcasts a file_change directly so the tree
refreshes without waiting on the watcher.
"""

from __future__ import annotations

from pathlib import Path

from shelves import parse_chart
from shelves.models.loader import clear_model_cache, load_model
from shelves.studio.routes.files import (
    CHART_TEMPLATE,
    DASHBOARD_TEMPLATE,
    MODEL_TEMPLATE,
)
from shelves.studio.server import create_app
from tests.conftest import LoopbackTestClient as TestClient

_CHART_YAML = "sheet: test\n"


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "revenue.yaml").write_text(_CHART_YAML)
    (tmp_path / "dashboards").mkdir()
    (tmp_path / "models").mkdir()
    return tmp_path


# ─── Create ──────────────────────────────────────────────────────


class TestCreate:
    def test_create_chart_gets_chart_template(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "charts/new.yaml"})
        assert resp.status_code == 201
        assert resp.json() == {"ok": True, "path": "charts/new.yaml"}
        assert (project / "charts" / "new.yaml").read_text() == CHART_TEMPLATE
        # Structurally valid ChartSpec YAML; the placeholder model reference
        # is designed to produce a friendly compile marker, not a parse error.
        parse_chart(CHART_TEMPLATE)

    def test_create_dashboard_template_compiles(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "dashboards/new.yaml"})
        assert resp.status_code == 201
        assert (project / "dashboards" / "new.yaml").read_text() == DASHBOARD_TEMPLATE
        result = client.post("/compile-dashboard", content=DASHBOARD_TEMPLATE).json()
        assert result["errors"] == []
        assert result["html"]

    def test_create_model_template_loads(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "models/sales.yaml"})
        assert resp.status_code == 201
        content = (project / "models" / "sales.yaml").read_text()
        assert content == MODEL_TEMPLATE.format(stem="sales")
        assert content.startswith("model: sales\n")
        clear_model_cache()  # the loader caches by dir+name
        load_model("sales", models_dir=project / "models")

    def test_create_with_body_stores_body(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post(
            "/file", params={"path": "charts/copy.yaml"}, content="sheet: original\n"
        )
        assert resp.status_code == 201
        assert (project / "charts" / "copy.yaml").read_text() == "sheet: original\n"

    def test_create_makes_parent_dirs(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "charts/q3/deep/new.yaml"})
        assert resp.status_code == 201
        assert (project / "charts" / "q3" / "deep" / "new.yaml").read_text() == CHART_TEMPLATE

    def test_create_outside_groups_gets_empty_content(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "other/new.yaml"})
        assert resp.status_code == 201
        assert (project / "other" / "new.yaml").read_text() == ""

    def test_create_existing_conflicts(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "charts/revenue.yaml"})
        assert resp.status_code == 409
        assert resp.text == "File already exists"
        assert (project / "charts" / "revenue.yaml").read_text() == _CHART_YAML

    def test_create_traversal_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "../outside.yaml"})
        assert resp.status_code == 400
        assert not (tmp_path.parent / "outside.yaml").exists()

    def test_create_bad_extension_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "charts/notes.txt"})
        assert resp.status_code == 400
        assert resp.text == "Only .yaml, .yml, and .json files are allowed"
        assert not (project / "charts" / "notes.txt").exists()

    def test_create_missing_path_param(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        assert client.post("/file").status_code == 400

    def test_create_under_existing_file_rejected(self, tmp_path):
        # charts/revenue.yaml exists as a FILE — using it as a directory
        # component must be a clean 400, not an unhandled 500 (PR review).
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file", params={"path": "charts/revenue.yaml/child.yaml"})
        assert resp.status_code == 400
        assert resp.text == "A parent of the path is an existing file"
        assert (project / "charts" / "revenue.yaml").read_text() == _CHART_YAML


# ─── Rename ──────────────────────────────────────────────────────


class TestRename:
    def test_rename_moves_and_preserves_content(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post(
            "/file/rename",
            params={"path": "charts/revenue.yaml", "to": "charts/income.yaml"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "path": "charts/income.yaml"}
        assert not (project / "charts" / "revenue.yaml").exists()
        assert (project / "charts" / "income.yaml").read_text() == _CHART_YAML

    def test_rename_creates_target_parents(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post(
            "/file/rename",
            params={"path": "charts/revenue.yaml", "to": "charts/archive/revenue.yaml"},
        )
        assert resp.status_code == 200
        assert (project / "charts" / "archive" / "revenue.yaml").read_text() == _CHART_YAML

    def test_rename_missing_source_404(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post(
            "/file/rename", params={"path": "charts/ghost.yaml", "to": "charts/x.yaml"}
        )
        assert resp.status_code == 404
        assert resp.text == "File not found"

    def test_rename_target_exists_conflicts(self, tmp_path):
        project = _make_project(tmp_path)
        (project / "charts" / "other.yaml").write_text("sheet: other\n")
        client = TestClient(create_app(project_dir=project))
        resp = client.post(
            "/file/rename",
            params={"path": "charts/revenue.yaml", "to": "charts/other.yaml"},
        )
        assert resp.status_code == 409
        assert resp.text == "File already exists"
        assert (project / "charts" / "revenue.yaml").read_text() == _CHART_YAML
        assert (project / "charts" / "other.yaml").read_text() == "sheet: other\n"

    def test_rename_traversal_rejected_both_params(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file/rename", params={"path": "../a.yaml", "to": "charts/x.yaml"})
        assert resp.status_code == 400
        resp = client.post(
            "/file/rename", params={"path": "charts/revenue.yaml", "to": "../b.yaml"}
        )
        assert resp.status_code == 400
        assert (project / "charts" / "revenue.yaml").exists()

    def test_rename_missing_to_param(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file/rename", params={"path": "charts/revenue.yaml"})
        assert resp.status_code == 400
        assert resp.text == "Missing to parameter"

    def test_rename_bad_target_extension(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post(
            "/file/rename",
            params={"path": "charts/revenue.yaml", "to": "charts/revenue.txt"},
        )
        assert resp.status_code == 400
        assert resp.text == "Only .yaml, .yml, and .json files are allowed"

    def test_rename_target_under_existing_file_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        (project / "charts" / "other.yaml").write_text("sheet: other\n")
        client = TestClient(create_app(project_dir=project))
        resp = client.post(
            "/file/rename",
            params={"path": "charts/revenue.yaml", "to": "charts/other.yaml/x.yaml"},
        )
        assert resp.status_code == 400
        assert resp.text == "A parent of the path is an existing file"
        assert (project / "charts" / "revenue.yaml").read_text() == _CHART_YAML

    def test_rename_directory_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.post("/file/rename", params={"path": "charts", "to": "charts2.yaml"})
        assert resp.status_code == 400
        assert resp.text == "Not a file"


# ─── Delete ──────────────────────────────────────────────────────


class TestDelete:
    def test_delete_removes_file(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.delete("/file", params={"path": "charts/revenue.yaml"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert not (project / "charts" / "revenue.yaml").exists()

    def test_delete_missing_404(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.delete("/file", params={"path": "charts/ghost.yaml"})
        assert resp.status_code == 404
        assert resp.text == "File not found"

    def test_delete_directory_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.delete("/file", params={"path": "charts"})
        assert resp.status_code == 400
        assert resp.text == "Not a file"
        assert (project / "charts").is_dir()

    def test_delete_traversal_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.delete("/file", params={"path": "../../etc/hosts"})
        assert resp.status_code == 400

    def test_delete_bad_extension_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        (project / "README.md").write_text("# readme\n")
        client = TestClient(create_app(project_dir=project))
        resp = client.delete("/file", params={"path": "README.md"})
        assert resp.status_code == 400
        assert (project / "README.md").exists()


# ─── Broadcasts ──────────────────────────────────────────────────
# Direct broadcasts from the endpoints; the watcher (running under `with
# TestClient`) may append duplicates later — assert on the FIRST message(s)
# only, never on the absence of more.


class TestBroadcasts:
    def test_create_broadcasts_created(self, tmp_path):
        project = _make_project(tmp_path)
        app = create_app(project_dir=project)
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            client.post("/file", params={"path": "charts/new.yaml"})
            assert ws.receive_json() == {
                "type": "file_change",
                "event": "created",
                "path": "charts/new.yaml",
            }

    def test_rename_broadcasts_deleted_then_created(self, tmp_path):
        project = _make_project(tmp_path)
        app = create_app(project_dir=project)
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            client.post(
                "/file/rename",
                params={"path": "charts/revenue.yaml", "to": "charts/income.yaml"},
            )
            assert ws.receive_json() == {
                "type": "file_change",
                "event": "deleted",
                "path": "charts/revenue.yaml",
            }
            assert ws.receive_json() == {
                "type": "file_change",
                "event": "created",
                "path": "charts/income.yaml",
            }

    def test_delete_broadcasts_deleted(self, tmp_path):
        project = _make_project(tmp_path)
        app = create_app(project_dir=project)
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            client.delete("/file", params={"path": "charts/revenue.yaml"})
            assert ws.receive_json() == {
                "type": "file_change",
                "event": "deleted",
                "path": "charts/revenue.yaml",
            }
