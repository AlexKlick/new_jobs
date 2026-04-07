"""asyncpg connection pool management."""

import os
from typing import Optional

import asyncpg

_DEFAULT_DSN = "postgresql://localhost/denjobs"


def _dsn() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_DSN)


async def create_pool(
    min_size: int = 2,
    max_size: int = 10,
) -> asyncpg.Pool:
    """Create an asyncpg connection pool.

    Uses DATABASE_URL env var if set, otherwise defaults to
    ``postgresql://localhost/denjobs``.
    """
    return await asyncpg.create_pool(
        dsn=_dsn(),
        min_size=min_size,
        max_size=max_size,
    )


async def close_pool(pool: Optional[asyncpg.Pool]) -> None:
    """Gracefully close a connection pool."""
    if pool is not None:
        await pool.close()
