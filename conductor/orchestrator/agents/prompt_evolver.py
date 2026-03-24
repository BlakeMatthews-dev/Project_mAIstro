"""
Prompt Evolver — Cron-able self-improvement loop.

Runs periodically (e.g. daily) to:
1. Analyze variant performance across all recipes
2. Promote winners to 'production' label in Langfuse
3. Demote consistent losers (with human approval)
4. Suggest new prompt variants based on failure patterns

Safety rules:
- Never auto-demote without human approval (requires_approval=True)
- Promotion requires >5% improvement over 50+ runs
- All decisions logged to Langfuse as events for auditability

Integration:
  python -m orchestrator.agents.prompt_evolver --recipes-dir ./recipes
  Or via API: POST /v1/factory/evolve
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Literal

from pydantic import BaseModel

from .recipe import AgentRecipe, RecipeRegistry
from .variant_selector import VariantSelector

logger = logging.getLogger(__name__)

# Minimum improvement over production to justify promotion
_PROMOTION_THRESHOLD = 0.05  # 5%
# Minimum runs for a variant to be eligible for promotion
_MIN_RUNS_FOR_PROMOTION = 50
# Production success rate floor — flag for review if below this
_PRODUCTION_FLOOR = 0.70


class EvolutionResult(BaseModel):
    """Result of an evolution analysis for a single recipe."""

    recipe_name: str
    action: Literal["promote", "demote", "hold", "suggest_new"]
    from_variant: str | None = None
    to_variant: str | None = None
    confidence: float = 0.0
    evidence: str = ""
    requires_approval: bool = True


class PromptEvolver:
    """Reviews variant performance and promotes the best to 'production' label."""

    def __init__(
        self,
        variant_selector: VariantSelector,
        prompt_manager=None,
        langfuse_client=None,
        gateway_url: str = "http://localhost:8100",
    ) -> None:
        self._selector = variant_selector
        self._prompt_manager = prompt_manager
        self._lf = langfuse_client
        self._gateway_url = gateway_url

    def evolve(self, recipe: AgentRecipe) -> EvolutionResult:
        """Analyze variant performance and decide: promote, demote, hold, or suggest.

        Rules:
        1. If a challenger beats 'production' by >5% mean score over 50+ runs → promote
        2. If 'production' has <70% success rate over last 100 runs → flag for review
        3. Never demote without human approval (safety)
        4. Log all decisions to Langfuse as events
        """
        stats = self._selector.get_stats(recipe.prompt_name)

        if not stats:
            return EvolutionResult(
                recipe_name=recipe.name,
                action="hold",
                evidence="No variant stats available yet",
                requires_approval=False,
            )

        prod_stats = stats.get("production")
        if prod_stats is None:
            return EvolutionResult(
                recipe_name=recipe.name,
                action="hold",
                evidence="No 'production' variant stats found",
                requires_approval=False,
            )

        # Check if production is underperforming
        if prod_stats.runs >= _MIN_RUNS_FOR_PROMOTION:
            if prod_stats.success_rate < _PRODUCTION_FLOOR:
                # Production is struggling — find the best challenger
                best_challenger = None
                best_rate = 0.0

                for variant, vs in stats.items():
                    if variant == "production":
                        continue
                    if vs.runs >= _MIN_RUNS_FOR_PROMOTION and vs.success_rate > best_rate:
                        best_challenger = variant
                        best_rate = vs.success_rate

                if best_challenger and best_rate > prod_stats.success_rate + _PROMOTION_THRESHOLD:
                    result = EvolutionResult(
                        recipe_name=recipe.name,
                        action="promote",
                        from_variant="production",
                        to_variant=best_challenger,
                        confidence=min(1.0, (best_rate - prod_stats.success_rate) / 0.2),
                        evidence=(
                            f"Production success rate {prod_stats.success_rate:.1%} "
                            f"is below floor ({_PRODUCTION_FLOOR:.0%}). "
                            f"Challenger '{best_challenger}' has {best_rate:.1%} "
                            f"over {stats[best_challenger].runs} runs."
                        ),
                        requires_approval=True,
                    )
                    self._log_decision(result)
                    return result

                # No good challenger — suggest creating a new variant
                return EvolutionResult(
                    recipe_name=recipe.name,
                    action="suggest_new",
                    from_variant="production",
                    confidence=0.5,
                    evidence=(
                        f"Production success rate {prod_stats.success_rate:.1%} "
                        f"is below floor ({_PRODUCTION_FLOOR:.0%}). "
                        f"No challenger variant meets promotion threshold."
                    ),
                    requires_approval=True,
                )

        # Check if any challenger beats production
        for variant, vs in stats.items():
            if variant == "production":
                continue
            if vs.runs < _MIN_RUNS_FOR_PROMOTION:
                continue

            improvement = vs.success_rate - prod_stats.success_rate
            if improvement > _PROMOTION_THRESHOLD:
                result = EvolutionResult(
                    recipe_name=recipe.name,
                    action="promote",
                    from_variant="production",
                    to_variant=variant,
                    confidence=min(1.0, improvement / 0.2),
                    evidence=(
                        f"Variant '{variant}' ({vs.success_rate:.1%} success, "
                        f"{vs.runs} runs) beats production "
                        f"({prod_stats.success_rate:.1%} success, "
                        f"{prod_stats.runs} runs) by {improvement:.1%}."
                    ),
                    requires_approval=True,
                )
                self._log_decision(result)
                return result

        # No action needed
        return EvolutionResult(
            recipe_name=recipe.name,
            action="hold",
            evidence=(
                f"Production at {prod_stats.success_rate:.1%} success rate "
                f"over {prod_stats.runs} runs. No challenger exceeds "
                f"+{_PROMOTION_THRESHOLD:.0%} threshold."
            ),
            requires_approval=False,
        )

    async def suggest_new_variant(
        self,
        recipe: AgentRecipe,
        failure_patterns: list[str] | None = None,
    ) -> str | None:
        """Use an LLM to suggest a new prompt variant based on failure patterns.

        Inputs: current prompt text + common failure modes from TraceReviewer
        Output: suggested new prompt text (requires human approval before activation)
        """
        if not self._prompt_manager:
            return None

        # Get current production prompt
        current_prompt = self._prompt_manager.get_prompt(
            recipe.prompt_name, label="production"
        )
        if not current_prompt:
            return None

        # Build the meta-prompt for generating an improved variant
        failures_section = ""
        if failure_patterns:
            failures_section = (
                "\n## Common Failure Patterns\n"
                + "\n".join(f"- {p}" for p in failure_patterns)
            )

        meta_prompt = (
            "You are a prompt engineer. Your task is to improve the following "
            "system prompt based on observed failure patterns.\n\n"
            f"## Current Prompt\n```\n{current_prompt}\n```\n"
            f"{failures_section}\n\n"
            "## Instructions\n"
            "Write an improved version of the prompt that addresses the failure "
            "patterns while maintaining the original intent. Output ONLY the "
            "improved prompt text, no explanation."
        )

        # Call gateway to generate the suggestion
        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._gateway_url}/v1/chat/completions",
                    json={
                        "model": "auto",
                        "messages": [{"role": "user", "content": meta_prompt}],
                        "max_tokens": 2048,
                        "temperature": 0.7,
                    },
                    headers={
                        "Authorization": f"Bearer {os.environ.get('ROUTER_API_KEY', '')}",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
        except Exception as exc:
            logger.warning("Failed to generate prompt suggestion: %s", exc)

        return None

    def promote_variant(
        self,
        recipe: AgentRecipe,
        from_label: str,
    ) -> bool:
        """Promote a variant's content to the 'production' label.

        Copies the variant's prompt text to a new Langfuse prompt version
        with the 'production' label. The old production prompt remains in
        version history for rollback.
        """
        if not self._prompt_manager:
            logger.warning("No PromptManager — cannot promote")
            return False

        try:
            self._prompt_manager.promote_variant(
                recipe.prompt_name, from_label=from_label
            )
            logger.info(
                "Promoted variant '%s' to production for %s",
                from_label, recipe.prompt_name,
            )
            self._log_event(
                f"Promoted '{from_label}' → 'production' for {recipe.prompt_name}"
            )
            return True
        except Exception as exc:
            logger.error("Promotion failed for %s: %s", recipe.prompt_name, exc)
            return False

    def evolve_all(self, registry: RecipeRegistry) -> list[EvolutionResult]:
        """Run evolution for all registered recipes."""
        results = []
        for recipe in registry.list_recipes():
            result = self.evolve(recipe)
            results.append(result)
            if result.action != "hold":
                logger.info(
                    "Evolution [%s] %s: %s → %s (confidence=%.2f)",
                    result.recipe_name, result.action,
                    result.from_variant, result.to_variant,
                    result.confidence,
                )
        return results

    def _log_decision(self, result: EvolutionResult) -> None:
        """Log an evolution decision to Langfuse."""
        if not self._lf:
            return
        try:
            trace = self._lf.trace(
                name="prompt-evolution",
                metadata={
                    "recipe": result.recipe_name,
                    "action": result.action,
                    "from_variant": result.from_variant,
                    "to_variant": result.to_variant,
                    "confidence": result.confidence,
                },
            )
            trace.event(
                name=f"evolution-{result.action}",
                metadata={"evidence": result.evidence},
            )
        except Exception as exc:
            logger.debug("Failed to log evolution decision: %s", exc)

    def _log_event(self, message: str) -> None:
        """Log a simple event to Langfuse."""
        if not self._lf:
            return
        try:
            self._lf.trace(
                name="prompt-evolution-event",
                metadata={"message": message},
            )
        except Exception as exc:
            logger.debug("Failed to log evolution event: %s", exc)


async def main():
    """CLI entrypoint for running evolution as a cron job."""
    parser = argparse.ArgumentParser(description="Conductor Prompt Evolver")
    parser.add_argument(
        "--recipes-dir",
        default="./orchestrator/agents/recipes",
        help="Directory containing recipe YAML files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only, don't promote",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    registry = RecipeRegistry(args.recipes_dir)
    selector = VariantSelector()  # Will use Langfuse if available
    evolver = PromptEvolver(variant_selector=selector)

    results = evolver.evolve_all(registry)

    logger.info(f"\nEvolution results for {len(results)} recipes:")
    for r in results:
        icon = {"promote": "+", "demote": "-", "hold": "=", "suggest_new": "?"}
        logger.info(f"  [{icon.get(r.action, '?')}] {r.recipe_name}: {r.action}")
        if r.evidence:
            logger.info(f"      {r.evidence}")
        if r.requires_approval:
            print("      *** Requires human approval ***")

    if not args.dry_run:
        promotions = [r for r in results if r.action == "promote"]
        if promotions:
            logger.info(f"\n{len(promotions)} promotion(s) pending approval.")
            print("Use POST /v1/factory/promote to apply.")


if __name__ == "__main__":
    asyncio.run(main())
