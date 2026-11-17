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
    m.connect(r_id, ws, user_id=uuid.UUID(int=1), name=None)

    m.disconnect(r_id, ws)
    m.disconnect(r_id, ws)
    assert r_id not in m.rooms


def test_broadcast_reaches_every_queue() -> None:
    r_id = uuid.UUID(int=1)
    m = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    m.connect(r_id, ws1, user_id=uuid.UUID(int=2), name=None)
    m.connect(r_id, ws2, user_id=uuid.UUID(int=3), name=None)

    m.broadcast(r_id, {"text": "hi"})
    q_list = m.rooms[r_id]
    assert q_list[ws1].queue.get_nowait() == {"text": "hi"}
    assert q_list[ws2].queue.get_nowait() == {"text": "hi"}


def test_full_queue_drops_only_that_socket() -> None:
    r_id = uuid.UUID(int=1)
    m = ConnectionManager()
    slow = AsyncMock()
    fast = AsyncMock()

    m.connect(r_id, slow, user_id=uuid.UUID(int=2), name=None)
    m.connect(r_id, fast, user_id=uuid.UUID(int=3), name=None)

    slow_q = m.rooms[r_id][slow]
    for _ in range(QUEUE_SIZE):
        slow_q.queue.put_nowait({"text": "some text to fill"})

    m.broadcast(r_id, {"text": "hi"})

    q_list = m.rooms[r_id]
    assert fast in q_list
    assert q_list[fast].queue.get_nowait() == {"text": "hi"}
    assert slow not in q_list
    with pytest.raises(asyncio.QueueShutDown):
        slow_q.queue.get_nowait()


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


async def test_online_lists_each_person_once() -> None:
    room_id = uuid.UUID(int=1)
    ann_id = uuid.UUID(int=1)
    bob_id = uuid.UUID(int=2)

    ann_ws_1 = AsyncMock()
    ann_ws_2 = AsyncMock()
    bob_ws_1 = AsyncMock()

    m = ConnectionManager()
    m.connect(room_id=room_id, websocket=ann_ws_1, user_id=ann_id, name="Ann")
    m.connect(room_id=room_id, websocket=ann_ws_2, user_id=ann_id, name="Ann")
    m.connect(room_id=room_id, websocket=bob_ws_1, user_id=bob_id, name="Bob")

    clients = m.online(room_id)
    assert clients[0] == {"user_id": str(ann_id), "name": "Ann"}
    assert clients[1] == {"user_id": str(bob_id), "name": "Bob"}


async def test_a_person_with_another_tab_stays_online() -> None:
    room_id = uuid.UUID(int=1)
    ann_id = uuid.UUID(int=1)

    ann_ws_1 = AsyncMock()
    ann_ws_2 = AsyncMock()

    m = ConnectionManager()
    m.connect(room_id=room_id, websocket=ann_ws_1, user_id=ann_id, name="Ann")
    m.connect(room_id=room_id, websocket=ann_ws_2, user_id=ann_id, name="Ann")

    m.disconnect(room_id=room_id, websocket=ann_ws_2)
    clients = m.online(room_id)
    assert len(clients) == 1
    assert clients[0] == {"user_id": str(ann_id), "name": "Ann"}

    m.disconnect(room_id=room_id, websocket=ann_ws_1)
    clients = m.online(room_id)
    assert len(clients) == 0


async def test_two_full_queues_in_one_broadcast() -> None:
    room_id = uuid.UUID(int=1)
    ann_id = uuid.UUID(int=1)
    bob_id = uuid.UUID(int=2)
    cat_id = uuid.UUID(int=3)

    ann_ws = AsyncMock()
    bob_ws = AsyncMock()
    cat_ws = AsyncMock()

    m = ConnectionManager()
    ann_queue = m.connect(room_id=room_id, websocket=ann_ws, user_id=ann_id, name="Ann")
    for _ in range(QUEUE_SIZE):
        ann_queue.put_nowait({"text": "some text to fill"})

    bob_queue = m.connect(room_id=room_id, websocket=bob_ws, user_id=bob_id, name="Bob")
    for _ in range(QUEUE_SIZE):
        bob_queue.put_nowait({"text": "some text to fill"})

    m.connect(room_id=room_id, websocket=cat_ws, user_id=cat_id, name="Cat")

    m.broadcast(room_id=room_id, message={"text": "hi"})

    assert list(m.rooms[room_id]) == [cat_ws]
    assert m.rooms[room_id][cat_ws].queue.get_nowait() == {"text": "hi"}
