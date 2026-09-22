import uuid

from fastapi import FastAPI, HTTPException
from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import SessionDep
from app.models.user import User
from app.schemas.user import UserRead, UserCreate
from app.db.engine import engine
from app.core.security import hash_password

app = FastAPI()

@app.post("/auth/register", status_code=201)
async def register(session: SessionDep, userCreate: UserCreate) -> UserRead:
    existing = await session.scalar(select(User).where(User.email == userCreate.email))

    if existing is not None:
        raise HTTPException(409, "Email already registered")

    password_hash = await hash_password(userCreate.password)
    new_user = User(
        id = uuid.uuid4(),
        email = userCreate.email,
        password_hash = password_hash,
        display_name = userCreate.display_name
    )
    session.add(new_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise exc

    return UserRead.model_validate(new_user)


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
    