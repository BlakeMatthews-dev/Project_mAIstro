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


# ── Scout: codebase analysis ──────────────────────────────────────

class ScoutFile(BaseModel):
    """A single file in a scout inventory."""
    path: str = Field(description="File path relative to scan root")
    lines: int = Field(description="Line count")
    imports: list[str] = Field(default_factory=list, description="Top-level imports")
    exports: list[str] = Field(default_factory=list, description="Classes/functions defined")
    category: str = Field(default="", description="Functional category (e.g. 'security', 'memory', 'routing')")


class ScoutOutput(BaseModel):
    """Structured output from the scout agent."""
    files: list[ScoutFile] = Field(description="File inventory")
    total_lines: int = Field(default=0, description="Total LOC across all files")
    dependency_graph: dict[str, list[str]] = Field(
        default_factory=dict,
        description="File → list of files it imports from (internal deps only)",
    )
    god_files: list[str] = Field(
        default_factory=list,
        description="Files >500 LOC that should be split",
    )
    summary: str = Field(default="", description="Brief structural analysis")


ScoutOutput.model_rebuild()


# ── Architect: structure design ───────────────────────────────────

class ArchitectMapping(BaseModel):
    """A single file mapping from source to target."""
    source: str = Field(description="Source file path")
    target: str = Field(description="Target file path in new structure")
    transforms: list[str] = Field(
        default_factory=list,
        description="Transforms to apply: 'rename:old→new', 'sanitize:pattern', 'split:function_name→new_file'",
    )
    priority: int = Field(default=5, description="Execution order (1=first)")


class ArchitectOutput(BaseModel):
    """Structured output from the architect agent."""
    directory_structure: list[str] = Field(
        description="Target directory tree (list of paths to create)",
    )
    file_mappings: list[ArchitectMapping] = Field(
        description="Ordered list of source→target file mappings with transforms",
    )
    new_files: list[ArchitectNewFile] = Field(
        default_factory=list,
        description="Files to create from scratch (READMEs, __init__.py, etc.)",
    )
    subtasks: list[str] = Field(
        default_factory=list,
        description="Ordered human-readable subtask descriptions for the extractor",
    )
    reasoning: str = Field(default="", description="Architecture decisions and rationale")


class ArchitectNewFile(BaseModel):
    """A file to be created from scratch."""
    path: str = Field(description="Target path")
    description: str = Field(description="What this file should contain")
    template: str = Field(default="", description="Rough content template or instructions")


ArchitectOutput.model_rebuild()


class CheckpointArchitectureOutput(BaseModel):
    """Structured output from the architect for normal coding checkpoints."""

    checkpoint_goal: str = Field(
        default="",
        description="What this checkpoint is trying to complete before review",
    )
    allowed_files: list[str] = Field(
        default_factory=list,
        description="Files or paths the builder should stay within for this checkpoint",
    )
    non_goals: list[str] = Field(
        default_factory=list,
        description="Things explicitly out of scope for the current checkpoint",
    )
    invariants: list[str] = Field(
        default_factory=list,
        description="Constraints that must remain true while building",
    )
    review_focus: list[str] = Field(
        default_factory=list,
        description="What reviewers should pay extra attention to",
    )
    test_focus: list[str] = Field(
        default_factory=list,
        description="Tests or behaviors that should provide evidence before advancing",
    )
    summary: str = Field(default="", description="Brief architecture guidance")


CheckpointArchitectureOutput.model_rebuild()


# ── Extractor: file transformation ────────────────────────────────

class ExtractorOutput(BaseModel):
    """Structured output from the extractor agent."""
    files_written: list[FileChange] = Field(
        default_factory=list,
        description="Files written to target location",
    )
    renames_applied: list[str] = Field(
        default_factory=list,
        description="Rename operations performed (e.g. 'conductor→sovereign')",
    )
    sanitizations: list[str] = Field(
        default_factory=list,
        description="Credential/IP sanitizations performed",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Issues encountered that need human review",
    )
    summary: str = Field(default="", description="What was done")


# ── Validator: build/test verification ────────────────────────────

class ValidatorCheck(BaseModel):
    """A single validation check result."""
    name: str = Field(description="Check name (e.g. 'import_check', 'docker_build')")
    passed: bool = Field(description="Whether the check passed")
    output: str = Field(default="", description="Command output or error message")


class ValidatorOutput(BaseModel):
    """Structured output from the validator agent."""
    checks: list[ValidatorCheck] = Field(description="Results of each validation check")
    all_passed: bool = Field(description="Whether all checks passed")
    blocking_issues: list[str] = Field(
        default_factory=list,
        description="Issues that must be fixed before proceeding",
    )
    summary: str = Field(default="", description="Validation summary")


# Registry: maps dotted path strings to classes for runtime resolution
SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "schemas.PlanOutput": PlanOutput,
    "schemas.CodeOutput": CodeOutput,
    "schemas.ReviewOutput": ReviewOutput,
    "schemas.PlanSubtask": PlanSubtask,
    "schemas.FileChange": FileChange,
    "schemas.ReviewScores": ReviewScores,
    "schemas.ScoutOutput": ScoutOutput,
    "schemas.ScoutFile": ScoutFile,
    "schemas.ArchitectOutput": ArchitectOutput,
    "schemas.CheckpointArchitectureOutput": CheckpointArchitectureOutput,
    "schemas.ArchitectMapping": ArchitectMapping,
    "schemas.ArchitectNewFile": ArchitectNewFile,
    "schemas.ExtractorOutput": ExtractorOutput,
    "schemas.ValidatorOutput": ValidatorOutput,
    "schemas.ValidatorCheck": ValidatorCheck,
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
