import pytest

from httpx import AsyncClient

REG = {"email": "ihor@example.com", "password": "secret12", "display_name": "Ihor"}
LOG = { "email": "ihor@example.com", "password": "secret12" }
WRONG_LOG_PASSWORD = { "email": "ihor@example.com", "password": "secret" }
WRONG_LOG_EMAIL = { "email": "ih@example.com", "password": "secret12" }

async def test_register_returns_201_no_hash(client: AsyncClient) -> None:
    r = await client.post("/auth/register", json = REG)

    assert r.status_code == 201
    body = r.json()
    assert body["email"] == REG["email"]
    assert "password_hash" not in body
    assert "password" not in body

async def test_register_same_email_twice_returns_409(client: AsyncClient) -> None:
    r1 = await client.post("/auth/register", json = REG)

    assert r1.status_code == 201

    r2 = await client.post("/auth/register", json = REG)
    assert r2.status_code == 409

async def test_login_return_token_that_works(client: AsyncClient) -> None:
    r1 = await client.post("/auth/register", json = REG)
    assert r1.status_code == 201

    r2 = await client.post("/auth/login", json=LOG)
    assert r2.status_code == 200
    token = r2.json()["access_token"]

    r3 = await client.get("/users/me", headers= {"Authorization": f"Bearer {token}"})
    assert r3.status_code == 200

async def test_login_with_wrong_password_return_401(client: AsyncClient) -> None:
    r1 = await client.post("/auth/register", json = REG)
    assert r1.status_code == 201

    r2 = await client.post("/auth/login", json=WRONG_LOG_PASSWORD)
    assert r2.status_code == 401

async def test_login_with_wrong_email_return_401_and_same_message_as_wrong_password(client: AsyncClient) -> None:
    r1 = await client.post("/auth/register", json = REG)
    assert r1.status_code == 201

    r2 = await client.post("/auth/login", json=WRONG_LOG_PASSWORD)
    assert r2.status_code == 401
    wrong_message = r2.content

    r3 = await client.post("/auth/login", json=WRONG_LOG_EMAIL)
    assert r3.status_code == 401
    assert wrong_message == r3.content

@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic abc"}],
    ids=["no header", "bad token", "wrong scheme"],
)
async def test_users_me_rejects_bad_credentials(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    r = await client.get("/users/me", headers=headers)
    assert r.status_code == 401
