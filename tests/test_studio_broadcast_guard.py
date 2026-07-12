"""
Watcher-broadcast guards for preview/dashboard rendering (SHE-49).

Runs preview.js + dashboard.js in node against a DOM stub with a working
event bus (tests/support/run_broadcast_guard.mjs) and replays watcher
broadcasts: a compile/dashboard result stamped with a path other than the
open file's must not repaint the preview, the dashboard iframe, or end the
loading veil — while results for the open file (or unstamped local results)
behave exactly as before.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_broadcast_guard.mjs"


@lru_cache(maxsize=1)
def run_scenarios() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"broadcast guard harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_veil_arms_on_compile_start():
    assert run_scenarios()["veilArmed"] is True


def test_foreign_chart_broadcast_does_not_repaint():
    out = run_scenarios()
    assert out["foreignChartApplied"] is False
    assert out["foreignJsonPainted"] is False


def test_foreign_chart_broadcast_does_not_end_veil():
    assert run_scenarios()["veilAfterForeign"] is True


def test_own_file_broadcast_applies_and_ends_veil():
    out = run_scenarios()
    assert out["ownChartApplied"] is True
    assert out["veilAfterOwn"] is False


def test_local_result_without_path_applies():
    assert run_scenarios()["localChartApplied"] is True


def test_foreign_dashboard_broadcast_does_not_paint_iframe():
    assert run_scenarios()["foreignDashboardPainted"] is False


def test_own_dashboard_broadcast_paints_when_mode_active():
    assert run_scenarios()["ownDashboardPainted"] is True


def test_local_dashboard_result_paints():
    assert run_scenarios()["localDashboardPainted"] is True
