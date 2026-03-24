"""
Dream Loop — Idle-time memory consolidation and counterfactual reasoning.

When no tasks are pending and the heartbeat fires, the conductor enters
"dream mode" — it reviews its episodic memories, generates counterfactual
scenarios, tests hypotheses, and consolidates learning.

Dream activities:
1. Memory Consolidation — reinforce strong memories, prune weak ones
2. Counterfactual Generation — "what if I had used variant X for task Y?"
3. Hypothesis Testing — check opinions against accumulated evidence
4. Wisdom Distillation — promote recurring lessons to T7 wisdom
5. Pattern Discovery — find correlations across memories

The dream loop runs inside the heartbeat when the task queue is empty.
It uses the routing LLM (cheap, fast) not the coding LLM.
"""

from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)


class DreamLoop:
    """Idle-time memory consolidation — the agent gets smarter while you sleep."""

    def __init__(
        self,
        episodic_memory=None,
        board=None,
        evolution=None,
        gateway_url: str = "http://localhost:9090",
    ) -> None:
        self._memory = episodic_memory
        self._board = board
        self._evolution = evolution
        self._gateway_url = gateway_url
        self._dream_count = 0

    async def dream(self) -> dict:
        """Run one dream cycle. Returns a summary of what happened."""
        if not self._memory:
            return {"dreamed": False, "reason": "no memory system"}

        self._dream_count += 1
        results = {
            "dream_number": self._dream_count,
            "consolidated": 0,
            "pruned": 0,
            "counterfactuals": 0,
            "wisdom_candidates": 0,
        }

        # 1. Memory consolidation — reinforce strong, prune weak
        consolidated, pruned = await self._consolidate()
        results["consolidated"] = consolidated
        results["pruned"] = pruned

        # 2. Counterfactual generation (every 3rd dream)
        if self._dream_count % 3 == 0:
            counterfactuals = await self._generate_counterfactuals()
            results["counterfactuals"] = counterfactuals

        # 3. Wisdom distillation (every 10th dream)
        if self._dream_count % 10 == 0:
            wisdom = await self._distill_wisdom()
            results["wisdom_candidates"] = wisdom

        # Log the dream
        if self._evolution:
            self._evolution.record_mutation(
                surface="dream",
                action="cycle",
                description=(
                    f"Dream #{self._dream_count}: "
                    f"consolidated={consolidated}, pruned={pruned}, "
                    f"counterfactuals={results['counterfactuals']}"
                ),
                details=results,
            )

        logger.info(
            "Dream #%d: consolidated=%d, pruned=%d, counterfactuals=%d",
            self._dream_count, consolidated, pruned, results["counterfactuals"],
        )
        return results

    async def _consolidate(self) -> tuple[int, int]:
        """Review memories by weight and reinforce/prune."""
        from ...memory.episodic import WEAK_THRESHOLD, MemoryTier

        consolidated = 0
        pruned = 0

        # Get weak memories
        weak = await self._memory.get_weak(WEAK_THRESHOLD)
        for mem in weak:
            # Observations below floor with no reinforcement → prune
            if mem.tier == MemoryTier.OBSERVATION and mem.reinforcement_count == 0:
                await self._memory.soft_delete(mem.memory_id)
                pruned += 1
            # Hypotheses that were never tested → prune
            elif mem.tier == MemoryTier.HYPOTHESIS and mem.reinforcement_count == 0 and mem.contradiction_count == 0:
                await self._memory.soft_delete(mem.memory_id)
                pruned += 1

        # Get strong memories and reinforce ones that have been accessed recently
        from ...memory.episodic import MemoryTier
        for tier in (MemoryTier.LESSON, MemoryTier.REGRET, MemoryTier.AFFIRMATION):
            memories = await self._memory.get_by_tier(tier, limit=20)
            for mem in memories:
                # Reinforce memories with high reinforcement counts
                if mem.reinforcement_count >= 3 and mem.contradiction_count == 0:
                    await self._memory.reinforce(mem.memory_id)
                    consolidated += 1

        return consolidated, pruned

    async def _generate_counterfactuals(self) -> int:
        """Generate "what if" memories from recent task outcomes.

        Uses the routing LLM to imagine alternate outcomes.
        """
        from ...memory.episodic import MemoryTier

        # Get recent regrets and lessons
        regrets = await self._memory.get_by_tier(MemoryTier.REGRET, limit=5)
        if not regrets:
            return 0

        # Pick a random regret to reason about
        regret = random.choice(regrets)

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._gateway_url}/v1/chat/completions",
                    json={
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are analyzing a past decision that went wrong. "
                                    "Generate a brief counterfactual: what could have been "
                                    "done differently, and what the likely outcome would have been. "
                                    "Be specific and actionable. One paragraph max."
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"Past regret: {regret.content}",
                            },
                        ],
                        "max_tokens": 256,
                        "temperature": 0.8,
                    },
                )
                resp.raise_for_status()
                counterfactual = resp.json()["choices"][0]["message"]["content"]

            # Store as a hypothesis
            await self._memory.store(
                MemoryTier.HYPOTHESIS,
                f"Counterfactual from dream #{self._dream_count}: {counterfactual}",
                source=f"dream/counterfactual/{regret.memory_id}",
                linked_memory_ids=[regret.memory_id],
            )
            return 1

        except Exception as exc:
            logger.debug("Counterfactual generation failed: %s", exc)
            return 0

    async def _distill_wisdom(self) -> int:
        """Check if any lessons have been reinforced enough to become wisdom.

        A lesson that's been reinforced 5+ times with zero contradictions
        is a strong candidate for T7 wisdom.
        """
        from ...memory.episodic import MemoryTier

        lessons = await self._memory.get_by_tier(MemoryTier.LESSON, limit=50)
        candidates = [
            m for m in lessons
            if m.reinforcement_count >= 5 and m.contradiction_count == 0
        ]

        if not candidates and self._board:
            return 0

        for candidate in candidates[:3]:  # Max 3 wisdom promotions per dream
            await self._memory.store_wisdom(
                title=f"Distilled from lesson {candidate.memory_id}",
                content={
                    "lesson": candidate.content,
                    "reinforcements": candidate.reinforcement_count,
                    "weight": candidate.weight,
                    "source": candidate.source,
                },
                source_memory_ids=[candidate.memory_id],
            )

            if self._board:
                self._board.observation(
                    f"Wisdom distilled: {candidate.content[:60]}...",
                    f"Lesson reinforced {candidate.reinforcement_count} times with zero "
                    f"contradictions. Promoted to T7 wisdom.\n\n"
                    f"**Full content:** {candidate.content}",
                    source="dream/wisdom-distill",
                )

        return len(candidates[:3])
