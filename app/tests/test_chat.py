import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import create_access_token
from app.tests.helpers import (
    add_room_with_members,
    add_user,
    close_code,
    token_for,
    ws_connect,
)


@pytest.mark.parametrize(
    "query",
    [
        "/rooms/AAAAAAA/ws",
        "/rooms/AAAAAAA/ws?token=not-a-jwt",
        f"/rooms/AAAAAAA/ws?token={create_access_token(str(uuid.UUID(int=99)))})",
    ],
    ids=["no token", "wrong token", "valid token for non existing user"],
)
async def test_bad_token_is_closed(session: AsyncSession, query: str) -> None:
    u = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=u, members=[])

    code = await close_code(query)
    assert code == 4001


async def test_unknown_room_is_closed(
    session: AsyncSession,
) -> None:
    u = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=u, members=[])

    code = await close_code(f"/rooms/ZZZZZZZ/ws?token={token_for(u)}")
    assert code == 4004


async def test_member_of_another_room_is_closed(
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=ann, members=[])

    bob = await add_user(session=session, n=2, name="Bob")

    await add_room_with_members(session=session, host=bob, members=[], code="BBBBBBB")

    code = await close_code(f"/rooms/AAAAAAA/ws?token={token_for(bob)}")
    assert code == 4003


async def test_member_gets_own_message_back(
    session: AsyncSession,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=ann, members=[])

    async with ws_connect(f"/rooms/AAAAAAA/ws?token={token_for(ann)}") as ws:
        await ws.send_text("hi")
        response = await ws.receive_json(timeout=1)
        assert response == {"user_id": str(ann.id), "name": "Ann", "text": "hi"}


async def test_open_socket_holds_no_db_transaction(
    session: AsyncSession,
    engine: AsyncEngine,
) -> None:
    ann = await add_user(session=session, n=1, name="Ann")

    await add_room_with_members(session=session, host=ann, members=[])

    async with ws_connect(f"/rooms/AAAAAAA/ws?token={token_for(ann)}") as ws:
        await ws.send_text("hi")
        await ws.receive_json(timeout=1)
        stuck = await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE state = 'idle in transaction'"
            )
        )
    assert stuck == 0
