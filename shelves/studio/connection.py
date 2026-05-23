from __future__ import annotations

from fastapi import WebSocket


class ConnectionManager:
    """
    Manages active WebSocket connections for broadcast.

    One instance per app (stored in app.state) for test isolation.
    Not designed for multi-process deployments — Studio is a local dev tool.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection from the set."""
        self._connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """
        Send a JSON message to all connected clients.

        Removes any client that fails to receive the message (disconnected).
        """
        dead: set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)
