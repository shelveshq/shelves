from __future__ import annotations

import asyncio
import secrets
from urllib.parse import urlparse

from fastapi import WebSocket, WebSocketDisconnect

_TERMINAL_AUTH_TIMEOUT_SECONDS = 5.0

_ALLOWED_WS_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_allowed_ws_origin(origin: str | None) -> bool:
    """Return True if a WebSocket Origin header points to a loopback host.

    Browsers always send Origin for WebSocket handshakes from page context,
    so a missing/empty Origin is treated as untrusted too.
    """
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in _ALLOWED_WS_HOSTS


async def ws_terminal(ws: WebSocket) -> None:
    """
    Terminal WebSocket endpoint.

    Protocol (client -> server):
        {"type": "auth", "token": "<string>"}     — REQUIRED first message
        {"type": "input", "data": "<string>"}     — keystrokes to write to PTY
        {"type": "resize", "rows": N, "cols": N}  — terminal resize event

    Protocol (server -> client):
        {"type": "output", "data": "<base64>"}     — PTY output (base64-encoded)
        {"type": "exit", "code": N}                — shell process exited

    Security:
      * The Origin header must be a loopback origin — browsers always
        send Origin for WS, so cross-site pages are rejected before accept.
      * The client must send an auth message with the per-app token
        within _TERMINAL_AUTH_TIMEOUT_SECONDS. This defends against a
        malicious local process or browser extension that could bypass
        the Origin check.
    Each authenticated connection gets its own PtyManager instance.
    On disconnect, the PTY is closed and the subprocess terminated.
    """
    import base64 as _base64
    import json as _json

    from shelves.studio.terminal import PtyManager

    if not is_allowed_ws_origin(ws.headers.get("origin")):
        await ws.close(code=1008)
        return

    await ws.accept()

    # Require auth before spawning a shell.
    expected_token: str = ws.app.state.terminal_token
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=_TERMINAL_AUTH_TIMEOUT_SECONDS)
        auth_msg = _json.loads(raw)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        await ws.close(code=1008)
        return

    token = auth_msg.get("token") if isinstance(auth_msg, dict) else None
    if (
        not isinstance(auth_msg, dict)
        or auth_msg.get("type") != "auth"
        or not isinstance(token, str)
        or not secrets.compare_digest(token, expected_token)
    ):
        await ws.close(code=1008)
        return

    project_dir = str(ws.app.state.project_dir)
    mgr = PtyManager(cwd=project_dir)
    try:
        mgr.spawn()
    except OSError as e:
        await ws.send_json({"type": "exit", "code": -1, "error": str(e)})
        await ws.close()
        return

    async def _read_loop() -> None:
        try:
            while mgr.is_alive:
                data = await mgr.read()
                if not data:
                    break
                await ws.send_json(
                    {"type": "output", "data": _base64.b64encode(data).decode("ascii")}
                )
            # Shell exited
            code = mgr._proc.returncode if mgr._proc else 0
            try:
                await ws.send_json({"type": "exit", "code": code or 0})
            except Exception:
                pass
        except Exception:
            pass

    read_task = asyncio.create_task(_read_loop())

    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            try:
                msg = _json.loads(raw)
            except Exception:
                # Malformed JSON — close gracefully
                break
            msg_type = msg.get("type")
            if msg_type == "input":
                data_str = msg.get("data", "")
                if data_str:
                    mgr.write(data_str.encode())
            elif msg_type == "resize":
                rows = int(msg.get("rows", 24))
                cols = int(msg.get("cols", 80))
                mgr.resize(rows, cols)
            # Unknown types are silently ignored
    except Exception:
        pass
    finally:
        read_task.cancel()
        try:
            await read_task
        except asyncio.CancelledError:
            pass
        mgr.close()
