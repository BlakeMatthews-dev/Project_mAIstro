"""
Agent Spec Contracts — Uniform spawn/result envelopes for conductor-to-agent communication.

Every agent spawned by the conductor receives an AgentSpec and returns an AgentOutput.
This creates a predictable, observable, type-safe interface regardless of agent role.

AgentSpec defines WHAT to do (role, task, context, constraints, tools).
AgentOutput defines WHAT happened (result, errors, timing, trace IDs).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class Lane(StrEnum):
    """Execution lanes for priority-aware scheduling.

    Live-chat work is latency-sensitive — it gets reserved slots and priority
    scheduling so interactive users never wait behind batch jobs.
    Background-task work uses excess capacity and yields to live requests.
    """

    LIVE = "live-chat"
    BACKGROUND = "background-task"


class AgentRole(StrEnum):
    """Roles an agent can take in the conductor pipeline."""

    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    SCOUT = "scout"           # Codebase exploration, file inventory, dependency mapping
    ARCHITECT = "architect"   # Designs module boundaries, repo structure, import graphs
    EXTRACTOR = "extractor"   # Copy + rename + sanitize + split files between locations
    VALIDATOR = "validator"   # Run the result (docker build, import check, pytest)
    INTENT_ROUTER = "intent_router"
    ARTIFACT = "artifact"     # Document / diagram generation
    CONVERSATION = "conversation"


class ErrorType(StrEnum):
    """Categorized error types for structured error handling.

    Recoverable errors trigger retries or tier escalation.
    Non-recoverable errors fail immediately.
    """

    # Recoverable
    TIMEOUT = "timeout"
    PARSE_FAILURE = "parse_failure"
    MODEL_ERROR = "model_error"
    LOW_SCORE = "low_score"

    # Non-recoverable
    SAFETY_VIOLATION = "safety_violation"
    TOOL_VIOLATION = "tool_violation"
    DEPENDENCY_FAILED = "dependency_failed"


# Which error types can be retried
RECOVERABLE_ERRORS = {
    ErrorType.TIMEOUT,
    ErrorType.PARSE_FAILURE,
    ErrorType.MODEL_ERROR,
    ErrorType.LOW_SCORE,
}


# Default tool whitelists per role (least-privilege)
DEFAULT_TOOLS: dict[AgentRole, list[str]] = {
    AgentRole.PLANNER: ["file_ops.read", "file_ops.list", "shell.run_read_only"],
    AgentRole.CODER: ["file_ops.read", "file_ops.write", "file_ops.list", "shell.run"],
    AgentRole.REVIEWER: ["file_ops.read", "file_ops.list"],
    AgentRole.SCOUT: ["file_ops.read", "file_ops.list", "shell.run_read_only", "git.log", "git.diff"],
    AgentRole.ARCHITECT: ["file_ops.read", "file_ops.list"],
    AgentRole.EXTRACTOR: ["file_ops.read", "file_ops.write", "file_ops.list"],
    AgentRole.VALIDATOR: ["file_ops.read", "file_ops.list", "shell.run_read_only"],
    AgentRole.INTENT_ROUTER: [],
    AgentRole.ARTIFACT: ["file_ops.read", "file_ops.write"],
    AgentRole.CONVERSATION: [],
}


class AgentSpec(BaseModel):
    """What the conductor sends TO a spawned agent.

    This is the complete envelope — everything an agent needs to do its job.
    """

    # Identity
    agent_id: str = Field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:8]}")
    role: AgentRole
    parent_agent_id: str | None = None  # conductor's own agent_id (for trace nesting)
    tenant_id: str = "homelab"           # Multi-tenant isolation key

    # Task
    task_id: str
    subtask_id: str
    description: str
    attempt: int = 1
    project_id: str = ""               # For gateway prefix cache restore (local inference)

    # Context (assembled from memory layers)
    context: dict[str, str] = Field(default_factory=dict)
    # Upstream agent outputs injected here (e.g., planner output → coder context)
    upstream_outputs: dict[str, str] = Field(default_factory=dict)

    # Model configuration
    tier: int = 2
    model_override: str | None = None    # bypass tier → model mapping
    temperature: float | None = None     # override default for role
    max_tokens: int | None = None
    parallel_generations: int = 1        # >1 for Ultra Think

    # Prompt
    prompt_name: str | None = None       # PromptManager key, e.g. "coder.generate"
    prompt_label: str = "production"     # Langfuse prompt label
    prompt_variables: dict[str, str] = Field(default_factory=dict)

    # Agent Factory — recipe-driven spawning
    recipe_name: str | None = None       # AgentRecipe name (triggers variant selection)
    result_type: str | None = None       # Dotted path to Pydantic model for typed output

    # Few-shot exemplars
    exemplar_task_type: str | None = None  # ExemplarLibrary task_type for lookup
    exemplar_count: int = 2                # how many exemplars to inject
    exemplar_min_score: float = 7.0        # minimum reviewer score for exemplars

    # Security
    tools_allowed: list[str] = Field(default_factory=list)
    write_scopes: list[str] = Field(default_factory=list)  # allowed file path prefixes

    # Execution lane — controls slot priority and trace tagging
    lane: Lane = Lane.BACKGROUND

    # Langfuse trace propagation (filled by spawn(), not caller)
    langfuse_trace_id: str | None = None
    langfuse_parent_span_id: str | None = None

    def with_defaults(self) -> AgentSpec:
        """Fill in defaults that depend on role."""
        if not self.tools_allowed:
            self.tools_allowed = list(DEFAULT_TOOLS.get(self.role, []))
        if not self.prompt_name:
            # Convention: role.action (e.g. "coder.generate", "reviewer.score")
            action_map = {
                AgentRole.PLANNER: "planner.decompose",
                AgentRole.CODER: "coder.generate",
                AgentRole.REVIEWER: "reviewer.score",
                AgentRole.SCOUT: "scout.analyze",
                AgentRole.ARCHITECT: "architect.design",
                AgentRole.EXTRACTOR: "extractor.transform",
                AgentRole.VALIDATOR: "validator.check",
            }
            self.prompt_name = action_map.get(self.role)
        return self


class AgentOutput(BaseModel):
    """What a spawned agent returns TO the conductor.

    Uniform result envelope with error categorization, timing, and trace context.
    """

    # Identity (echo back from spec)
    agent_id: str
    role: AgentRole
    task_id: str
    subtask_id: str
    attempt: int = 1

    # Result
    success: bool = True
    output: str = ""                     # primary output (plan JSON, code, review JSON)
    output_parsed: dict | None = None    # structured parse of output (if applicable)

    # Error handling
    error: str | None = None
    error_type: ErrorType | None = None
    recoverable: bool = True             # can the conductor retry?
    escalation_reason: str | None = None  # why tier was escalated

    # Agent Factory metadata
    variant_used: str | None = None      # Which prompt variant was selected

    # Metadata
    model_used: str | None = None
    tier_used: int | None = None
    tokens_used: dict[str, int] = Field(default_factory=dict)  # {"input": N, "output": M}
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_ms: float = 0.0

    # Langfuse span ID (for downstream agents to nest under)
    langfuse_span_id: str | None = None

    def mark_complete(self) -> None:
        """Set completed_at and duration_ms."""
        self.completed_at = datetime.now(timezone.utc)
        if self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_ms = delta.total_seconds() * 1000

    def mark_error(
        self,
        error: str,
        error_type: ErrorType,
        *,
        escalation_reason: str | None = None,
    ) -> None:
        """Mark this output as failed with categorized error."""
        self.success = False
        self.error = error
        self.error_type = error_type
        self.recoverable = error_type in RECOVERABLE_ERRORS
        self.escalation_reason = escalation_reason
        self.mark_complete()
