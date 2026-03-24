"""
Shared output schemas for typed agent results.

These Pydantic models define the expected JSON structure returned by agents.
When a recipe specifies `result_schema`, the StructuredOutputParser injects
the schema into the system prompt and validates the response against it.

Inspired by Pydantic AI's typed result concept — declare your output shape
upfront so the system can validate, retry, and score structurally.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanOutput(BaseModel):
    """Structured output from the planner agent."""

    subtasks: list[PlanSubtask] = Field(
        description="Ordered list of subtasks to execute",
    )
    reasoning: str = Field(
        default="",
        description="Brief explanation of the decomposition strategy",
    )
    estimated_tiers: list[int] = Field(
        default_factory=list,
        description="Suggested tier for each subtask (parallel to subtasks list)",
    )


class PlanSubtask(BaseModel):
    """A single subtask in a plan."""

    id: str = Field(description="Unique subtask identifier, e.g. 'step-1'")
    description: str = Field(description="What this subtask should accomplish")
    depends_on: list[str] = Field(
        default_factory=list,
        description="IDs of subtasks that must complete before this one",
    )
    agent_role: str = Field(
        default="coder",
        description="Which agent role should handle this subtask",
    )


# Forward ref resolution (PlanSubtask used in PlanOutput before definition)
PlanOutput.model_rebuild()


class CodeOutput(BaseModel):
    """Structured output from the coder agent."""

    files_modified: list[FileChange] = Field(
        default_factory=list,
        description="List of file changes made",
    )
    summary: str = Field(
        default="",
        description="Brief description of what was done",
    )
    tests_added: bool = Field(
        default=False,
        description="Whether tests were added or modified",
    )


class FileChange(BaseModel):
    """A single file change in a code output."""

    path: str = Field(description="File path relative to project root")
    action: str = Field(description="'create', 'modify', or 'delete'")
    description: str = Field(
        default="",
        description="What changed in this file",
    )


CodeOutput.model_rebuild()


class ReviewOutput(BaseModel):
    """Structured output from the reviewer agent."""

    scores: ReviewScores
    selected_candidate: int = Field(
        default=0,
        description="Index of the best candidate (0-indexed)",
    )
    feedback: str = Field(
        default="",
        description="Actionable feedback for the coder",
    )
    approved: bool = Field(
        default=False,
        description="Whether the output meets the quality threshold",
    )


class ReviewScores(BaseModel):
    """Score dimensions for code review."""

    correctness: float = Field(ge=0, le=10, description="Does the code work correctly?")
    quality: float = Field(ge=0, le=10, description="Code quality, readability, patterns")
    safety: float = Field(ge=0, le=10, description="Security and safety considerations")
    completeness: float = Field(ge=0, le=10, description="Does it fully address the task?")
    overall: float = Field(ge=0, le=10, description="Weighted overall score")


ReviewOutput.model_rebuild()


# Registry: maps dotted path strings to classes for runtime resolution
SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "schemas.PlanOutput": PlanOutput,
    "schemas.CodeOutput": CodeOutput,
    "schemas.ReviewOutput": ReviewOutput,
    "schemas.PlanSubtask": PlanSubtask,
    "schemas.FileChange": FileChange,
    "schemas.ReviewScores": ReviewScores,
}


def resolve_schema(dotted_path: str) -> type[BaseModel] | None:
    """Resolve a dotted path string to a Pydantic model class.

    Checks the built-in registry first, then falls back to importlib
    for custom schemas defined outside this module.
    """
    if dotted_path in SCHEMA_REGISTRY:
        return SCHEMA_REGISTRY[dotted_path]

    # Fallback: dynamic import
    try:
        import importlib

        module_path, class_name = dotted_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            return cls
    except (ImportError, AttributeError, ValueError):
        pass

    return None
