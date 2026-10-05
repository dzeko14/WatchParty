import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.models.user import User


async def test_patch_change_display_name(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.patch(
        "/users/me", json={"display_name": "Ihor B"}, headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Ihor B"
    assert r.json()["email"] == "ihor@example.com"


async def test_patch_with_empty_body_changes_nothing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.patch("/users/me", json={}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["display_name"] == "Ihor"


async def test_patch_with_null_clears_display_name(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.patch(
        "/users/me", json={"display_name": None}, headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["display_name"] is None


@pytest.mark.parametrize(
    "bodies",
    [{"email": "new@example.com"}, {"password_hash": "x"}, {"display_nmae": "typo"}],
    ids=["email", "password hash", "typo in display name"],
)
async def test_patch_rejects_fields_you_cannot_edit(
    client: AsyncClient, auth_headers: dict[str, str], bodies: dict[str, str]
) -> None:
    r = await client.patch("/users/me", json=bodies, headers=auth_headers)
    assert r.status_code == 422


async def test_patch_needs_login(client: AsyncClient) -> None:
    r = await client.patch("/users/me", json={"display_name": "Ihor B"})
    assert r.status_code == 401


async def test_patch_is_saved_in_the_database(
    client: AsyncClient, auth_headers: dict[str, str], engine: AsyncEngine
) -> None:
    await client.patch(
        "/users/me", json={"display_name": "Ihor B"}, headers=auth_headers
    )

    async with engine.connect() as conn:
        saved = await conn.scalar(select(User.display_name))
    assert saved == "Ihor B"


async def test_user_by_id_needs_login(client: AsyncClient, user: User) -> None:
    r = await client.get(f"/users/{user.id}")
    assert r.status_code == 401


async def test_user_by_id_works_with_login(
    client: AsyncClient, user: User, auth_headers: dict[str, str]
) -> None:
    r = await client.get(f"/users/{user.id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == str(user.id)
