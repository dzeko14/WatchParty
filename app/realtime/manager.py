import asyncio
import uuid
from typing import Any

from fastapi import WebSocket

QUEUE_SIZE = 100
SEND_TIMEOUT = 2 * 60


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, dict[WebSocket, asyncio.Queue[dict[str, Any]]]] = {}

    def connect(
        self, room_id: uuid.UUID, websocket: WebSocket
    ) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.rooms.setdefault(room_id, {})[websocket] = q
        return q

    def disconnect(self, room_id: uuid.UUID, websocket: WebSocket) -> None:
        try:
            q = self.rooms[room_id][websocket]
            self.rooms[room_id].pop(websocket, None)
            q.shutdown(immediate=True)
            if len(self.rooms[room_id]) == 0:
                self.rooms.pop(room_id, None)
        except KeyError:
            pass

    def broadcast(self, room_id: uuid.UUID, message: dict[str, Any]) -> None:
        for ws, q in self.rooms.get(room_id, {}).copy().items():
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                self.disconnect(room_id=room_id, websocket=ws)


manager = ConnectionManager()


async def send_loop(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
    timeout: float = SEND_TIMEOUT,
) -> None:
    while True:
        m = await queue.get()
        async with asyncio.timeout(timeout):
            await websocket.send_json(m)
