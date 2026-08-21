"""
`shelves-mcp` CLI tests (SHE-55).

The CLI's one job beyond argument parsing is to turn a missing `mcp` SDK into a
clear install hint instead of a traceback. Because `shelves.mcp.server` imports
the SDK lazily (inside `build_server`), the `ModuleNotFoundError` surfaces when
the server is *built*, not when it is imported — so the CLI must catch it around
the run, not just around the import.
"""

from __future__ import annotations

import pytest


def test_cli_missing_sdk_prints_install_hint(monkeypatch, tmp_path, capsys):
    """When the `mcp` SDK is absent, `main` prints the install hint and exits 1
    rather than propagating a traceback — even though the failure only surfaces
    inside `build_server`, not at import time."""
    import shelves.mcp.server as server_mod
    from shelves.mcp import cli

    def _no_sdk(*_args):
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    # Simulate the SDK missing: the lazy `import mcp.server` inside build_server
    # is what raises in production.
    monkeypatch.setattr(server_mod, "build_server", _no_sdk)

    rc = cli.main(["--project-dir", str(tmp_path)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "pip install" in err
    assert "mcp" in err


def test_cli_reraises_unrelated_import_error(monkeypatch, tmp_path):
    """A `ModuleNotFoundError` for something other than the `mcp` SDK must not be
    swallowed as the install hint — it propagates."""
    import shelves.mcp.server as server_mod
    from shelves.mcp import cli

    def _other_missing(*_args):
        raise ModuleNotFoundError("No module named 'numpy'", name="numpy")

    monkeypatch.setattr(server_mod, "build_server", _other_missing)

    with pytest.raises(ModuleNotFoundError):
        cli.main(["--project-dir", str(tmp_path)])
