import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUserDep, SessionDep, get_current_user
from app.models.room import Room, RoomMember
from app.schemas.rooms import RoomRead

router = APIRouter(
    prefix="/rooms", tags=["rooms"], dependencies=[Depends(get_current_user)]
)

CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(7))


@router.post("", status_code=201)
async def post_rooms(session: SessionDep, user: CurrentUserDep) -> RoomRead:
    for _ in range(5):
        r = Room(code=new_code())
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
        raise HTTPException(404, detail="There is no room with such code")

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
    room = await session.scalar(select(Room).where(Room.code == code))
    if room is None:
        raise HTTPException(404, detail="There is no room with such code")

    room_member = await session.scalar(
        delete(RoomMember)
        .where(RoomMember.room_id == room.id, RoomMember.user_id == user.id)
        .returning(RoomMember)
    )
    await session.commit()
    if room_member is None:
        raise HTTPException(404, "User is not a part of a room")
