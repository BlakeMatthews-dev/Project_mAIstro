"""Agent definitions — specs, spawner, factory components, and specialized agents."""

from .agent_spec import RECOVERABLE_ERRORS, AgentOutput, AgentRole, AgentSpec, ErrorType, Lane
from .bouncer import Bouncer, BouncerResult, Verdict
from .prompt_evolver import EvolutionResult, PromptEvolver
from .recipe import AgentRecipe, RecipeRegistry
from .schemas import (
    CodeOutput,
    FileChange,
    PlanOutput,
    PlanSubtask,
    ReviewOutput,
    ReviewScores,
    resolve_schema,
)
from .spawner import Spawner
from .structured_output import StructuredOutputParser
from .variant_selector import VariantSelector, VariantStats

__all__ = [
    # Core
    "AgentSpec",
    "AgentOutput",
    "AgentRole",
    "ErrorType",
    "Lane",
    "RECOVERABLE_ERRORS",
    "Spawner",
    # Bouncer
    "Bouncer",
    "BouncerResult",
    "Verdict",
    # Factory
    "AgentRecipe",
    "RecipeRegistry",
    "VariantSelector",
    "VariantStats",
    "StructuredOutputParser",
    "PromptEvolver",
    "EvolutionResult",
    # Schemas
    "PlanOutput",
    "CodeOutput",
    "ReviewOutput",
    "ReviewScores",
    "PlanSubtask",
    "FileChange",
    "resolve_schema",
]
