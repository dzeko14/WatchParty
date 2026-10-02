import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models.user import User


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def alembic_cfg(postgres_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["database.url"] = postgres_url
    return cfg


@pytest.fixture(scope="session")
async def engine(postgres_url: str, alembic_cfg: Config) -> AsyncIterator[AsyncEngine]:
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    eng = create_async_engine(postgres_url)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s

    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(delete(table))


@pytest.fixture
async def client(
    engine: AsyncEngine, session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def user(session: AsyncSession) -> User:
    u = User(
        email="ihor@example.com",
        password_hash=await hash_password("secret12"),
        display_name="Ihor",
    )
    session.add(u)
    await session.commit()
    return u


@pytest.fixture
def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}
