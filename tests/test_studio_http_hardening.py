"""
Studio HTTP API Hardening Tests — SHE-52

Host validation on every endpoint/mount (DNS-rebinding defense: binding to
127.0.0.1 does not stop the victim's own browser from carrying an attacker
hostname in Host), the PUT /file write allow-list (theme file exempt), and
the direct resolve_safe unit coverage the 2026-07-04 review flagged missing.
"""

from __future__ import annotations

import os
from pathlib import Path

from shelves.studio.routes.files import _EXTENSION_ERROR, resolve_safe
from shelves.studio.server import create_app
from tests.conftest import LoopbackTestClient

_CHART_YAML = "sheet: test\n"


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "charts").mkdir(parents=True)
    (tmp_path / "charts" / "revenue.yaml").write_text(_CHART_YAML)
    return tmp_path


# ─── Host validation ─────────────────────────────────────────────


class TestHostValidation:
    def test_loopback_hosts_accepted(self, tmp_path):
        project = _make_project(tmp_path)
        client = LoopbackTestClient(create_app(project_dir=project))
        for host in ("127.0.0.1", "127.0.0.1:5173", "localhost", "localhost:8089"):
            assert client.get("/project", headers={"host": host}).status_code == 200
            resp = client.get(
                "/file", params={"path": "charts/revenue.yaml"}, headers={"host": host}
            )
            assert resp.status_code == 200

    def test_default_client_passes(self, tmp_path):
        """Pins that LoopbackTestClient really sends a loopback Host."""
        project = _make_project(tmp_path)
        client = LoopbackTestClient(create_app(project_dir=project))
        assert client.get("/project").status_code == 200

    def test_non_loopback_host_rejected_everywhere(self, tmp_path):
        project = _make_project(tmp_path)
        client = LoopbackTestClient(create_app(project_dir=project))
        requests = [
            ("GET", "/project", {}),
            ("GET", "/file", {"params": {"path": "charts/revenue.yaml"}}),
            (
                "PUT",
                "/file",
                {"params": {"path": "charts/revenue.yaml"}, "content": "x: 1\n"},
            ),
            ("POST", "/file", {"params": {"path": "charts/new.yaml"}}),
            (
                "POST",
                "/file/rename",
                {"params": {"path": "charts/revenue.yaml", "to": "charts/x.yaml"}},
            ),
            ("DELETE", "/file", {"params": {"path": "charts/revenue.yaml"}}),
            ("POST", "/compile", {"content": _CHART_YAML}),
            ("GET", "/schema", {}),
            ("GET", "/", {}),
            ("GET", "/static/styles.css", {}),
        ]
        for host in ("evil.example.com", "evil.example.com:5173"):
            for method, url, kwargs in requests:
                resp = client.request(method, url, headers={"host": host}, **kwargs)
                assert resp.status_code == 400, f"{method} {url} with Host {host}"
                assert resp.text == "Invalid host header", f"{method} {url}"
        # No filesystem side effects from any of the rejected writes.
        assert (project / "charts" / "revenue.yaml").read_text() == _CHART_YAML
        assert not (project / "charts" / "new.yaml").exists()
        assert not (project / "charts" / "x.yaml").exists()

    def test_missing_host_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = LoopbackTestClient(create_app(project_dir=project))
        resp = client.get("/project", headers={"host": ""})
        assert resp.status_code == 400


# ─── PUT /file write allow-list ──────────────────────────────────


class TestPutAllowList:
    def test_yaml_yml_json_writes_succeed(self, tmp_path):
        project = _make_project(tmp_path)
        client = LoopbackTestClient(create_app(project_dir=project))
        for rel in ("charts/a.yaml", "charts/b.yml", "assets_like/c.json"):
            resp = client.put("/file", params={"path": rel}, content="x: 1\n")
            assert resp.status_code == 200, rel
            assert (project / rel).read_text() == "x: 1\n"

    def test_theme_write_exempt_from_allowlist(self, tmp_path):
        project = _make_project(tmp_path)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        theme = outside / "brand.theme"  # deliberately NOT .yaml
        theme.write_text("font: Inter\n")
        app = create_app(project_dir=project, theme_path=theme)
        client = LoopbackTestClient(app)
        resp = client.put("/file", params={"path": "@theme/brand.theme"}, content="font: X\n")
        assert resp.status_code == 200
        assert theme.read_text() == "font: X\n"

    def test_put_disallowed_extension_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = LoopbackTestClient(create_app(project_dir=project))
        resp = client.put("/file", params={"path": "charts/evil.py"}, content='print("pwned")')
        assert resp.status_code == 400
        assert resp.text == _EXTENSION_ERROR
        assert not (project / "charts" / "evil.py").exists()

    def test_put_no_extension_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        client = LoopbackTestClient(create_app(project_dir=project))
        resp = client.put("/file", params={"path": "charts/Makefile"}, content="all:\n")
        assert resp.status_code == 400
        assert resp.text == _EXTENSION_ERROR
        assert not (project / "charts" / "Makefile").exists()

    def test_put_overwrite_disallowed_extension_rejected(self, tmp_path):
        project = _make_project(tmp_path)
        (project / "script.py").write_text("original\n")
        client = LoopbackTestClient(create_app(project_dir=project))
        resp = client.put("/file", params={"path": "script.py"}, content="evil\n")
        assert resp.status_code == 400
        assert (project / "script.py").read_text() == "original\n"


# ─── resolve_safe unit coverage ──────────────────────────────────


class TestResolveSafe:
    def test_empty_rel_rejected(self, tmp_path):
        _, error = resolve_safe(tmp_path, "")
        assert error == "Missing path parameter"

    def test_plain_relative_ok(self, tmp_path):
        project = _make_project(tmp_path)
        resolved, error = resolve_safe(project, "charts/revenue.yaml")
        assert error is None
        assert resolved == (project / "charts" / "revenue.yaml").resolve()

    def test_parent_traversal_rejected(self, tmp_path):
        _, error = resolve_safe(tmp_path, "../outside.yaml")
        assert error is not None
        assert "outside the project directory" in error

    def test_embedded_traversal_rejected(self, tmp_path):
        _, error = resolve_safe(tmp_path, "charts/../../x.yaml")
        assert error is not None

    def test_absolute_path_rejected(self, tmp_path):
        # pathlib gotcha this pins: (project / "/etc/passwd") IS /etc/passwd.
        _, error = resolve_safe(tmp_path, "/etc/passwd")
        assert error is not None

    def test_internal_dotdot_that_stays_inside_ok(self, tmp_path):
        project = _make_project(tmp_path)
        resolved, error = resolve_safe(project, "charts/../charts/revenue.yaml")
        assert error is None
        assert resolved == (project / "charts" / "revenue.yaml").resolve()

    def test_symlink_escape_rejected(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        outside_dir = tmp_path / "outside_dir"
        outside_dir.mkdir()
        os.symlink(outside_dir, project / "link")
        _, error = resolve_safe(project, "link/x.yaml")
        assert error is not None
