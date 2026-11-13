import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, call

import pytest

from app.realtime.manager import QUEUE_SIZE, ConnectionManager, send_loop


def test_disconnect_twice_is_harmless() -> None:
    r_id = uuid.UUID(int=1)
    m = ConnectionManager()
    ws = AsyncMock()
    m.connect(r_id, ws)

    m.disconnect(r_id, ws)
    m.disconnect(r_id, ws)
    assert r_id not in m.rooms


def test_broadcast_reaches_every_queue() -> None:
    r_id = uuid.UUID(int=1)
    m = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    m.connect(r_id, ws1)
    m.connect(r_id, ws2)

    m.broadcast(r_id, {"text": "hi"})
    q_list = m.rooms[r_id]
    assert q_list[ws1].get_nowait() == {"text": "hi"}
    assert q_list[ws2].get_nowait() == {"text": "hi"}


def test_full_queue_drops_only_that_socket() -> None:
    r_id = uuid.UUID(int=1)
    m = ConnectionManager()
    slow = AsyncMock()
    fast = AsyncMock()

    m.connect(r_id, slow)
    m.connect(r_id, fast)

    slow_q = m.rooms[r_id][slow]
    for _ in range(QUEUE_SIZE):
        slow_q.put_nowait({"text": "some text to fill"})

    m.broadcast(r_id, {"text": "hi"})

    q_list = m.rooms[r_id]
    assert fast in q_list
    assert q_list[fast].get_nowait() == {"text": "hi"}
    assert slow not in q_list
    with pytest.raises(asyncio.QueueShutDown):
        slow_q.get_nowait()


async def test_send_loop_sends_in_order_and_stops_on_shutdown() -> None:
    ws = AsyncMock()
    queue = asyncio.Queue[dict[str, Any]]()

    a = {"n": 1}
    b = {"n": 2}

    queue.put_nowait(a)
    queue.put_nowait(b)
    queue.shutdown()

    with pytest.raises(asyncio.QueueShutDown):
        await send_loop(websocket=ws, queue=queue, timeout=0.1)

    assert ws.send_json.await_args_list == [call(a), call(b)]


async def never_returns(*args: object) -> None:
    await asyncio.Event().wait()


async def test_send_loop_gives_up_on_a_stuck_socket() -> None:
    ws = AsyncMock()
    ws.send_json.side_effect = never_returns
    queue = asyncio.Queue[dict[str, Any]]()
    a = {"n": 1}
    queue.put_nowait(a)

    async with asyncio.timeout(1):
        with pytest.raises(TimeoutError):
            await send_loop(websocket=ws, queue=queue, timeout=0.1)
