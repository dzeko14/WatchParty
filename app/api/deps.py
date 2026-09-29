import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.user import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]

bearer_schema = HTTPBearer()

TokenDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_schema)]

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(token: TokenDep, session: SessionDep) -> User:
    try:
        payload = jwt.decode(
            jwt=token.credentials,
            key=settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = uuid.UUID(payload["sub"])
        user = await session.get(User, user_id)
        if user is None:
            raise CREDENTIALS_ERROR
        return user
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise CREDENTIALS_ERROR from exc


CurrentUserDep = Annotated[User, Depends(get_current_user)]
