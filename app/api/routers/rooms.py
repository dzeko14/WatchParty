import secrets

from fastapi import APIRouter, Depends, HTTPException
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
