import uuid

from fastapi import FastAPI, HTTPException
from sqlalchemy import text, select

from app.api.deps import SessionDep
from app.models.user import User
from app.schemas.user import UserRead
from app.db.engine import engine

app = FastAPI()

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
    