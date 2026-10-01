import asyncio

from alembic import command
from alembic.config import Config


async def test_migrations_match_models(alembic_cfg: Config) -> None:
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    await asyncio.to_thread(command.check, alembic_cfg)
