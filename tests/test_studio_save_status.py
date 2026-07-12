"""
Save (Cmd+S) feedback in the status bar (SHE-65).

`saveCurrentFile` only clears the dirty flag on a confirmed 2xx PUT and
surfaces failures through `state.saveStatus` / `state.saveError`. These tests
run state.js under node (tests/support/run_save_status.mjs) and pin the
status-bar rendering of the save states and their precedence.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_save_status.mjs"


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
    assert proc.returncode == 0, f"save status harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_saving_state_renders_pulsing_dot():
    out = run_scenarios()
    assert out["savingDot"] == "sh-status-dot compiling"
    assert out["savingMsg"] == "Saving…"


def test_failed_save_is_persistent_error_with_reason():
    out = run_scenarios()
    assert out["failedDot"] == "sh-status-dot error"
    assert out["failedMsg"] == "Save failed: disk full"


def test_failed_save_without_reason_falls_back():
    assert run_scenarios()["failedNoReasonMsg"] == "Save failed: unknown error"


def test_saved_flash_renders_plain_dot():
    out = run_scenarios()
    assert out["savedDot"] == "sh-status-dot"
    assert out["savedMsg"] == "Saved"


def test_compiling_outranks_save_status():
    assert run_scenarios()["compilingOverSaveMsg"] == "Compiling…"


def test_cleared_save_status_yields_to_marker_counts():
    assert run_scenarios()["countsAfterClearMsg"] == "2 errors"
