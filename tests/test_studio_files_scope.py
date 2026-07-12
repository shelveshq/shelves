"""
Studio File-Tree Scoping Tests — SHE-39

GET /project must return typed top-level groups built from the configured
charts/dashboards/models/assets dirs instead of walking the whole project,
so .venv/, docs/, tests/ never clutter the explorer. GET/PUT /file stay
relative to project_dir (resolve_safe untouched).
"""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from shelves.studio.server import create_app

_CHART_YAML = "sheet: test\n"


def _make_default_project(tmp_path: Path) -> Path:
    """Default-dirs layout from the SHE-39 plan."""
    (tmp_path / "charts" / "sub").mkdir(parents=True)
    (tmp_path / "charts" / "revenue.yaml").write_text(_CHART_YAML)
    (tmp_path / "charts" / "sub" / "orders.yaml").write_text(_CHART_YAML)
    (tmp_path / "dashboards").mkdir()
    (tmp_path / "dashboards" / "exec.yaml").write_text(_CHART_YAML)
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "sales.yaml").write_text(_CHART_YAML)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.yaml").write_text(_CHART_YAML)  # must NOT appear
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "x.yaml").write_text(_CHART_YAML)  # must NOT appear
    (tmp_path / "assets").mkdir()  # empty → omitted
    return tmp_path


class TestProjectTreeScope:
    def test_project_tree_scoped_to_default_dirs(self, tmp_path):
        project = _make_default_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.get("/project")
        assert resp.status_code == 200
        assert resp.json() == [
            {
                "name": "charts",
                "type": "dir",
                "path": "charts",
                "group": "charts",
                "children": [
                    {
                        "name": "sub",
                        "type": "dir",
                        "path": "charts/sub",
                        "children": [
                            {
                                "name": "orders.yaml",
                                "type": "file",
                                "path": "charts/sub/orders.yaml",
                            }
                        ],
                    },
                    {"name": "revenue.yaml", "type": "file", "path": "charts/revenue.yaml"},
                ],
            },
            {
                "name": "dashboards",
                "type": "dir",
                "path": "dashboards",
                "group": "dashboards",
                "children": [{"name": "exec.yaml", "type": "file", "path": "dashboards/exec.yaml"}],
            },
            {
                "name": "models",
                "type": "dir",
                "path": "models",
                "group": "models",
                "children": [{"name": "sales.yaml", "type": "file", "path": "models/sales.yaml"}],
            },
        ]

    def test_project_tree_custom_dirs(self, tmp_path):
        """Custom dirs: name carries the folder name, group carries the ROLE."""
        (tmp_path / "viz").mkdir()
        (tmp_path / "viz" / "a.yaml").write_text(_CHART_YAML)
        (tmp_path / "semantics").mkdir()
        (tmp_path / "semantics" / "m.yaml").write_text(_CHART_YAML)
        app = create_app(
            project_dir=tmp_path,
            charts_dir=tmp_path / "viz",
            models_dir=tmp_path / "semantics",
        )
        client = TestClient(app)
        tree = client.get("/project").json()
        assert [(e["name"], e["group"]) for e in tree] == [
            ("viz", "charts"),
            ("semantics", "models"),
        ]
        assert tree[0]["path"] == "viz"
        assert tree[0]["children"] == [{"name": "a.yaml", "type": "file", "path": "viz/a.yaml"}]

    def test_missing_configured_dir_is_omitted(self, tmp_path):
        """models/ doesn't exist → group omitted, no error."""
        (tmp_path / "charts").mkdir()
        (tmp_path / "charts" / "a.yaml").write_text(_CHART_YAML)
        client = TestClient(create_app(project_dir=tmp_path))
        tree = client.get("/project").json()
        assert [e["group"] for e in tree] == ["charts"]

    def test_empty_configured_dir_is_omitted(self, tmp_path):
        """assets/ exists but has no matching files → group omitted."""
        (tmp_path / "charts").mkdir()
        (tmp_path / "charts" / "a.yaml").write_text(_CHART_YAML)
        (tmp_path / "assets").mkdir()
        client = TestClient(create_app(project_dir=tmp_path))
        tree = client.get("/project").json()
        assert [e["group"] for e in tree] == ["charts"]

    def test_dir_outside_project_is_omitted_with_warning(self, tmp_path, caplog):
        """A configured dir outside project_dir is skipped with a warning."""
        import logging

        project = tmp_path / "project"
        (project / "charts").mkdir(parents=True)
        (project / "charts" / "a.yaml").write_text(_CHART_YAML)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "logo.json").write_text("{}")

        app = create_app(project_dir=project, assets_dir=outside)
        client = TestClient(app)
        with caplog.at_level(logging.WARNING, logger="shelves.studio.files"):
            tree = client.get("/project").json()
        assert [e["group"] for e in tree] == ["charts"]
        assert any("elsewhere" in r.message for r in caplog.records), (
            f"Expected a warning naming the outside dir; got {[r.message for r in caplog.records]}"
        )

    def test_duplicate_dirs_deduped_first_role_wins(self, tmp_path):
        """charts_dir == dashboards_dir → one group, role 'charts'."""
        shared = tmp_path / "everything"
        shared.mkdir()
        (shared / "a.yaml").write_text(_CHART_YAML)
        app = create_app(
            project_dir=tmp_path,
            charts_dir=shared,
            dashboards_dir=shared,
        )
        client = TestClient(app)
        tree = client.get("/project").json()
        assert [(e["name"], e["group"]) for e in tree] == [("everything", "charts")]

    def test_assets_group_included_when_it_has_matching_files(self, tmp_path):
        (tmp_path / "charts").mkdir()
        (tmp_path / "charts" / "a.yaml").write_text(_CHART_YAML)
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "logo.json").write_text("{}")
        client = TestClient(create_app(project_dir=tmp_path))
        tree = client.get("/project").json()
        assert [e["group"] for e in tree] == ["charts", "assets"]
        assert tree[1]["children"] == [
            {"name": "logo.json", "type": "file", "path": "assets/logo.json"}
        ]


class TestFileIOUnchanged:
    def test_get_put_file_still_relative_to_project_dir(self, tmp_path):
        project = _make_default_project(tmp_path)
        client = TestClient(create_app(project_dir=project))

        resp = client.get("/file", params={"path": "charts/revenue.yaml"})
        assert resp.status_code == 200
        assert resp.json()["content"] == _CHART_YAML

        resp = client.put("/file", params={"path": "charts/new.yaml"}, content="sheet: new\n")
        assert resp.status_code == 200
        assert (project / "charts" / "new.yaml").read_text() == "sheet: new\n"

        resp = client.get("/file", params={"path": "../outside.yaml"})
        assert resp.status_code == 400
