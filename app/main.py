import uuid

from fastapi import FastAPI, HTTPException
from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import SessionDep, CurrentUserDep
from app.models.user import User
from app.schemas.user import UserRead, UserCreate, UserLogin, UserLoginResponse, UserUpdate
from app.db.engine import engine
from app.core.security import hash_password, verify_password, create_access_token

app = FastAPI()

@app.post("/auth/login", status_code=200)
async def login(session: SessionDep, user_login: UserLogin) -> UserLoginResponse:
    user = await session.scalar(select(User).where(User.email == user_login.email))

    if user is None:
        raise HTTPException(401, "Email or password is wrong")

    is_verified_password = await verify_password(user_login.password, user.password_hash)

    if not is_verified_password:
        raise HTTPException(401, "Email or password is wrong")

    return UserLoginResponse(
        access_token=create_access_token(str(user.id))
    )


@app.post("/auth/register", status_code=201)
async def register(session: SessionDep, user_create: UserCreate) -> UserRead:
    existing = await session.scalar(select(User).where(User.email == user_create.email))

    if existing is not None:
        raise HTTPException(409, "Email already registered")

    password_hash = await hash_password(user_create.password)
    new_user = User(
        email = user_create.email,
        password_hash = password_hash,
        display_name = user_create.display_name
    )
    session.add(new_user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Email already registered")

    return UserRead.model_validate(new_user)


@app.patch("/users/me")
async def user_me_patch(current_user: CurrentUserDep, session: SessionDep, user_update: UserUpdate) -> UserRead:
    for field, value in user_update.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    await session.commit()
    return UserRead.model_validate(current_user)

@app.get("/users/me")
async def user_me(current_user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(current_user)

@app.get("/users/{user_id}")
async def user(session: SessionDep, user_id: uuid.UUID) -> UserRead:
    read_user = await session.get(User, user_id)
    if read_user is None:
        raise HTTPException(status_code=404, detail="There is no user with such id")
    return UserRead.model_validate(read_user)   

@app.get("/users")
async def list_users(session: SessionDep) -> list[UserRead]:
    users = await session.scalars(select(User))
    return [UserRead.model_validate(user) for user in users]

@app.get("/health/db")
async def health_db() -> dict[str, str]:
    async with engine.connect() as connection:
        result = await connection.execute(text("select version()"))
        return {"database_message": result.scalar_one()}
    