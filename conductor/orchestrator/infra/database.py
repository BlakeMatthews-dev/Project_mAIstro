"""
Database Interface — Tenant-scoped PostgreSQL with connection pooling.

All database operations are scoped to the current tenant. In homelab mode,
there's one schema ("public"). In multi-tenant mode, each tenant gets its
own PG schema — complete isolation with shared infrastructure.

Connection string: CONDUCTOR_DATABASE_URL env var.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

DEFAULT_DSN = os.environ.get(
    "CONDUCTOR_DATABASE_URL",
    "postgresql://langfuse:langfuse@localhost:5432/conductor",
)


class Database:
    """Tenant-aware database connection pool."""

    def __init__(self, dsn: str = DEFAULT_DSN) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create connection pool and ensure base schema exists."""
        import asyncpg
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        logger.info("Database pool created: %s", self._dsn.split("@")[-1])

    async def ensure_tenant_schema(self, schema: str = "public") -> None:
        """Create tenant schema and tables if they don't exist.

        In multi-tenant mode, each tenant gets its own PG schema.
        In homelab mode, everything is in 'public'.
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if schema != "public":
                await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

            # Set search path for this connection
            await conn.execute(f'SET search_path TO "{schema}", public')

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id                  SERIAL PRIMARY KEY,
                    memory_id           VARCHAR(64) UNIQUE NOT NULL,
                    tenant_id           VARCHAR(255) NOT NULL DEFAULT 'homelab',
                    tier                VARCHAR(20) NOT NULL,
                    content             TEXT NOT NULL,
                    weight              REAL NOT NULL DEFAULT 0.5,
                    confidence          REAL NOT NULL DEFAULT 0.8,
                    context             JSONB DEFAULT '{}',
                    source              VARCHAR(255) DEFAULT '',
                    linked_memory_ids   JSONB DEFAULT '[]',
                    reinforcement_count INT DEFAULT 0,
                    contradiction_count INT DEFAULT 0,
                    created_at          TIMESTAMPTZ DEFAULT NOW(),
                    last_accessed_at    TIMESTAMPTZ DEFAULT NOW(),
                    deleted             BOOLEAN DEFAULT FALSE
                );

                CREATE INDEX IF NOT EXISTS idx_memories_tenant
                    ON memories (tenant_id) WHERE NOT deleted;
                CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
                    ON memories USING gin (content gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS idx_memories_tier_weight
                    ON memories (tier, weight DESC) WHERE NOT deleted;

                CREATE TABLE IF NOT EXISTS wisdom (
                    id              SERIAL PRIMARY KEY,
                    wisdom_id       VARCHAR(64) UNIQUE NOT NULL,
                    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'homelab',
                    title           VARCHAR(255) NOT NULL,
                    content         JSONB NOT NULL,
                    source_memories JSONB DEFAULT '[]',
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS task_progress (
                    id              SERIAL PRIMARY KEY,
                    task_id         VARCHAR(64) NOT NULL,
                    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'homelab',
                    filename        VARCHAR(255) NOT NULL,
                    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
                    current_step    VARCHAR(255) DEFAULT '',
                    steps_total     INT DEFAULT 0,
                    steps_completed INT DEFAULT 0,
                    started_at      TIMESTAMPTZ DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ DEFAULT NOW(),
                    completed_at    TIMESTAMPTZ,
                    details         JSONB DEFAULT '{}',
                    error           TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_progress_tenant
                    ON task_progress (tenant_id, status);

                CREATE TABLE IF NOT EXISTS arena_results (
                    id              SERIAL PRIMARY KEY,
                    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'homelab',
                    model           VARCHAR(255) NOT NULL,
                    provider        VARCHAR(100) DEFAULT '',
                    task_type       VARCHAR(50) NOT NULL,
                    score           REAL NOT NULL,
                    success         BOOLEAN NOT NULL,
                    tokens_used     INT DEFAULT 0,
                    latency_ms      REAL DEFAULT 0,
                    task_id         VARCHAR(64) DEFAULT '',
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_arena_tenant
                    ON arena_results (tenant_id, model, task_type);
            """)

        logger.info("Tenant schema ready: %s", schema)

    async def acquire(self):
        """Acquire a connection from the pool."""
        assert self._pool is not None
        return self._pool.acquire()

    async def execute(self, query: str, *args):
        """Execute a query."""
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args):
        """Fetch rows."""
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        """Fetch a single row."""
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        """Fetch a single value."""
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("Database pool closed")
