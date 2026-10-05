from fastapi import APIRouter
from sqlalchemy import text

from app.db.engine import engine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/db")
async def health_db() -> dict[str, str]:
    async with engine.connect() as connection:
        result = await connection.execute(text("select version()"))
        return {"database_message": result.scalar_one()}
