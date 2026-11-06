import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, list[WebSocket]] = {}

    def connect(self, room_id: uuid.UUID, websocket: WebSocket) -> None:
        self.rooms.setdefault(room_id, []).append(websocket)

    def disconnect(self, room_id: uuid.UUID, websocket: WebSocket) -> None:
        try:
            self.rooms[room_id].remove(websocket)
            if len(self.rooms[room_id]) == 0:
                self.rooms.pop(room_id, None)
        except ValueError, KeyError:
            pass

    async def broadcast(self, room_id: uuid.UUID, message: dict[str, Any]) -> None:
        for ws in list(self.rooms.get(room_id, [])):
            try:
                await ws.send_json(message)
            except WebSocketDisconnect:
                self.disconnect(room_id=room_id, websocket=ws)


manager = ConnectionManager()
