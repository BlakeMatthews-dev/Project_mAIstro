"""
Agent Recipe — Declarative agent definitions for A/B testing and evolution.

An AgentRecipe is a YAML-defined template that specifies:
- Which prompt to use (and which variants to A/B test)
- What typed output to expect (Pydantic model for validation)
- Model constraints (tier, temperature, max tokens)
- Evolution parameters (when to start Thompson sampling, exploration rate)

Recipes live as YAML files in `orchestrator/agents/recipes/` and are also
synced to Langfuse as prompt metadata. They're the unit of experimentation —
each recipe tracks its own variant performance independently.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .agent_spec import AgentRole

logger = logging.getLogger(__name__)

_DEFAULT_RECIPES_DIR = Path(__file__).parent / "recipes"


class AgentRecipe(BaseModel):
    """Declarative agent definition — the unit of A/B testing and evolution."""

    name: str                          # e.g. "coder.python", "planner.decompose"
    role: AgentRole
    description: str = ""              # human-readable purpose

    # Prompt template (Langfuse prompt name)
    prompt_name: str                   # e.g. "coder.generate"
    prompt_variants: list[str] = Field(
        default_factory=lambda: ["production"],
        description="Langfuse labels to A/B test",
    )

    # Typed output (Pydantic AI concept)
    result_schema: str | None = None   # dotted path, e.g. "schemas.CodeOutput"

    # Tool definitions
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names from the tool registry",
    )

    # Model constraints
    min_tier: int = 2
    max_tier: int = 4
    temperature: float = 0.7
    max_tokens: int = 4096

    # Evolution parameters
    min_samples_before_selection: int = 20
    exploration_rate: float = 0.1


class RecipeRegistry:
    """Loads and caches agent recipes from YAML files."""

    def __init__(self, recipes_dir: str | Path | None = None) -> None:
        self._dir = Path(recipes_dir) if recipes_dir else _DEFAULT_RECIPES_DIR
        self._cache: dict[str, AgentRecipe] = {}

    def get(self, name: str) -> AgentRecipe | None:
        """Get a recipe by name. Loads from cache or disk."""
        if name in self._cache:
            return self._cache[name]
        return self._load_from_disk(name)

    def list_recipes(self) -> list[AgentRecipe]:
        """Load and return all recipes from the recipes directory."""
        self._load_all()
        return list(self._cache.values())

    def register(self, recipe: AgentRecipe) -> None:
        """Register a recipe programmatically (e.g. from API)."""
        self._cache[recipe.name] = recipe

    def save(self, recipe: AgentRecipe) -> Path:
        """Save a recipe to YAML on disk."""
        self._dir.mkdir(parents=True, exist_ok=True)
        filename = recipe.name.replace(".", "_") + ".yaml"
        path = self._dir / filename
        data = recipe.model_dump(exclude_defaults=True)
        # AgentRole is a StrEnum — serialize as plain string
        data["role"] = recipe.role.value
        path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
        self._cache[recipe.name] = recipe
        return path

    def _load_from_disk(self, name: str) -> AgentRecipe | None:
        """Try to load a recipe YAML by name."""
        if not self._dir.exists():
            return None

        # Try exact match first: coder.python → coder_python.yaml
        filename = name.replace(".", "_") + ".yaml"
        path = self._dir / filename
        if path.exists():
            return self._parse_yaml(path)

        # Scan all files for matching name field
        for yaml_path in self._dir.glob("*.yaml"):
            recipe = self._parse_yaml(yaml_path)
            if recipe and recipe.name == name:
                return recipe

        return None

    def _load_all(self) -> None:
        """Load all YAML recipe files."""
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob("*.yaml")):
            self._parse_yaml(path)

    def _parse_yaml(self, path: Path) -> AgentRecipe | None:
        """Parse a single YAML file into an AgentRecipe."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not data or not isinstance(data, dict):
                return None
            recipe = AgentRecipe(**data)
            self._cache[recipe.name] = recipe
            return recipe
        except Exception as exc:
            logger.warning("Failed to parse recipe %s: %s", path, exc)
            return None
