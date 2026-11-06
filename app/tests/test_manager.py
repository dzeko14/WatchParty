import uuid
from unittest.mock import AsyncMock

from fastapi import WebSocketDisconnect

from app.realtime.manager import ConnectionManager


async def test_broadcast_skips_a_broken_socket() -> None:
    r_id = uuid.UUID(int=1)
    m = ConnectionManager()
    broken_ws = AsyncMock()
    broken_ws.send_json.side_effect = WebSocketDisconnect(1006)
    m.connect(r_id, broken_ws)

    success_ws = AsyncMock()
    m.connect(r_id, success_ws)

    message = {"text": "hi"}
    await m.broadcast(r_id, message)
    success_ws.send_json.assert_awaited_once_with(message)
    assert len(m.rooms[r_id]) == 1
    assert m.rooms[r_id][0] == success_ws


async def test_disconnect_twice_is_harmless() -> None:
    r_id = uuid.UUID(int=1)
    m = ConnectionManager()
    ws = AsyncMock()
    m.connect(r_id, ws)

    m.disconnect(r_id, ws)
    m.disconnect(r_id, ws)
    assert r_id not in m.rooms
