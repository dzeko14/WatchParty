import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.realtime.manager import manager
from app.tests.helpers import (
    add_room_with_members,
    add_user,
    close_code,
    join,
    token_for,
)


@pytest.mark.parametrize(
    "query",
    [
        "/rooms/AAAAAAA/ws",
        "/rooms/AAAAAAA/ws?token=not-a-jwt",
        f"/rooms/AAAAAAA/ws?token={create_access_token(str(uuid.UUID(int=99)))}",
    ],
    ids=["no token", "wrong token", "valid token for non existing user"],
)
async def test_bad_token_is_closed(
    db_override: None, session: AsyncSession, query: str
) -> None:
    u = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=u, members=[])

    code = await close_code(query)
    assert code == 4001


async def test_unknown_room_is_closed(
    db_override: None,
    session: AsyncSession,
) -> None:
    u = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=u, members=[])

    code = await close_code(f"/rooms/ZZZZZZZ/ws?token={token_for(u)}")
    assert code == 4004


async def test_member_of_another_room_is_closed(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=ann, members=[])

    bob = await add_user(session=session, n=2, name="Bob")

    await add_room_with_members(session=session, host=bob, members=[], code="BBBBBBB")

    code = await close_code(f"/rooms/AAAAAAA/ws?token={token_for(bob)}")
    assert code == 4003


async def test_member_gets_own_message_back(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=ann, members=[])

    async with join(f"/rooms/AAAAAAA/ws?token={token_for(ann)}") as ws:
        await ws.send_text("hi")
        response = await ws.receive_json(timeout=1)
        assert response == {
            "type": "message",
            "user_id": str(ann.id),
            "name": "Ann",
            "text": "hi",
        }


async def test_open_socket_holds_no_db_transaction(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=ann, members=[])

    async with join(f"/rooms/AAAAAAA/ws?token={token_for(ann)}") as ws:
        await ws.send_text("hi")
        await ws.receive_json(timeout=1)
        stuck = await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE state = 'idle in transaction'"
            )
        )
    assert stuck == 0


async def test_message_reaches_everyone_in_the_room(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")
    bob = await add_user(session=session, n=2, name="Bob")

    await add_room_with_members(session=session, host=ann, members=[bob])

    async with (
        join(f"/rooms/AAAAAAA/ws?token={token_for(ann)}") as a,
        join(f"/rooms/AAAAAAA/ws?token={token_for(bob)}") as b,
    ):
        await a.send_text("hi")
        b_result = await b.receive_json(timeout=1)
        a_result = await a.receive_json(timeout=0.2)
        expect_result = {
            "type": "message",
            "user_id": str(ann.id),
            "name": "Ann",
            "text": "hi",
        }
        assert b_result == expect_result
        assert a_result == expect_result


async def test_other_room_hears_nothing(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")
    cat = await add_user(session=session, n=3, name="Cat")

    await add_room_with_members(session=session, host=ann, members=[])
    await add_room_with_members(session=session, host=cat, members=[], code="BBBBBBB")

    async with (
        join(f"/rooms/AAAAAAA/ws?token={token_for(ann)}") as a,
        join(f"/rooms/BBBBBBB/ws?token={token_for(cat)}") as b,
    ):
        await a.send_text("hi")
        with pytest.raises(TimeoutError):
            await b.receive_json(timeout=0.2)


async def test_a_closed_socket_does_not_break_the_room(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")
    bob = await add_user(session=session, n=2, name="Bob")
    cat = await add_user(session=session, n=3, name="Cat")

    await add_room_with_members(session=session, host=ann, members=[bob, cat])

    async with join(f"/rooms/AAAAAAA/ws?token={token_for(ann)}"):
        pass

    async with (
        join(f"/rooms/AAAAAAA/ws?token={token_for(bob)}") as b,
        join(f"/rooms/AAAAAAA/ws?token={token_for(cat)}") as c,
    ):
        await b.send_text("hi")
        c_result = await c.receive_json(timeout=1)
        assert c_result == {
            "type": "message",
            "user_id": str(bob.id),
            "name": "Bob",
            "text": "hi",
        }


async def test_room_is_forgotten_when_the_last_socket_closes(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")
    room = await add_room_with_members(session=session, host=ann, members=[])

    async with join(f"/rooms/AAAAAAA/ws?token={token_for(ann)}"):
        assert len(manager.rooms[room.id]) == 1

    assert room.id not in manager.rooms


async def test_room_is_forgotten_when_the_handler_fails(
    db_override: None,
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")
    room = await add_room_with_members(session=session, host=ann, members=[])

    async with join(f"/rooms/AAAAAAA/ws?token={token_for(ann)}") as a:
        assert len(manager.rooms[room.id]) == 1
        await a.send_bytes(b"not text")

    assert room.id not in manager.rooms
