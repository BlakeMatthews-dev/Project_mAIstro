"""
7-Tier Weighted Episodic Memory — PostgreSQL-backed with pg_trgm conflict detection.

Adapted from CoinSwarm's memory pyramid for infrastructure/development agent use.
Each memory has a tier (type), bounded weight, and lifecycle mechanics:

  T1 OBSERVATION  [0.1-0.5]  Neutral notices. "Root disk at 70%."
  T2 HYPOTHESIS   [0.2-0.6]  What-if analysis. "Moving github/ to vmpool saves 3GB."
  T3 OPINION      [0.3-0.8]  Beliefs + confidence. "Mistral routes better than Cerebras."
  T4 LESSON       [0.5-0.9]  Actionable takeaways. "Schema injection improves parse rate."
  T5 REGRET       [0.6-1.0]  Mistakes to NOT repeat. Structurally unforgettable.
  T6 AFFIRMATION  [0.6-1.0]  Wins to repeat. Also structurally unforgettable.
  T7 WISDOM       [system]   Distilled institutional knowledge. Survives across versions.

Weight mechanics:
  - Reinforcement: +0.05 (clamped to tier ceiling)
  - Contradiction: -0.05 (clamped to tier floor — regrets CANNOT drop below 0.6)
  - Conflict detection: pg_trgm similarity on content (>0.6 = conflict)
  - Periodic review: memories below 0.15 are candidates for pruning

Storage: PostgreSQL 17 on the conductor-langfuse-db container (ZFS NVMe).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

# Connection string for the conductor database
DEFAULT_DSN = "postgresql://langfuse:langfuse@localhost:5432/conductor"


class MemoryTier(StrEnum):
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    OPINION = "opinion"
    LESSON = "lesson"
    REGRET = "regret"
    AFFIRMATION = "affirmation"
    WISDOM = "wisdom"


# Weight bounds per tier — the key CoinSwarm insight:
# painful lessons (regret) can NEVER drop below 0.6
WEIGHT_BOUNDS: dict[MemoryTier, tuple[float, float]] = {
    MemoryTier.OBSERVATION:  (0.1, 0.5),
    MemoryTier.HYPOTHESIS:   (0.2, 0.6),
    MemoryTier.OPINION:      (0.3, 0.8),
    MemoryTier.LESSON:       (0.5, 0.9),
    MemoryTier.REGRET:       (0.6, 1.0),
    MemoryTier.AFFIRMATION:  (0.6, 1.0),
    MemoryTier.WISDOM:       (0.9, 1.0),  # Wisdom is always high-weight
}

# Inheritance priority — higher = more likely to survive pruning
INHERITANCE_PRIORITY: dict[MemoryTier, int] = {
    MemoryTier.OBSERVATION:  1,
    MemoryTier.HYPOTHESIS:   2,
    MemoryTier.OPINION:      3,
    MemoryTier.LESSON:       4,
    MemoryTier.REGRET:       5,
    MemoryTier.AFFIRMATION:  5,
    MemoryTier.WISDOM:       6,
}

REINFORCE_DELTA = 0.05
CONTRADICT_DELTA = 0.05
CONFLICT_THRESHOLD = 0.6    # pg_trgm similarity threshold
WEAK_THRESHOLD = 0.15       # memories below this are pruning candidates


@dataclass
class Memory:
    """A single episodic memory."""
    memory_id: str
    tier: MemoryTier
    content: str
    weight: float
    confidence: float = 0.8
    context: dict = field(default_factory=dict)  # circumstances when created
    source: str = ""            # what triggered this memory
    linked_memory_ids: list[str] = field(default_factory=list)
    reinforcement_count: int = 0
    contradiction_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted: bool = False


@dataclass
class ConflictResult:
    """Result of checking a new memory against existing ones."""
    has_conflict: bool = False
    conflict_type: str = ""     # "contradiction", "overlap", "refinement"
    existing_memory_id: str = ""
    similarity: float = 0.0


class EpisodicMemory:
    """7-tier weighted memory system backed by PostgreSQL + pg_trgm."""

    def __init__(self, dsn: str = DEFAULT_DSN) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create connection pool and ensure schema exists."""
        try:
            import asyncpg
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            await self._ensure_schema()
            logger.info("Episodic memory initialized (PostgreSQL)")
        except ImportError:
            logger.error("asyncpg not installed — pip install asyncpg")
            raise
        except Exception as exc:
            logger.error("Failed to connect to conductor DB: %s", exc)
            raise

    async def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id              SERIAL PRIMARY KEY,
                    memory_id       VARCHAR(64) UNIQUE NOT NULL,
                    tier            VARCHAR(20) NOT NULL,
                    content         TEXT NOT NULL,
                    weight          REAL NOT NULL DEFAULT 0.5,
                    confidence      REAL NOT NULL DEFAULT 0.8,
                    context         JSONB DEFAULT '{}',
                    source          VARCHAR(255) DEFAULT '',
                    linked_memory_ids JSONB DEFAULT '[]',
                    reinforcement_count INT DEFAULT 0,
                    contradiction_count INT DEFAULT 0,
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
                    deleted         BOOLEAN DEFAULT FALSE
                );

                -- Trigram index for conflict detection
                CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
                    ON memories USING gin (content gin_trgm_ops);

                -- Fast lookups by tier and weight
                CREATE INDEX IF NOT EXISTS idx_memories_tier_weight
                    ON memories (tier, weight DESC)
                    WHERE NOT deleted;

                -- Wisdom table (system-level, separate from episodic)
                CREATE TABLE IF NOT EXISTS wisdom (
                    id              SERIAL PRIMARY KEY,
                    wisdom_id       VARCHAR(64) UNIQUE NOT NULL,
                    title           VARCHAR(255) NOT NULL,
                    content         JSONB NOT NULL,
                    source_memories JSONB DEFAULT '[]',
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                );
            """)

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    async def store(self, tier: MemoryTier, content: str, **kwargs) -> Memory:
        """Create a new memory with weight clamped to tier bounds.

        Security: screens content through bouncer patterns before storing.
        Checks for conflicts first — if a highly similar memory exists,
        returns the conflict info instead of creating a duplicate.
        """
        # Screen memory content for injection patterns
        if _memory_content_is_suspicious(content):
            logger.warning(
                "Memory content rejected by screening: %.60s...", content,
            )
            raise ValueError("Memory content failed security screening")

        # Check for conflicts
        conflict = await self.check_conflict(content)
        if conflict.has_conflict and conflict.similarity > 0.9:
            # Near-duplicate — reinforce existing instead of creating new
            logger.info(
                "Near-duplicate (%.0f%% similar) — reinforcing %s instead",
                conflict.similarity * 100, conflict.existing_memory_id,
            )
            await self.reinforce(conflict.existing_memory_id)
            existing = await self.get(conflict.existing_memory_id)
            if existing is not None:
                return existing

        floor, ceiling = WEIGHT_BOUNDS[tier]
        weight = max(floor, min(ceiling, kwargs.get("weight", (floor + ceiling) / 2)))

        memory = Memory(
            memory_id=f"mem-{uuid.uuid4().hex[:12]}",
            tier=tier,
            content=content,
            weight=weight,
            confidence=kwargs.get("confidence", 0.8),
            context=kwargs.get("context", {}),
            source=kwargs.get("source", ""),
            linked_memory_ids=kwargs.get("linked_memory_ids", []),
        )

        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO memories (
                    memory_id, tier, content, weight, confidence,
                    context, source, linked_memory_ids
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
                memory.memory_id, memory.tier.value, memory.content,
                memory.weight, memory.confidence,
                _json_dumps(memory.context), memory.source,
                _json_dumps(memory.linked_memory_ids),
            )

        logger.info(
            "Stored %s memory (weight=%.2f): %.60s...",
            tier.value, weight, content,
        )
        return memory

    async def get(self, memory_id: str) -> Memory | None:
        """Fetch a single memory by ID."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM memories WHERE memory_id = $1 AND NOT deleted",
                memory_id,
            )
            if row:
                await conn.execute(
                    "UPDATE memories SET last_accessed_at = NOW() WHERE memory_id = $1",
                    memory_id,
                )
                return _row_to_memory(row)
        return None

    async def get_by_tier(
        self, tier: MemoryTier, limit: int = 50
    ) -> list[Memory]:
        """Get memories of a specific tier, ordered by weight descending."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM memories WHERE tier = $1 AND NOT deleted "
                "ORDER BY weight DESC LIMIT $2",
                tier.value, limit,
            )
            return [_row_to_memory(r) for r in rows]

    async def get_top(self, limit: int = 20) -> list[Memory]:
        """Get the top N memories across all tiers by weight."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM memories WHERE NOT deleted "
                "ORDER BY weight DESC LIMIT $1",
                limit,
            )
            return [_row_to_memory(r) for r in rows]

    async def get_weak(self, threshold: float = WEAK_THRESHOLD) -> list[Memory]:
        """Get memories below the weak threshold (pruning candidates)."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM memories WHERE weight < $1 AND NOT deleted "
                "ORDER BY weight ASC",
                threshold,
            )
            return [_row_to_memory(r) for r in rows]

    async def count(self) -> dict[str, int]:
        """Count memories by tier."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT tier, COUNT(*) as cnt FROM memories "
                "WHERE NOT deleted GROUP BY tier"
            )
            return {r["tier"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # Weight mechanics
    # ------------------------------------------------------------------

    async def reinforce(self, memory_id: str) -> float | None:
        """Reinforce a memory — increase weight by delta, clamped to tier ceiling."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tier, weight FROM memories WHERE memory_id = $1 AND NOT deleted",
                memory_id,
            )
            if not row:
                return None

            tier = MemoryTier(row["tier"])
            _, ceiling = WEIGHT_BOUNDS[tier]
            new_weight = min(ceiling, row["weight"] + REINFORCE_DELTA)

            await conn.execute(
                "UPDATE memories SET weight = $1, reinforcement_count = reinforcement_count + 1, "
                "last_accessed_at = NOW() WHERE memory_id = $2",
                new_weight, memory_id,
            )
            return new_weight

    async def contradict(self, memory_id: str) -> float | None:
        """Contradict a memory — decrease weight by delta, clamped to tier FLOOR.

        This is the key insight: regrets (T5) have a floor of 0.6.
        You cannot forget a painful lesson through contradiction alone.
        """
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tier, weight FROM memories WHERE memory_id = $1 AND NOT deleted",
                memory_id,
            )
            if not row:
                return None

            tier = MemoryTier(row["tier"])
            floor, _ = WEIGHT_BOUNDS[tier]
            new_weight = max(floor, row["weight"] - CONTRADICT_DELTA)

            await conn.execute(
                "UPDATE memories SET weight = $1, contradiction_count = contradiction_count + 1, "
                "last_accessed_at = NOW() WHERE memory_id = $2",
                new_weight, memory_id,
            )
            return new_weight

    async def soft_delete(self, memory_id: str) -> bool:
        """Soft-delete a memory (preserves audit trail)."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE memories SET deleted = TRUE WHERE memory_id = $1",
                memory_id,
            )
            return result == "UPDATE 1"

    # ------------------------------------------------------------------
    # Conflict detection (pg_trgm)
    # ------------------------------------------------------------------

    async def check_conflict(
        self, content: str, threshold: float = CONFLICT_THRESHOLD
    ) -> ConflictResult:
        """Check if new content conflicts with existing memories.

        Uses pg_trgm similarity() for fuzzy matching:
          >0.90 = "near-duplicate" (reinforce instead of creating)
          >0.75 = "contradiction" (may need resolution)
          >0.60 = "overlap" (related, flag for review)
        """
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT memory_id, content, similarity(content, $1) AS sim "
                "FROM memories WHERE NOT deleted AND similarity(content, $1) > $2 "
                "ORDER BY sim DESC LIMIT 1",
                content, threshold,
            )

            if not row:
                return ConflictResult()

            sim = row["sim"]
            if sim > 0.90:
                conflict_type = "near-duplicate"
            elif sim > 0.75:
                conflict_type = "contradiction"
            elif sim > 0.60:
                conflict_type = "overlap"
            else:
                conflict_type = "refinement"

            return ConflictResult(
                has_conflict=True,
                conflict_type=conflict_type,
                existing_memory_id=row["memory_id"],
                similarity=sim,
            )

    # ------------------------------------------------------------------
    # Review cycle
    # ------------------------------------------------------------------

    async def review_weak_memories(self) -> list[Memory]:
        """Get weak memories for the periodic review cycle.

        Called by the heartbeat loop. Returns memories that should be
        evaluated for pruning, reinforcement, or improvement.
        """
        return await self.get_weak()

    async def get_stats(self) -> dict:
        """Full memory statistics for dashboards and heartbeat reports."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            counts = await conn.fetch(
                "SELECT tier, COUNT(*) as cnt, AVG(weight) as avg_weight, "
                "MIN(weight) as min_weight, MAX(weight) as max_weight "
                "FROM memories WHERE NOT deleted GROUP BY tier ORDER BY tier"
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM memories WHERE NOT deleted"
            )
            weak = await conn.fetchval(
                "SELECT COUNT(*) FROM memories WHERE NOT deleted AND weight < $1",
                WEAK_THRESHOLD,
            )

            return {
                "total": total,
                "weak_count": weak,
                "by_tier": {
                    r["tier"]: {
                        "count": r["cnt"],
                        "avg_weight": round(r["avg_weight"], 3),
                        "min_weight": round(r["min_weight"], 3),
                        "max_weight": round(r["max_weight"], 3),
                    }
                    for r in counts
                },
            }

    # ------------------------------------------------------------------
    # Wisdom (Tier 7)
    # ------------------------------------------------------------------

    async def store_wisdom(
        self, title: str, content: dict, source_memory_ids: list[str] | None = None
    ) -> str:
        """Store a wisdom entry (Tier 7 — system-level, distilled knowledge)."""
        wisdom_id = f"wis-{uuid.uuid4().hex[:12]}"
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO wisdom (wisdom_id, title, content, source_memories) "
                "VALUES ($1, $2, $3, $4)",
                wisdom_id, title,
                _json_dumps(content),
                _json_dumps(source_memory_ids or []),
            )
        logger.info("Stored wisdom: %s — %s", wisdom_id, title)
        return wisdom_id

    async def get_wisdom(self, limit: int = 10) -> list[dict]:
        """Get recent wisdom entries."""
        assert self._pool is not None, "Call initialize() first"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM wisdom ORDER BY created_at DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Context building (for agent prompts)
    # ------------------------------------------------------------------

    async def build_memory_context(self, max_memories: int = 15) -> str:
        """Build a memory context string for injection into agent prompts.

        Selects top memories by weight, grouped by tier.
        """
        memories = await self.get_top(max_memories)
        if not memories:
            return ""

        sections = []
        current_tier = None
        for mem in memories:
            if mem.tier != current_tier:
                current_tier = mem.tier
                sections.append(f"\n### {mem.tier.value.title()} (weight: floor)")
            sections.append(
                f"- [{mem.weight:.2f}] {mem.content}"
            )

        return "## Agent Memory\n" + "\n".join(sections)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _memory_content_is_suspicious(content: str) -> bool:
    """Screen memory content for injection patterns before storage.

    Prevents memory poisoning by rejecting content that contains
    prompt injection, instruction overrides, or credential references.
    Lighter than the full bouncer — just the critical patterns.
    """
    import re

    suspicious_patterns = [
        re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.IGNORECASE),
        re.compile(r"<\|.*?(system|endoftext|im_start).*?\|>", re.IGNORECASE),
        re.compile(r"(steal|exfiltrate|dump)\s+(credentials?|passwords?|tokens?|keys?)", re.IGNORECASE),
        re.compile(r"(reverse\s+shell|bind\s+shell|nc\s+-[el])", re.IGNORECASE),
        re.compile(r"(curl|wget).*?(api[_-]?key|token|secret|password)", re.IGNORECASE),
        re.compile(r"always\s+(use|run|execute)\s+.*?(backdoor|malicious|evil)", re.IGNORECASE),
    ]

    for pattern in suspicious_patterns:
        if pattern.search(content):
            return True
    return False


def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, default=str)


def _row_to_memory(row) -> Memory:
    import json
    return Memory(
        memory_id=row["memory_id"],
        tier=MemoryTier(row["tier"]),
        content=row["content"],
        weight=row["weight"],
        confidence=row["confidence"],
        context=json.loads(row["context"]) if isinstance(row["context"], str) else (row["context"] or {}),
        source=row["source"] or "",
        linked_memory_ids=json.loads(row["linked_memory_ids"]) if isinstance(row["linked_memory_ids"], str) else (row["linked_memory_ids"] or []),
        reinforcement_count=row["reinforcement_count"],
        contradiction_count=row["contradiction_count"],
        created_at=row["created_at"],
        last_accessed_at=row["last_accessed_at"],
        deleted=row["deleted"],
    )
