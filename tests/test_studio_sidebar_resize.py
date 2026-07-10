"""
sidebar.js resize-drag lifecycle tests (PR #59 review).

Runs the sidebar module in node against a DOM stub
(tests/support/run_sidebar_drag.mjs) and simulates a drag that ends with
`pointercancel` instead of `pointerup` — touch scrolling, an OS gesture, or
lost pointer capture. The drag must terminate: no stuck `.dragging` class and
no further reaction to pointer moves.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_sidebar_drag.mjs"


def run_drag() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"sidebar drag harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_pointerdown_starts_drag():
    assert run_drag()["duringDrag"] is True


def test_pointercancel_ends_drag():
    assert run_drag()["afterCancel"] is False


def test_pointermove_after_cancel_does_not_resize():
    assert run_drag()["movedAfterCancel"] is False
