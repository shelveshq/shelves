"""
Studio Theme-File Exposure Tests — SHE-44

When --theme is set, the theme file appears in the /project tree (real
relative path inside the project, exact-match "@theme/<name>" alias when it
lives outside), opens/saves via GET/PUT /file, and every theme write —
Studio save or on-disk edit — broadcasts theme_changed so clients recompile
the open buffer with the new theme.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, call

from shelves.studio.lifespan import _build_scope_dirs, handle_fs_event
from shelves.studio.routes.files import theme_alias
from shelves.studio.server import create_app
from tests.conftest import LoopbackTestClient as TestClient

_CHART_YAML = "sheet: test\n"
_THEME_YAML = "font: Inter\n"


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "charts").mkdir(parents=True)
    (tmp_path / "charts" / "revenue.yaml").write_text(_CHART_YAML)
    return tmp_path


def _outside_theme(tmp_path: Path) -> tuple[Path, Path]:
    """(project, theme) with the theme outside the project dir."""
    project = _make_project(tmp_path / "project")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    theme = outside / "brand.yaml"
    theme.write_text(_THEME_YAML)
    return project, theme


# ─── Tree entry ──────────────────────────────────────────────────


class TestThemeInTree:
    def test_inside_project_theme_listed_with_real_path(self, tmp_path):
        project = _make_project(tmp_path)
        (project / "theme.yaml").write_text(_THEME_YAML)
        client = TestClient(create_app(project_dir=project, theme_path=project / "theme.yaml"))
        tree = client.get("/project").json()
        assert tree[-1] == {
            "name": "theme.yaml",
            "type": "file",
            "path": "theme.yaml",
            "group": "theme",
        }

    def test_outside_project_theme_listed_with_alias(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        client = TestClient(create_app(project_dir=project, theme_path=theme))
        tree = client.get("/project").json()
        assert tree[-1] == {
            "name": "brand.yaml",
            "type": "file",
            "path": "@theme/brand.yaml",
            "group": "theme",
        }

    def test_no_theme_no_entry(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        tree = client.get("/project").json()
        assert [e["group"] for e in tree] == ["charts", "dashboards", "models"]

    def test_missing_theme_file_omitted(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project, theme_path=project / "ghost.yaml"))
        tree = client.get("/project").json()
        assert "theme" not in [e["group"] for e in tree]


# ─── Alias file IO ───────────────────────────────────────────────


class TestThemeAliasIO:
    def test_get_alias_reads_theme(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        client = TestClient(create_app(project_dir=project, theme_path=theme))
        resp = client.get("/file", params={"path": "@theme/brand.yaml"})
        assert resp.status_code == 200
        assert resp.json() == {"content": _THEME_YAML, "path": "@theme/brand.yaml"}

    def test_put_alias_writes_and_broadcasts(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        app = create_app(project_dir=project, theme_path=theme)
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            resp = client.put(
                "/file", params={"path": "@theme/brand.yaml"}, content="font: Georgia\n"
            )
            assert resp.status_code == 200
            assert theme.read_text() == "font: Georgia\n"
            # No file_change for the alias — the tree entry is static; the
            # first message is the theme_changed itself.
            assert ws.receive_json() == {"type": "theme_changed", "path": "@theme/brand.yaml"}

    def test_put_real_path_theme_broadcasts(self, tmp_path):
        project = _make_project(tmp_path)
        theme = project / "theme.yaml"
        theme.write_text(_THEME_YAML)
        app = create_app(project_dir=project, theme_path=theme)
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            resp = client.put("/file", params={"path": "theme.yaml"}, content="font: Georgia\n")
            assert resp.status_code == 200
            assert ws.receive_json() == {"type": "theme_changed", "path": "theme.yaml"}

    def test_put_non_theme_no_theme_broadcast(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        app = create_app(project_dir=project, theme_path=theme)
        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            client.put("/file", params={"path": "charts/revenue.yaml"}, content="sheet: x\n")
            client.put("/file", params={"path": "@theme/brand.yaml"}, content="font: Y\n")
            # The chart PUT must not emit theme_changed: the first theme event
            # carries the alias path from the SECOND request.
            assert ws.receive_json() == {"type": "theme_changed", "path": "@theme/brand.yaml"}


# ─── Alias safety ────────────────────────────────────────────────


class TestThemeAliasSafety:
    def test_alias_requires_configured_theme(self, tmp_path):
        project = _make_project(tmp_path)
        client = TestClient(create_app(project_dir=project))
        resp = client.get("/file", params={"path": "@theme/x.yaml"})
        assert resp.status_code != 200

    def test_alias_name_must_match(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        client = TestClient(create_app(project_dir=project, theme_path=theme))
        resp = client.get("/file", params={"path": "@theme/other.yaml"})
        assert resp.status_code != 200

    def test_alias_traversal_rejected(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        client = TestClient(create_app(project_dir=project, theme_path=theme))
        resp = client.get("/file", params={"path": "@theme/../../etc/passwd"})
        assert resp.status_code == 400

    def test_alias_not_deletable(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        client = TestClient(create_app(project_dir=project, theme_path=theme))
        resp = client.delete("/file", params={"path": "@theme/brand.yaml"})
        assert resp.status_code >= 400
        assert theme.exists()

    def test_alias_not_renamable(self, tmp_path):
        project, theme = _outside_theme(tmp_path)
        client = TestClient(create_app(project_dir=project, theme_path=theme))
        resp = client.post(
            "/file/rename", params={"path": "@theme/brand.yaml", "to": "charts/x.yaml"}
        )
        assert resp.status_code >= 400
        assert theme.read_text() == _THEME_YAML


# ─── Watcher routing (lifespan) ──────────────────────────────────


class TestWatcherThemeRouting:
    def test_theme_event_broadcasts_theme_changed(self, tmp_path):
        project = _make_project(tmp_path)
        theme = project / "theme.yaml"
        theme.write_text(_THEME_YAML)
        manager = AsyncMock()
        asyncio.run(
            handle_fs_event(
                "modified",
                theme,
                manager=manager,
                project_dir=project,
                theme_path=theme,
                models_dir=project / "models",
                charts_dir=project / "charts",
            )
        )
        assert manager.broadcast.await_args_list == [
            call({"type": "file_change", "event": "modified", "path": "theme.yaml"}),
            call({"type": "theme_changed", "path": "theme.yaml"}),
        ]

    def test_chart_event_still_compiles(self, tmp_path):
        project = _make_project(tmp_path)
        theme = project / "theme.yaml"
        theme.write_text(_THEME_YAML)
        manager = AsyncMock()
        asyncio.run(
            handle_fs_event(
                "modified",
                project / "charts" / "revenue.yaml",
                manager=manager,
                project_dir=project,
                theme_path=theme,
                models_dir=project / "models",
                charts_dir=project / "charts",
            )
        )
        broadcasts = [c.args[0] for c in manager.broadcast.await_args_list]
        assert broadcasts[0] == {
            "type": "file_change",
            "event": "modified",
            "path": "charts/revenue.yaml",
        }
        assert any(b["type"] == "compile_result" for b in broadcasts)
        assert not any(b["type"] == "theme_changed" for b in broadcasts)

    def test_theme_delete_broadcasts(self, tmp_path):
        project = _make_project(tmp_path)
        theme = project / "theme.yaml"  # never written — deletion event
        manager = AsyncMock()
        asyncio.run(
            handle_fs_event(
                "deleted",
                theme,
                manager=manager,
                project_dir=project,
                theme_path=theme,
                models_dir=project / "models",
                charts_dir=project / "charts",
            )
        )
        assert manager.broadcast.await_args_list == [
            call({"type": "file_change", "event": "deleted", "path": "theme.yaml"}),
            call({"type": "theme_changed", "path": "theme.yaml"}),
        ]

    def test_scope_dirs_include_theme(self, tmp_path):
        charts = tmp_path / "charts"
        dashboards = tmp_path / "dashboards"
        models = tmp_path / "models"
        assets = tmp_path / "assets"
        theme = tmp_path / "theme.yaml"
        assert _build_scope_dirs(charts, dashboards, models, assets, theme) == [
            charts,
            dashboards,
            models,
            assets,
            theme,
        ]
        assert _build_scope_dirs(charts, dashboards, models, assets, None) == [
            charts,
            dashboards,
            models,
            assets,
        ]


# ─── parameters_changed routing ─────────────────────────────────


class TestWatcherParametersRouting:
    def test_parameters_event_broadcasts_parameters_changed(self, tmp_path):
        project = _make_project(tmp_path)
        models = project / "models"
        models.mkdir(exist_ok=True)
        params_file = models / "parameters.yaml"
        params_file.write_text("parameters:\n  region:\n    type: string\n")
        manager = AsyncMock()
        asyncio.run(
            handle_fs_event(
                "modified",
                params_file,
                manager=manager,
                project_dir=project,
                theme_path=None,
                models_dir=models,
                charts_dir=project / "charts",
                parameters_path=params_file,
            )
        )
        assert manager.broadcast.await_args_list == [
            call({"type": "file_change", "event": "modified", "path": "models/parameters.yaml"}),
            call({"type": "parameters_changed", "path": "models/parameters.yaml"}),
        ]

    def test_chart_event_does_not_broadcast_parameters_changed(self, tmp_path):
        project = _make_project(tmp_path)
        models = project / "models"
        models.mkdir(exist_ok=True)
        params_file = models / "parameters.yaml"
        params_file.write_text("parameters:\n  region:\n    type: string\n")
        manager = AsyncMock()
        asyncio.run(
            handle_fs_event(
                "modified",
                project / "charts" / "revenue.yaml",
                manager=manager,
                project_dir=project,
                theme_path=None,
                models_dir=models,
                charts_dir=project / "charts",
                parameters_path=params_file,
            )
        )
        broadcasts = [c.args[0] for c in manager.broadcast.await_args_list]
        assert not any(b["type"] == "parameters_changed" for b in broadcasts)


# ─── theme_alias helper ──────────────────────────────────────────


def test_theme_alias():
    assert theme_alias(None) is None
    assert theme_alias(Path("/x/brand.yaml")) == "@theme/brand.yaml"
