import asyncio

from argon2 import PasswordHasher

_hasher = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1)

async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)
