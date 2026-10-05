import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUserDep, SessionDep, get_current_user
from app.models.user import User
from app.schemas.user import UserRead, UserUpdate

router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)]
)


@router.patch("/me")
async def user_me_patch(
    current_user: CurrentUserDep, session: SessionDep, user_update: UserUpdate
) -> UserRead:
    for field, value in user_update.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    await session.commit()
    return UserRead.model_validate(current_user)


@router.get("/me")
async def user_me(current_user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(current_user)


@router.get("/{user_id}")
async def user(session: SessionDep, user_id: uuid.UUID) -> UserRead:
    read_user = await session.get(User, user_id)
    if read_user is None:
        raise HTTPException(status_code=404, detail="There is no user with such id")
    return UserRead.model_validate(read_user)
