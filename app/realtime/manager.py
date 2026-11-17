import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

QUEUE_SIZE = 100
SEND_TIMEOUT = 2 * 60


@dataclass
class Client:
    user_id: uuid.UUID
    name: str | None
    queue: asyncio.Queue[dict[str, Any]]


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, dict[WebSocket, Client]] = {}

    def connect(
        self,
        room_id: uuid.UUID,
        websocket: WebSocket,
        user_id: uuid.UUID,
        name: str | None,
    ) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        c = Client(user_id=user_id, name=name, queue=q)
        self.rooms.setdefault(room_id, {})[websocket] = c
        return q

    def online(self, room_id: uuid.UUID) -> list[dict[str, str | None]]:
        people: dict[uuid.UUID, str | None] = {}
        for v in self.rooms.get(room_id, {}).values():
            people.setdefault(v.user_id, v.name)
        return [{"user_id": str(k), "name": v} for k, v in people.items()]

    def disconnect(self, room_id: uuid.UUID, websocket: WebSocket) -> None:
        try:
            client = self.rooms[room_id][websocket]
            self.rooms[room_id].pop(websocket, None)
            client.queue.shutdown(immediate=True)
            if len(self.rooms[room_id]) == 0:
                self.rooms.pop(room_id, None)
        except KeyError:
            pass

    def broadcast(self, room_id: uuid.UUID, message: dict[str, Any]) -> None:
        for ws, client in self.rooms.get(room_id, {}).copy().items():
            try:
                client.queue.put_nowait(message)
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
