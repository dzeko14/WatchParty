import asyncio

from httpx import AsyncClient
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken

REG = {"email": "ihor@example.com", "password": "secret12"}


async def register_and_login(client: AsyncClient) -> dict[str, str]:
    await client.post("/auth/register", json=REG)
    r = await client.post("/auth/login", json=REG)
    assert r.status_code == 200
    tokens: dict[str, str] = r.json()
    return tokens


async def test_refresh_returns_new_tokens_that_work(client: AsyncClient) -> None:
    tokens = await register_and_login(client)

    r = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    me = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {new['access_token']}"}
    )
    assert me.status_code == 200


async def test_refresh_token_works_only_once(client: AsyncClient) -> None:
    tokens = await register_and_login(client)
    body = {"refresh_token": tokens["refresh_token"]}

    r1 = await client.post("/auth/refresh", json=body)
    r2 = await client.post("/auth/refresh", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 401


async def test_expired_refresh_token_returns_401(
    client: AsyncClient, session: AsyncSession
) -> None:
    tokens = await register_and_login(client)
    await session.execute(update(RefreshToken).values(expires_at=func.now()))
    await session.commit()

    r = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r.status_code == 401


async def test_two_refreshes_at_once_only_one_wins(client: AsyncClient) -> None:
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    # Two requests at once make the pool open a second connection. Without this,
    # the second refresh waits ~20 ms for a new connection and starts too late.
    await asyncio.gather(
        client.get("/users/me", headers=headers),
        client.get("/users/me", headers=headers),
    )

    body = {"refresh_token": tokens["refresh_token"]}
    r1, r2 = await asyncio.gather(
        client.post("/auth/refresh", json=body),
        client.post("/auth/refresh", json=body),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 401]
