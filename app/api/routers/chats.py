from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.api.deps import SessionDep, user_from_token
from app.models.room import Room, RoomMember

router = APIRouter(prefix="/rooms", tags=["rooms_web_socket"])


@router.websocket("/{code}/ws")
async def room_socket(
    websocket: WebSocket, session: SessionDep, code: str, token: str = ""
) -> None:
    await websocket.accept()
    user = await user_from_token(token=token, session=session)

    if user is None:
        await websocket.close(code=4001, reason="No user with such id")
        return
    room = await session.scalar(select(Room).where(Room.code == code))
    if room is None:
        await websocket.close(code=4004, reason="There is no room with such code")
        return
    room_membership_user_id = await session.scalar(
        select(RoomMember.user_id).where(
            RoomMember.user_id == user.id, RoomMember.room_id == room.id
        )
    )
    if room_membership_user_id is None:
        await websocket.close(code=4003, reason="User is not a member of a room")
        return
    await session.commit()

    try:
        while True:
            request_text = await websocket.receive_text()
            await websocket.send_json(
                {
                    "user_id": str(user.id),
                    "name": user.display_name,
                    "text": request_text,
                }
            )
    except WebSocketDisconnect:
        pass
