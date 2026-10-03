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


async def test_logout_stops_the_refresh_token(client: AsyncClient) -> None:
    tokens = await register_and_login(client)
    body = {"refresh_token": tokens["refresh_token"]}

    r1 = await client.post("/auth/logout", json=body)
    assert r1.status_code == 204

    r2 = await client.post("/auth/refresh", json=body)
    assert r2.status_code == 401


async def test_logout_with_unknown_token_returns_204(client: AsyncClient) -> None:
    r1 = await client.post("auth/logout", json={"refresh_token": "nonesense"})
    assert r1.status_code == 204


async def test_reused_token_stops_every_token_of_the_user(client: AsyncClient) -> None:
    phone = await register_and_login(client)
    laptop = (await client.post("/auth/login", json=REG)).json()
    old = {"refresh_token": phone["refresh_token"]}

    r = await client.post("/auth/refresh", json=old)
    assert r.status_code == 200
    new = r.json()

    r = await client.post("/auth/refresh", json=old)
    assert r.status_code == 401

    for token in (new["refresh_token"], laptop["refresh_token"]):
        r = await client.post("/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 401


async def test_reuse_does_not_touch_other_users(client: AsyncClient) -> None:
    ihor = await register_and_login(client)
    olena_creds = {"email": "olena@example.com", "password": "secret12"}
    await client.post("/auth/register", json=olena_creds)
    olena = (await client.post("/auth/login", json=olena_creds)).json()

    old = {"refresh_token": ihor["refresh_token"]}
    await client.post("/auth/refresh", json=old)
    await client.post("/auth/refresh", json=old)

    r = await client.post(
        "/auth/refresh", json={"refresh_token": olena["refresh_token"]}
    )
    assert r.status_code == 200
