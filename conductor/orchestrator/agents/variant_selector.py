"""
Variant Selector — Thompson Sampling over Langfuse scores.

Selects the best prompt variant for an agent recipe using Thompson sampling
(a Bayesian multi-armed bandit approach). Each variant maintains a Beta
distribution of success/failure, and we sample from each to decide which
variant to use for the next spawn.

Flow:
  1. Query Langfuse for historical scores per variant (cached with TTL)
  2. If too few samples: round-robin to gather data
  3. Otherwise: Thompson sample from Beta(successes+1, failures+1)
  4. With exploration_rate probability: random variant (prevent starvation)

The key insight: Thompson sampling naturally balances exploration and
exploitation without tuning an epsilon parameter. Early on, wide Beta
distributions cause frequent exploration. As data accumulates, the
distributions narrow and converge on the true best variant.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Score threshold: scores above this count as "success" for the Beta distribution
_SUCCESS_THRESHOLD = 7.0


class VariantStats(BaseModel):
    """Performance statistics for a single prompt variant."""

    variant: str
    runs: int = 0
    successes: int = 0       # scores >= threshold
    failures: int = 0        # scores < threshold
    mean_score: float = 0.0
    p95_score: float = 0.0
    success_rate: float = 0.0
    last_updated: datetime = datetime.now(timezone.utc)


class VariantSelector:
    """Selects the best prompt variant using Thompson sampling over Langfuse scores."""

    def __init__(
        self,
        langfuse_client=None,
        cache_ttl: int = 300,
        success_threshold: float = _SUCCESS_THRESHOLD,
    ) -> None:
        self._lf = langfuse_client
        self._cache: dict[str, dict[str, VariantStats]] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._cache_ttl = cache_ttl
        self._success_threshold = success_threshold
        # Round-robin counter for early exploration
        self._rr_counters: dict[str, int] = {}

    def select(self, recipe) -> str:
        """Return the prompt label to use for this spawn.

        Args:
            recipe: An AgentRecipe instance with prompt_name, prompt_variants,
                    min_samples_before_selection, and exploration_rate.

        Returns:
            The selected variant label string.
        """
        variants = recipe.prompt_variants
        if not variants:
            return "production"
        if len(variants) == 1:
            return variants[0]

        stats = self._get_stats(recipe.prompt_name)
        total_runs = sum(s.runs for s in stats.values())

        # Phase 1: Not enough data — round-robin to gather samples
        if total_runs < recipe.min_samples_before_selection:
            key = recipe.prompt_name
            idx = self._rr_counters.get(key, 0)
            self._rr_counters[key] = (idx + 1) % len(variants)
            selected = variants[idx % len(variants)]
            logger.debug(
                "Round-robin for %s: %s (run %d/%d)",
                recipe.prompt_name, selected, total_runs,
                recipe.min_samples_before_selection,
            )
            return selected

        # Phase 2: Exploration — random variant with exploration_rate probability
        if random.random() < recipe.exploration_rate:
            selected = random.choice(variants)
            logger.debug(
                "Exploration for %s: %s (exploration_rate=%.2f)",
                recipe.prompt_name, selected, recipe.exploration_rate,
            )
            return selected

        # Phase 3: Thompson sampling — sample from Beta distribution per variant
        best_sample = -1.0
        best_variant = variants[0]

        for variant in variants:
            vs = stats.get(variant)
            if vs is None or vs.runs == 0:
                # No data for this variant — give it a chance
                sample = random.random()
            else:
                # Beta(successes + 1, failures + 1) — the +1 is the uniform prior
                alpha = vs.successes + 1
                beta_param = vs.failures + 1
                sample = random.betavariate(alpha, beta_param)

            if sample > best_sample:
                best_sample = sample
                best_variant = variant

        logger.debug(
            "Thompson sampling for %s: %s (sample=%.3f)",
            recipe.prompt_name, best_variant, best_sample,
        )
        return best_variant

    def record_outcome(
        self,
        prompt_name: str,
        variant: str,
        score: float,
        *,
        trace_id: str | None = None,
    ) -> None:
        """Record a score for a variant. Called after the reviewer scores the output.

        Also records the score in Langfuse if a client is available.
        """
        # Update local cache
        stats = self._cache.setdefault(prompt_name, {})
        vs = stats.get(variant)
        if vs is None:
            vs = VariantStats(variant=variant)
            stats[variant] = vs

        vs.runs += 1
        is_success = score >= self._success_threshold
        if is_success:
            vs.successes += 1
        else:
            vs.failures += 1

        # Incremental mean update
        vs.mean_score = vs.mean_score + (score - vs.mean_score) / vs.runs
        vs.success_rate = vs.successes / vs.runs if vs.runs > 0 else 0.0
        vs.last_updated = datetime.now(timezone.utc)

        # Record in Langfuse
        if self._lf and trace_id:
            try:
                self._lf.score(
                    trace_id=trace_id,
                    name="variant_score",
                    value=score,
                    comment=f"variant={variant}",
                )
            except Exception as exc:
                logger.debug("Failed to record variant score in Langfuse: %s", exc)

    def get_stats(self, prompt_name: str) -> dict[str, VariantStats]:
        """Return current stats per variant (for dashboard/debugging)."""
        return dict(self._get_stats(prompt_name))

    def _get_stats(self, prompt_name: str) -> dict[str, VariantStats]:
        """Get cached stats, refreshing from Langfuse if stale."""
        now = time.monotonic()
        cache_ts = self._cache_timestamps.get(prompt_name, 0)

        if prompt_name in self._cache and (now - cache_ts) < self._cache_ttl:
            return self._cache[prompt_name]

        # Try to refresh from Langfuse
        if self._lf:
            try:
                self._refresh_from_langfuse(prompt_name)
                self._cache_timestamps[prompt_name] = now
            except Exception as exc:
                logger.debug("Failed to refresh stats from Langfuse: %s", exc)

        return self._cache.get(prompt_name, {})

    def _refresh_from_langfuse(self, prompt_name: str) -> None:
        """Fetch historical scores from Langfuse and rebuild stats.

        Queries for scores tagged with the prompt name, groups by variant
        label in the score comment/metadata.
        """
        if not self._lf:
            return

        try:
            # Fetch scores for this prompt — Langfuse SDK fetch_scores
            scores = self._lf.client.score.list(
                name="variant_score",
                page=1,
                limit=500,
            )

            stats: dict[str, VariantStats] = {}
            for score in scores.data:
                # Extract variant from comment (format: "variant=xxx")
                comment = score.comment or ""
                if not comment.startswith("variant="):
                    continue

                variant = comment.split("=", 1)[1]
                vs = stats.get(variant)
                if vs is None:
                    vs = VariantStats(variant=variant)
                    stats[variant] = vs

                vs.runs += 1
                if score.value >= self._success_threshold:
                    vs.successes += 1
                else:
                    vs.failures += 1

            # Compute derived stats
            for vs in stats.values():
                if vs.runs > 0:
                    vs.success_rate = vs.successes / vs.runs
                vs.last_updated = datetime.now(timezone.utc)

            self._cache[prompt_name] = stats

        except Exception as exc:
            logger.debug("Langfuse score fetch failed for %s: %s", prompt_name, exc)
