import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUserDep, SessionDep, get_current_user
from app.models.room import Room, RoomMember
from app.models.user import User
from app.schemas.rooms import PublicRoomRead, RoomCreate, RoomHandover, RoomRead

router = APIRouter(
    prefix="/rooms", tags=["rooms"], dependencies=[Depends(get_current_user)]
)

CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DEFAULT_ROOM_CREATE = RoomCreate()
NO_ROOM_BY_THIS_CODE_MSG = "There is no room with such code"


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(7))


@router.get("")
async def get_rooms(
    session: SessionDep,
) -> list[PublicRoomRead]:
    rows = await session.execute(
        select(
            Room.id,
            Room.code,
            Room.member_limit,
            func.count(RoomMember.room_id).label("member_count"),
        )
        .outerjoin(RoomMember, RoomMember.room_id == Room.id)
        .where(Room.is_public)
        .group_by(Room.id)
        .order_by(Room.id)
        .limit(50)
    )

    return [PublicRoomRead.model_validate(row) for row in rows]


@router.post("", status_code=201)
async def post_rooms(
    session: SessionDep, user: CurrentUserDep, body: RoomCreate = DEFAULT_ROOM_CREATE
) -> RoomRead:
    for _ in range(5):
        r = Room(
            code=new_code(),
            member_limit=body.member_limit,
            is_public=body.is_public,
            host_id=user.id,
        )
        try:
            async with session.begin_nested():
                session.add(r)
        except IntegrityError:
            continue

        r_m = RoomMember(user_id=user.id, room_id=r.id)
        session.add(r_m)
        await session.commit()
        return RoomRead.model_validate(r)

    raise HTTPException(500, "No free code after 5 attempts")


@router.post("/{code}/members")
async def join_room(
    response: Response, session: SessionDep, user: CurrentUserDep, code: str
) -> RoomRead:
    room = await session.scalar(select(Room).where(Room.code == code).with_for_update())
    if room is None:
        raise HTTPException(404, detail=NO_ROOM_BY_THIS_CODE_MSG)

    present_room_membership = await session.scalar(
        select(func.count())
        .select_from(RoomMember)
        .where(RoomMember.user_id == user.id, RoomMember.room_id == room.id)
    )
    if present_room_membership is not None and present_room_membership == 1:
        response.status_code = status.HTTP_200_OK
        return RoomRead.model_validate(room)

    actual_room_members_amount = await session.scalar(
        select(func.count())
        .select_from(RoomMember)
        .where(RoomMember.room_id == room.id)
    )
    if (
        actual_room_members_amount is not None
        and actual_room_members_amount >= room.member_limit
    ):
        raise HTTPException(409, detail="The room is full")

    session.add(RoomMember(user_id=user.id, room_id=room.id))
    await session.commit()
    response.status_code = status.HTTP_201_CREATED
    return RoomRead.model_validate(room)


@router.delete("/{code}/members/me", status_code=204)
async def leave_room(session: SessionDep, user: CurrentUserDep, code: str) -> None:
    room = await session.scalar(select(Room).where(Room.code == code).with_for_update())
    if room is None:
        raise HTTPException(404, detail=NO_ROOM_BY_THIS_CODE_MSG)

    room_member = await session.scalar(
        delete(RoomMember)
        .where(RoomMember.room_id == room.id, RoomMember.user_id == user.id)
        .returning(RoomMember)
    )

    if room_member is None:
        raise HTTPException(404, "User is not a part of a room")

    if user.id != room.host_id:
        await session.commit()
        return

    await session.flush()

    next_host_id = await session.scalar(
        select(RoomMember.user_id)
        .where(RoomMember.room_id == room.id)
        .order_by(RoomMember.joined_at, RoomMember.user_id)
        .limit(1)
    )

    if next_host_id is None:
        await session.scalar(delete(Room).where(Room.id == room.id).returning(Room))
    else:
        room.host_id = next_host_id
        session.add(room)

    await session.commit()


@router.put("/{code}/host")
async def handover_host(
    session: SessionDep, current_user: CurrentUserDep, body: RoomHandover, code: str
) -> RoomRead:
    room = await session.scalar(select(Room).where(Room.code == code).with_for_update())
    if room is None:
        raise HTTPException(404, NO_ROOM_BY_THIS_CODE_MSG)

    if current_user.id != room.host_id:
        raise HTTPException(403, "Only the host can do handover")

    next_host_id = await session.scalar(select(User.id).where(User.id == body.user_id))

    if next_host_id is None:
        raise HTTPException(404, "There is no such user for next host")

    membership = await session.scalar(
        select(RoomMember).where(
            RoomMember.user_id == next_host_id, RoomMember.room_id == room.id
        )
    )

    if membership is None:
        raise HTTPException(
            409, "User, you are trying to handover to, is not a member of room"
        )

    room.host_id = next_host_id
    session.add(room)
    await session.commit()
    return RoomRead.model_validate(room)
