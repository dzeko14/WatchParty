import asyncio
import jwt

from datetime import datetime, timezone, timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.core.config import settings

_hasher = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1)

async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)

async def verify_password(password: str, password_hash: str) -> bool:
    try:
        return await asyncio.to_thread(_hasher.verify, password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False

def create_access_token(subject: str) -> str:
    current_time = datetime.now(timezone.utc)
    exp_time = current_time + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "exp": exp_time,
        "iat": current_time
    }
    return jwt.encode(payload, settings.jwt_secret_key, settings.jwt_algorithm)
