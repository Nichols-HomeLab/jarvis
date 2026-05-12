from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class ProjectorHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._last_event: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    @property
    def last_event(self) -> dict[str, Any] | None:
        return self._last_event

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        if self._last_event is not None:
            await websocket.send_json(self._last_event)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        self._last_event = event
        dead: list[WebSocket] = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.discard(ws)
