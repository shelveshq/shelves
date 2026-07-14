"""
websocket.js theme_changed routing — SHE-44

A theme_changed broadcast must reach the DOM as shelves:theme-changed
(tests/support/run_theme_event.mjs) so main.js recompiles the open buffer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_theme_event.mjs"


def run_harness() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"theme event harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_theme_changed_dispatches_dom_event():
    assert run_harness()["eventFired"] is True


def test_theme_changed_detail_carries_path():
    assert run_harness()["detailPath"] == "@theme/brand.yaml"
