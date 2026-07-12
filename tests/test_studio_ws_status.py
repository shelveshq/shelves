"""
WebSocket disconnect visibility + reconnect resync (SHE-66).

Runs websocket.js in node with a fake WebSocket
(tests/support/run_ws_status.mjs) and drives the connection lifecycle: a
disconnect must paint a gated "Reconnecting…" status (grey dot), repeated
failures escalate to "server unreachable", and a successful REconnect —
never the first connect — restores the status and dispatches
`shelves:ws-reconnected` (sidebar re-fetches the tree, main.js recompiles
the open buffer).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_ws_status.mjs"


@lru_cache(maxsize=1)
def run_lifecycle() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"ws status harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_first_connect_is_not_a_reconnect():
    out = run_lifecycle()
    assert out["initialStatus"] == "connected"
    assert out["initialResyncCount"] == 0


def test_disconnect_paint_is_gated():
    assert run_lifecycle()["statusRightAfterClose"] == "connected"


def test_disconnect_shows_reconnecting_after_gate():
    out = run_lifecycle()
    assert out["statusAfterGate"] == "reconnecting"
    assert out["dotAfterGate"] == "sh-status-dot reconnecting"
    assert out["msgAfterGate"] == "Reconnecting…"


def test_reconnect_restores_status_and_resyncs_once():
    out = run_lifecycle()
    assert out["statusAfterReconnect"] == "connected"
    assert out["resyncAfterReconnect"] == 1


def test_repeated_failures_escalate_to_unreachable():
    out = run_lifecycle()
    assert out["statusAfterManyFailures"] == "unreachable"
    assert "unreachable" in out["msgAfterManyFailures"]
    assert "shelves-studio" in out["msgAfterManyFailures"]


def test_recovery_after_unreachable_resyncs():
    out = run_lifecycle()
    assert out["statusAfterRecovery"] == "connected"
    assert out["resyncAfterRecovery"] == 2
