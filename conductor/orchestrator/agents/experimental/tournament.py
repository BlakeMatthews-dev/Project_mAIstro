"""
Model Tournament Arena — Private leaderboard from real task outcomes.

Every task the conductor processes generates a data point: which model was
used, what task type it was, and whether it succeeded (reviewer score).
Over time, this builds a leaderboard that's specific to YOUR workload —
not a generic benchmark.

The arena integrates with:
- Variant Selector (Thompson sampling) — already picks best prompt variants
- Router scoring (conductor-router) — already picks models by quality/cost
- This module adds: per-model, per-task-type win rate tracking

Data flows:
  Task completed → reviewer scores it → arena records (model, task_type, score)
  Arena periodically computes rankings → feeds back into routing decisions

Storage: PostgreSQL (conductor database, same as episodic memory)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

DEFAULT_DSN = "postgresql://langfuse:langfuse@localhost:5432/conductor"


class ModelArena:
    """Tracks per-model, per-task-type performance from real task outcomes."""

    def __init__(self, dsn: str = DEFAULT_DSN) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        import asyncpg
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=3)
        await self._ensure_schema()
        logger.info("Model Arena initialized")

    async def _ensure_schema(self) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS arena_results (
                    id              SERIAL PRIMARY KEY,
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
                CREATE INDEX IF NOT EXISTS idx_arena_model_task
                    ON arena_results (model, task_type);
            """)

    async def record(
        self,
        model: str,
        task_type: str,
        score: float,
        *,
        provider: str = "",
        tokens_used: int = 0,
        latency_ms: float = 0,
        task_id: str = "",
        success_threshold: float = 7.0,
    ) -> None:
        """Record a task outcome for a model."""
        if not self._pool:
            return
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO arena_results "
                "(model, provider, task_type, score, success, tokens_used, latency_ms, task_id) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                model, provider, task_type, score,
                score >= success_threshold,
                tokens_used, latency_ms, task_id,
            )

    async def leaderboard(
        self, task_type: str | None = None, min_runs: int = 5
    ) -> list[dict]:
        """Get model rankings, optionally filtered by task type.

        Returns models sorted by win rate, with enough runs for statistical
        significance (min_runs threshold).
        """
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            if task_type:
                rows = await conn.fetch("""
                    SELECT model, provider, task_type,
                           COUNT(*) as runs,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END) as wins,
                           ROUND(AVG(score)::numeric, 2) as avg_score,
                           ROUND(AVG(latency_ms)::numeric, 0) as avg_latency_ms,
                           ROUND(AVG(tokens_used)::numeric, 0) as avg_tokens
                    FROM arena_results
                    WHERE task_type = $1
                    GROUP BY model, provider, task_type
                    HAVING COUNT(*) >= $2
                    ORDER BY AVG(score) DESC
                """, task_type, min_runs)
            else:
                rows = await conn.fetch("""
                    SELECT model, provider, 'all' as task_type,
                           COUNT(*) as runs,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END) as wins,
                           ROUND(AVG(score)::numeric, 2) as avg_score,
                           ROUND(AVG(latency_ms)::numeric, 0) as avg_latency_ms,
                           ROUND(AVG(tokens_used)::numeric, 0) as avg_tokens
                    FROM arena_results
                    GROUP BY model, provider
                    HAVING COUNT(*) >= $1
                    ORDER BY AVG(score) DESC
                """, min_runs)

            return [
                {
                    "rank": i + 1,
                    "model": r["model"],
                    "provider": r["provider"],
                    "task_type": r["task_type"],
                    "runs": r["runs"],
                    "wins": r["wins"],
                    "win_rate": round(r["wins"] / r["runs"], 3) if r["runs"] > 0 else 0,
                    "avg_score": float(r["avg_score"]),
                    "avg_latency_ms": float(r["avg_latency_ms"]),
                    "avg_tokens": int(r["avg_tokens"]),
                }
                for i, r in enumerate(rows)
            ]

    async def head_to_head(self, model_a: str, model_b: str) -> dict:
        """Compare two models head-to-head across all task types."""
        if not self._pool:
            return {}

        async with self._pool.acquire() as conn:
            stats = {}
            for model in (model_a, model_b):
                rows = await conn.fetch("""
                    SELECT task_type,
                           COUNT(*) as runs,
                           ROUND(AVG(score)::numeric, 2) as avg_score,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END) as wins
                    FROM arena_results
                    WHERE model = $1
                    GROUP BY task_type
                """, model)
                stats[model] = {
                    r["task_type"]: {
                        "runs": r["runs"],
                        "avg_score": float(r["avg_score"]),
                        "win_rate": round(r["wins"] / r["runs"], 3) if r["runs"] > 0 else 0,
                    }
                    for r in rows
                }

            return {
                "model_a": model_a,
                "model_b": model_b,
                "stats_a": stats.get(model_a, {}),
                "stats_b": stats.get(model_b, {}),
            }

    async def get_stats(self) -> dict:
        """Overall arena statistics."""
        if not self._pool:
            return {}

        async with self._pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM arena_results")
            models = await conn.fetchval("SELECT COUNT(DISTINCT model) FROM arena_results")
            task_types = await conn.fetchval("SELECT COUNT(DISTINCT task_type) FROM arena_results")
            return {
                "total_results": total,
                "unique_models": models,
                "unique_task_types": task_types,
            }

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
