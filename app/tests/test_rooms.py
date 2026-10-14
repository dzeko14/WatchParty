import asyncio
import random
import string
import uuid

from httpx import AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.routers.rooms import CODE_ALPHABET
from app.core.security import create_access_token, hash_password
from app.models.room import Room, RoomMember
from app.models.user import User

REG = {"email": "ihor@example.com", "password": "secret12"}


async def setup_full_room(
    session: AsyncSession, member_count: int, code: str = "AAAAAAA"
) -> Room:
    u1 = User(
        email=f"{''.join(random.choices(string.ascii_letters, k=7))}@mail.com",
        password_hash=await hash_password("secret12"),
    )
    session.add(u1)
    u2 = User(
        email=f"{''.join(random.choices(string.ascii_letters, k=7))}@mail.com",
        password_hash=await hash_password("secret12"),
    )
    session.add(u2)
    room = Room(code=code, member_limit=member_count)
    session.add(room)
    await session.flush()
    session.add(RoomMember(user_id=u1.id, room_id=room.id))
    session.add(RoomMember(user_id=u2.id, room_id=room.id))
    await session.commit()
    return room


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


async def test_post_room_members_no_auth_get_401(client: AsyncClient) -> None:
    r = await client.post("/rooms/AAAAAAA/members")
    assert r.status_code == 401


async def test_post_room_with_code_no_room_404(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.post("/rooms/AAAAAAA/members", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "There is no room with such code"


async def test_post_room_with_real_code_return_room(
    client: AsyncClient,
    auth_headers: dict[str, str],
    room: Room,
    user: User,
    session: AsyncSession,
) -> None:
    r = await client.post(f"/rooms/{room.code}/members", headers=auth_headers)
    assert r.status_code == 201
    room_id = r.json()["id"]

    room_member = await session.scalar(
        select(RoomMember).where(
            RoomMember.user_id == user.id, RoomMember.room_id == uuid.UUID(room_id)
        )
    )
    assert room_member is not None


async def test_post_room_already_joined_return_200(
    client: AsyncClient,
    auth_headers: dict[str, str],
    room: Room,
    user: User,
    session: AsyncSession,
) -> None:
    session.add(RoomMember(user_id=user.id, room_id=room.id))
    await session.commit()

    r = await client.post(f"/rooms/{room.code}/members", headers=auth_headers)
    assert r.status_code == 200

    members_joined = await session.scalar(
        select(func.count())
        .select_from(RoomMember)
        .where(RoomMember.room_id == room.id)
    )

    assert members_joined is not None and members_joined == 1


async def test_full_room_return_409_when_join(
    client: AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    room = await setup_full_room(session, 2)
    r = await client.post(f"/rooms/{room.code}/members", headers=auth_headers)
    assert r.status_code == 409
    user_memeber_amount = await session.scalar(
        select(func.count())
        .select_from(RoomMember)
        .where(RoomMember.room_id == room.id)
    )
    assert user_memeber_amount is not None and user_memeber_amount == 2


async def test_member_full_room_join_again_return_200(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user: User,
    session: AsyncSession,
) -> None:
    room = await setup_full_room(session, 3)
    session.add(RoomMember(user_id=user.id, room_id=room.id))
    await session.commit()
    r = await client.post(f"/rooms/{room.code}/members", headers=auth_headers)
    assert r.status_code == 200


async def test_delete_room_membership_user_in_return_204(
    client: AsyncClient,
    room: Room,
    auth_headers: dict[str, str],
    user: User,
    session: AsyncSession,
) -> None:
    session.add(RoomMember(user_id=user.id, room_id=room.id))
    await session.commit()
    r = await client.delete(f"/rooms/{room.code}/members/me", headers=auth_headers)
    assert r.status_code == 204
    member_amount = await session.scalar(
        select(func.count())
        .select_from(RoomMember)
        .where(RoomMember.room_id == room.id, RoomMember.user_id == user.id)
    )
    assert member_amount is not None and member_amount == 0


async def test_delete_room_membership_user_not_in_return_404(
    client: AsyncClient, auth_headers: dict[str, str], session: AsyncSession
) -> None:
    room = Room(code="BBBBBBB")
    session.add(room)
    await session.commit()

    r = await client.delete(f"/rooms/{room.code}/members/me", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "User is not a part of a room"


async def test_2_users_joins_1_free_place_in_room_one_successfully_joins(
    client: AsyncClient, session: AsyncSession
) -> None:
    warmup_room = await setup_full_room(session=session, member_count=10)
    u1 = User(
        email="ihor1@example.com",
        password_hash=await hash_password("secret12"),
        display_name="Ihor1",
    )
    u2 = User(
        email="ihor2@example.com",
        password_hash=await hash_password("secret12"),
        display_name="Ihor2",
    )
    session.add(u1)
    session.add(u2)
    await session.commit()

    auth_header_1 = {"Authorization": f"Bearer {create_access_token(str(u1.id))}"}
    auth_header_2 = {"Authorization": f"Bearer {create_access_token(str(u2.id))}"}

    await asyncio.gather(
        client.post(f"/rooms/{warmup_room.code}/members", headers=auth_header_1),
        client.post(f"/rooms/{warmup_room.code}/members", headers=auth_header_2),
    )

    room = await setup_full_room(session=session, member_count=3, code="BBBBBBB")
    r1, r2 = await asyncio.gather(
        client.post(f"/rooms/{room.code}/members", headers=auth_header_1),
        client.post(f"/rooms/{room.code}/members", headers=auth_header_2),
    )
    assert sorted([r1.status_code, r2.status_code]) == [201, 409]
