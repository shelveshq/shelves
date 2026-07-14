"""
Studio Integrated Terminal Tests — SHE-47

Backend coverage for the PTY terminal:
  - PtyManager.spawn(): the shell must be a session leader with the PTY
    slave as its controlling terminal (job control: Ctrl+C, fg/bg).
  - WS /ws/terminal: origin gating, token auth, echo round-trip, and
    malformed resize input must not kill the session.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from shelves.studio.routes.terminal import is_allowed_ws_origin
from shelves.studio.server import create_app
from shelves.studio.terminal import PtyManager
from tests.conftest import LoopbackTestClient as TestClient

# ─── is_allowed_ws_origin ────────────────────────────────────────


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8089",
        "http://127.0.0.1:8089",
        "https://localhost",
        "http://[::1]:8089",
    ],
)
def test_allowed_origins(origin: str) -> None:
    assert is_allowed_ws_origin(origin) is True


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "http://evil.com",
        "http://localhost.evil.com:8089",
        "ftp://localhost",
        "file://localhost",
        "not a url",
    ],
)
def test_rejected_origins(origin: str | None) -> None:
    assert is_allowed_ws_origin(origin) is False


# ─── PtyManager: session + controlling TTY (SHE-47 candidate 5) ──


def test_spawned_shell_is_session_leader_with_ctty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shell must own its session and the PTY as controlling terminal.

    Without this, job control misbehaves (Ctrl+C not interrupting,
    `zsh: can't set tty pgrp` warnings). tcgetpgrp on the master returns
    the slave side's foreground process group — 0 when no session has
    acquired the PTY, the shell's pid once it has.
    """
    monkeypatch.setenv("SHELL", "/bin/sh")
    mgr = PtyManager(cwd=str(tmp_path))
    mgr.spawn()
    try:
        assert mgr._proc is not None
        pid = mgr._proc.pid
        # Session leader: the shell's session id is its own pid.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if os.getsid(pid) == pid:
                break
            time.sleep(0.02)
        assert os.getsid(pid) == pid
        # Controlling TTY: the PTY has a foreground process group — the shell's.
        assert mgr._master_fd is not None
        assert os.tcgetpgrp(mgr._master_fd) == pid
    finally:
        mgr.close()


def test_close_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/sh")
    mgr = PtyManager(cwd=str(tmp_path))
    mgr.spawn()
    mgr.close()
    mgr.close()
    assert mgr.is_alive is False


# ─── WS /ws/terminal ─────────────────────────────────────────────

ORIGIN = {"origin": "http://127.0.0.1:8089"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SHELL", "/bin/sh")
    (tmp_path / "charts").mkdir()
    (tmp_path / "models").mkdir()
    app = create_app(project_dir=tmp_path)
    return TestClient(app)


def _auth(ws, token: str) -> None:
    ws.send_text(json.dumps({"type": "auth", "token": token}))


def _read_output_until(ws, needle: bytes, timeout: float = 5.0) -> bytes:
    """Collect base64 output frames until `needle` appears or timeout."""
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = json.loads(ws.receive_text())
        if msg["type"] == "output":
            buf += base64.b64decode(msg["data"])
            if needle in buf:
                return buf
        elif msg["type"] == "exit":
            break
    raise AssertionError(f"needle {needle!r} not found in terminal output: {buf!r}")


def test_ws_rejects_bad_origin(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/terminal", headers={"origin": "http://evil.com"}),
    ):
        pass
    assert exc_info.value.code == 1008


def test_ws_rejects_bad_token(client: TestClient) -> None:
    with client.websocket_connect("/ws/terminal", headers=ORIGIN) as ws:
        _auth(ws, "wrong-token")
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 1008


def test_ws_echo_round_trip(client: TestClient) -> None:
    token = client.app.state.terminal_token  # type: ignore[attr-defined]
    with client.websocket_connect("/ws/terminal", headers=ORIGIN) as ws:
        _auth(ws, token)
        ws.send_text(json.dumps({"type": "input", "data": "echo shelves-ok\r"}))
        _read_output_until(ws, b"shelves-ok")


def test_ws_malformed_resize_does_not_kill_session(client: TestClient) -> None:
    """Garbage rows/cols must be ignored, not raise into the receive loop."""
    token = client.app.state.terminal_token  # type: ignore[attr-defined]
    with client.websocket_connect("/ws/terminal", headers=ORIGIN) as ws:
        _auth(ws, token)
        ws.send_text(json.dumps({"type": "resize", "rows": "garbage", "cols": None}))
        ws.send_text(json.dumps({"type": "resize", "rows": -5, "cols": 10**9}))
        # Session must still be alive and interactive after both.
        ws.send_text(json.dumps({"type": "input", "data": "echo still-alive\r"}))
        _read_output_until(ws, b"still-alive")


def test_ws_hostile_frames_do_not_kill_session(client: TestClient) -> None:
    """Any post-auth frame is untrusted, not just resize (PR #63 review).

    Non-dict JSON raised AttributeError on msg.get(); non-string input data
    raised on .encode(). Both fell into the outer `except Exception: pass`,
    tearing down the PTY and closing with a default 1000 — a silently dead
    terminal, the exact SHE-47 failure mode. All of these must be ignored.
    """
    token = client.app.state.terminal_token  # type: ignore[attr-defined]
    with client.websocket_connect("/ws/terminal", headers=ORIGIN) as ws:
        _auth(ws, token)
        ws.send_text("[1, 2]")  # valid JSON, not a dict
        ws.send_text('"just a string"')
        ws.send_text("not json {")  # malformed JSON
        ws.send_text(json.dumps({"type": "input", "data": 123}))
        ws.send_text(json.dumps({"type": "input", "data": {"a": 1}}))
        ws.send_text(json.dumps({"type": "input", "data": None}))
        # Session must still be alive and interactive after all of them.
        ws.send_text(json.dumps({"type": "input", "data": "echo survived-hostile\r"}))
        _read_output_until(ws, b"survived-hostile")
