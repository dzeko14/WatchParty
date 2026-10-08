import uuid

from httpx import AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.routers.rooms import CODE_ALPHABET
from app.models.room import Room, RoomMember
from app.models.user import User

REG = {"email": "ihor@example.com", "password": "secret12"}


async def test_post_room_no_auth_get_401(client: AsyncClient) -> None:
    r = await client.post("/rooms")
    assert r.status_code == 401


async def test_post_room_return_new_room_with_token(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.post("/rooms", headers=auth_headers)
    assert r.status_code == 201
    body = r.json()
    code = body["code"]
    assert body["id"] is not None
    assert code is not None
    assert len(code) == 7
    for c in code:
        index = CODE_ALPHABET.find(c)
        assert index > -1


async def test_post_room_return_new_room_with_user_in_it(
    client: AsyncClient, auth_headers: dict[str, str], user: User, engine: AsyncEngine
) -> None:
    r = await client.post("/rooms", headers=auth_headers)
    assert r.status_code == 201
    body = r.json()

    async with engine.connect() as con:
        user_id = await con.scalar(
            select(RoomMember.user_id).where(RoomMember.room_id == body["id"])
        )
    assert user_id == user.id


async def test_code_collision_when_creating_room(
    client: AsyncClient,
    auth_headers: dict[str, str],
    room: Room,
    monkeypatch: MonkeyPatch,
) -> None:
    codes = iter(["AAAAAAA", "AAAAAAA", "CCCCCCC"])
    monkeypatch.setattr("app.api.routers.rooms.new_code", lambda: next(codes))
    r = await client.post("/rooms", headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["code"] == "CCCCCCC"


async def test_code_collision_loop_not_stuck(
    client: AsyncClient,
    auth_headers: dict[str, str],
    room: Room,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.routers.rooms.new_code", lambda: "AAAAAAA")
    r = await client.post("/rooms", headers=auth_headers)
    assert r.status_code == 500


async def test_same_membership_refused(
    client: AsyncClient, auth_headers: dict[str, str], user: User, session: AsyncSession
) -> None:
    r = await client.post("/rooms", headers=auth_headers)
    assert r.status_code == 201
    body = r.json()

    second_membership_was_not_created = False
    try:
        session.add(RoomMember(user_id=user.id, room_id=uuid.UUID(body["id"])))
        await session.commit()
    except IntegrityError:
        second_membership_was_not_created = True
    assert second_membership_was_not_created
