from fastapi import FastAPI
from app.db.engine import engine
from sqlalchemy import text

app = FastAPI()

@app.get("/health/db")
async def health_db() -> dict[str, str]:
    async with engine.connect() as connection:
        result = await connection.execute(text("select version()"))
        return {"database_message": result.scalar_one()}
    