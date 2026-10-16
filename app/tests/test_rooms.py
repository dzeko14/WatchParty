import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import event, func, select
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
        email=f"{uuid.uuid4()}@mail.com",
        password_hash=await hash_password("secret12"),
    )
    session.add(u1)
    u2 = User(
        email=f"{uuid.uuid4()}@mail.com",
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


async def test_rooms_with_body_return_201_and_chosen_values(
    client: AsyncClient,
    session: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    r = await client.post(
        "/rooms", headers=auth_headers, json={"is_public": False, "member_limit": 6}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["is_public"] is False
    assert body["member_limit"] == 6

    room_in_db = await session.scalar(
        select(Room).where(Room.id == uuid.UUID(body["id"]))
    )
    assert room_in_db is not None
    assert room_in_db.is_public is False
    assert room_in_db.member_limit == 6


async def test_rooms_with_no_body_return_201_and_room_with_defaults(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    r = await client.post("/rooms", headers=auth_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["is_public"] is True
    assert body["member_limit"] == 5


@pytest.mark.parametrize(
    "limit",
    [0, 1, 51, 100],
    ids=["0 far below ge", "1 just below ge", "51 just above le", "100 far above le"],
)
async def test_rooms_with_limit_outside_range_return_422_and_no_room_created(
    client: AsyncClient,
    session: AsyncSession,
    auth_headers: dict[str, str],
    limit: int,
) -> None:
    r = await client.post(
        "/rooms", headers=auth_headers, json={"is_public": True, "member_limit": limit}
    )
    assert r.status_code == 422
    rooms_in_db = (
        await session.execute(select(func.count()).select_from(Room))
    ).scalar_one()
    assert rooms_in_db == 0


@pytest.mark.parametrize(
    "limit", [2, 50], ids=["2 lowest allowed", "50 highest allowed"]
)
async def test_rooms_with_limit_at_range_ends_return_201(
    client: AsyncClient,
    session: AsyncSession,
    auth_headers: dict[str, str],
    limit: int,
) -> None:
    r = await client.post(
        "/rooms", headers=auth_headers, json={"is_public": True, "member_limit": limit}
    )
    assert r.status_code == 201
    assert r.json()["member_limit"] == limit

    room_in_db = await session.scalar(
        select(Room).where(Room.id == uuid.UUID(r.json()["id"]))
    )
    assert room_in_db is not None
    assert room_in_db.member_limit == limit


async def test_get_rooms_without_login_return_401(client: AsyncClient) -> None:
    r = await client.get("/rooms")
    assert r.status_code == 401


async def create_test_rooms(session: AsyncSession, user: User) -> list[Room]:
    r1 = Room(code="AAAAAAA", member_limit=7, is_public=True)  # public, no members
    r2 = Room(code="BBBBBBB", member_limit=5, is_public=True)  # public, 1 member
    r3 = Room(code="ZZZZZZZ", member_limit=4, is_public=False)  # private
    session.add_all([r1, r2, r3])
    await session.flush()
    session.add(RoomMember(user_id=user.id, room_id=r2.id))
    await session.commit()
    return [r1, r2]


async def test_get_rooms_return_list_of_public_rooms(
    client: AsyncClient,
    auth_headers: dict[str, str],
    user: User,
    session: AsyncSession,
) -> None:
    r1, r2 = await create_test_rooms(session, user)
    r = await client.get("/rooms", headers=auth_headers)
    assert r.status_code == 200
    expected: list[dict[str, Any]] = [
        {"id": str(r1.id), "code": "AAAAAAA", "member_limit": 7, "member_count": 0},
        {"id": str(r2.id), "code": "BBBBBBB", "member_limit": 5, "member_count": 1},
    ]
    # The endpoint orders by Room.id. Sorting the id strings gives the same order.
    assert r.json() == sorted(expected, key=lambda item: item["id"])


@contextmanager
def count_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def on_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", on_execute)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", on_execute)


async def add_room(
    session: AsyncSession, code: str, is_public: bool, member_limit: int
) -> Room:
    r = Room(code=code, is_public=is_public, member_limit=member_limit)
    session.add(r)
    await session.flush()
    return r


async def test_number_of_db_statements_does_not_grow_with_rooms(
    client: AsyncClient,
    session: AsyncSession,
    engine: AsyncEngine,
    auth_headers: dict[str, str],
) -> None:
    for code in ["AAAAAAA", "BBBBBBB", "CCCCCCC"]:
        await add_room(session, code, is_public=True, member_limit=5)
    await session.commit()
    with count_statements(engine) as statements1:
        r = await client.get("/rooms", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 3

    for code in [
        "DDDDDDD",
        "EEEEEEE",
        "FFFFFFF",
        "GGGGGGG",
        "HHHHHHH",
        "IIIIIII",
        "JJJJJJJ",
    ]:
        await add_room(session, code, is_public=True, member_limit=5)
    await session.commit()
    with count_statements(engine) as statements2:
        r = await client.get("/rooms", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 10

    ids = [item["id"] for item in r.json()]
    assert ids == sorted(ids)

    assert len(statements1) == len(statements2)
