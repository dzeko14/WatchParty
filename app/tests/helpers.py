import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from httpx_ws import AsyncWebSocketSession, WebSocketDisconnect, aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import create_access_token
from app.main import app
from app.models.room import Room, RoomMember
from app.models.user import User

T0 = datetime(2026, 1, 1, tzinfo=UTC)


@asynccontextmanager
async def ws_connect(url: str) -> AsyncIterator[AsyncWebSocketSession]:
    async with (
        AsyncClient(
            transport=ASGIWebSocketTransport(app=app), base_url="http://test"
        ) as c,
        aconnect_ws(url, c, session_class=AsyncWebSocketSession) as ws,
    ):
        yield ws


@asynccontextmanager
async def join(url: str) -> AsyncIterator[AsyncWebSocketSession]:
    async with ws_connect(url) as ws:
        r = await ws.receive_json(timeout=1)
        assert r["type"] == "ready"
        yield ws


async def close_code(url: str) -> int:
    async with ws_connect(url) as ws:
        try:
            text = await ws.receive_text(timeout=1)
        except WebSocketDisconnect as e:
            return e.code
    raise AssertionError(f"socket stayed open and sent {text!r}")


async def add_user(session: AsyncSession, n: int, name: str) -> User:
    u = User(
        id=uuid.UUID(int=n),
        email=f"{name}@gmail.com",
        password_hash="password",
        display_name=name,
    )
    session.add(u)
    await session.commit()
    return u


def token_for(user: User) -> str:
    return create_access_token(str(user.id))


async def add_room_with_members(
    session: AsyncSession, host: User, members: list[User], code: str = "AAAAAAA"
) -> Room:
    session.add_all(members)
    r = Room(code=code, host_id=host.id)
    session.add(r)
    await session.flush()
    for i, u in enumerate([host, *members]):
        session.add(
            RoomMember(user_id=u.id, room_id=r.id, joined_at=T0 + timedelta(minutes=i))
        )
    await session.commit()
    return r


@contextmanager
def count_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def on_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", on_execute)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", on_execute)
