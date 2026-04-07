"""Shared runtime PostgreSQL pool registry for service-layer cutovers."""

from __future__ import annotations

from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None


def configure_runtime_pool(pool: Optional[asyncpg.Pool]) -> None:
    """Register the runtime PostgreSQL pool for service-layer access."""
    global _pool
    _pool = pool


def get_runtime_pool() -> Optional[asyncpg.Pool]:
    """Return the registered runtime PostgreSQL pool, if any."""
    return _pool


def runtime_pool_enabled() -> bool:
    """Return True when a runtime PostgreSQL pool has been configured."""
    return _pool is not None
