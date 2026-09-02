"""In-process WebSocket hub for /ws/alerts broadcasts."""
import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("sentinel.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to every connected client; silently drop
        sockets that fail mid-send (clients disconnecting are expected)."""
        async with self._lock:
            targets = list(self._connections)
        dead: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        if dead:
            async with self._lock:
                for websocket in dead:
                    self._connections.discard(websocket)
            logger.debug("dropped %d dead websocket(s)", len(dead))


manager = ConnectionManager()
