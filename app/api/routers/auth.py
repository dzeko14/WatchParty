import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.user import (
    RefreshRequest,
    UserCreate,
    UserLogin,
    UserLoginResponse,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def add_refresh_token(session: AsyncSession, user_id: uuid.UUID) -> str:
    token = create_refresh_token()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    session.add(
        RefreshToken(
            user_id=user_id, token_hash=hash_refresh_token(token), expires_at=expires_at
        )
    )
    return token


async def revoke_all_if_reused(session: AsyncSession, token_hash: str) -> None:
    user_id = await session.scalar(
        select(RefreshToken.user_id).where(
            RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_not(None)
        )
    )
    if user_id is None:
        return
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    await session.commit()


@router.post("/logout", status_code=204)
async def logout(session: SessionDep, body: RefreshRequest) -> None:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(body.refresh_token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    )
    await session.commit()


@router.post("/login", status_code=200)
async def login(session: SessionDep, user_login: UserLogin) -> UserLoginResponse:
    user = await session.scalar(select(User).where(User.email == user_login.email))

    if user is None:
        raise HTTPException(401, "Email or password is wrong")

    is_verified_password = await verify_password(
        user_login.password, user.password_hash
    )

    if not is_verified_password:
        raise HTTPException(401, "Email or password is wrong")

    refresh_token = add_refresh_token(session, user.id)
    await session.commit()

    return UserLoginResponse(
        access_token=create_access_token(str(user.id)), refresh_token=refresh_token
    )


@router.post("/refresh")
async def refresh(session: SessionDep, body: RefreshRequest) -> UserLoginResponse:
    token_hash = hash_refresh_token(body.refresh_token)
    owner_id = await session.scalar(
        select(User.id)
        .join(RefreshToken, RefreshToken.user_id == User.id)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update(of=User)  # SQL: ... FOR UPDATE OF users
    )
    if owner_id is None:
        raise HTTPException(401, "Invalid refresh token")

    user_id = await session.scalar(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
        )
        .values(revoked_at=func.now())
        .returning(RefreshToken.user_id)
    )

    if user_id is None:
        await revoke_all_if_reused(session, token_hash)
        raise HTTPException(401, "Invalid refresh token")

    refresh_token = add_refresh_token(session, user_id)
    await session.commit()
    return UserLoginResponse(
        access_token=create_access_token(str(user_id)), refresh_token=refresh_token
    )


@router.post("/register", status_code=201)
async def register(session: SessionDep, user_create: UserCreate) -> UserRead:
    existing = await session.scalar(select(User).where(User.email == user_create.email))

    if existing is not None:
        raise HTTPException(409, "Email already registered")

    password_hash = await hash_password(user_create.password)
    new_user = User(
        email=user_create.email,
        password_hash=password_hash,
        display_name=user_create.display_name,
    )
    session.add(new_user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Email already registered")

    return UserRead.model_validate(new_user)
