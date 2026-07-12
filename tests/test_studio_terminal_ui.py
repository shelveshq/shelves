"""
Integrated terminal open path + failure visibility (SHE-47).

Runs terminal.js in node with a fake xterm + WebSocket
(tests/support/run_terminal_open.mjs). The pre-SHE-47 bug class: term.open()
was gated on ws.onopen, so a connection/auth failure produced a blank panel
with its error written into a never-opened terminal — and the server's
auth-reject path (close 1008) fired onclose, which had no handler at all.

Asserts:
  - the panel is shown/sized BEFORE the terminal is created, and the
    terminal opens + fits synchronously, before the WebSocket exists;
  - auth precedes resize once the socket opens;
  - shell exit, 1008 auth-reject, and abnormal closes all write visible
    messages (and a user-initiated close stays silent);
  - when the xterm CDN import fails, the toggle still opens the panel and
    renders a readable error card.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

RUNNER = Path(__file__).parent / "support" / "run_terminal_open.mjs"


@lru_cache(maxsize=2)
def run_harness(mode: str) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(RUNNER), mode],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"terminal harness ({mode}) failed: {proc.stderr}"
    return json.loads(proc.stdout)


# ─── Open path ordering ──────────────────────────────────────────


def test_panel_opens_before_terminal_is_created():
    out = run_harness("open")
    assert out["orderPanelOpen"] != -1
    assert out["orderPanelOpen"] < out["orderTermOpen"]
    assert out["panelHeight"] == "250px"


def test_terminal_opens_synchronously_not_gated_on_ws():
    out = run_harness("open")
    assert out["orderTermOpen"] < out["orderWsCreated"]
    assert out["termOpenedBeforeWsOpen"] is True
    assert out["fitAfterOpen"] is True


def test_auth_precedes_resize_and_carries_meta_token():
    out = run_harness("open")
    assert out["firstMsg"] == {"type": "auth", "token": "tok-123"}
    assert out["secondMsgType"] == "resize"


# ─── Failure visibility ──────────────────────────────────────────


def test_shell_exit_is_visible_and_dims_tab():
    out = run_harness("open")
    assert out["exitLine"] is not None and "Process exited" in out["exitLine"]
    assert out["tab1Dead"] is True


def test_auth_reject_1008_writes_actionable_message():
    out = run_harness("open")
    assert out["term2OpenedSynchronously"] is True
    assert out["authRejectLines"] == 2  # rejection + "reload the page" hint
    assert out["tab2Dead"] is True


def test_abnormal_close_writes_disconnect_marker():
    out = run_harness("open")
    assert out["disconnectLine"] is not None and "1006" in out["disconnectLine"]


def test_user_initiated_close_stays_silent():
    out = run_harness("open")
    assert out["userClosedSuppressed"] is True
    assert out["term2Disposed"] is True


# ─── xterm CDN import failure ────────────────────────────────────


def test_lib_load_failure_still_opens_panel_with_error_card():
    out = run_harness("libfail")
    assert out["initErrored"] is True
    assert out["panelOpened"] is True
    assert out["errorCardText"] is not None
    assert "xterm" in out["errorCardText"]
