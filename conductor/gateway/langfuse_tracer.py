"""
Langfuse tracing integration for the Conductor Gateway.

Wraps inference calls with Langfuse traces for observability:
- Every /v1/chat/completions call → Langfuse generation span
- Every /v1/ultra-think call → Langfuse trace with N generation spans
- Prompt cache hits/misses → Langfuse events
- Slot lifecycle → Langfuse spans

Supports trace propagation: when langfuse_trace_id and langfuse_parent_span_id
are provided (from a spawned agent), gateway generations nest under the conductor's
trace tree instead of creating orphan top-level traces.

The tracer is optional — if Langfuse is unreachable or not configured,
all methods are no-ops. Inference never blocks on telemetry.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Langfuse client — lazy-initialized, None if unavailable
_langfuse = None
_initialized = False


def _get_langfuse():
    """Lazy-init the Langfuse client. Returns None if not configured."""
    global _langfuse, _initialized
    if _initialized:
        return _langfuse
    _initialized = True

    try:
        from langfuse import Langfuse

        client = Langfuse()
        # Quick connectivity check
        client.auth_check()
        _langfuse = client
        logger.info("Langfuse tracing enabled: %s", client.base_url)
    except ImportError:
        logger.info("Langfuse SDK not installed — tracing disabled")
    except Exception as exc:
        logger.warning("Langfuse not reachable — tracing disabled: %s", exc)

    return _langfuse


def _get_observation_parent(lf, trace_id: str | None, parent_span_id: str | None):
    """Resolve a parent observation to nest under.

    If both trace_id and parent_span_id are provided, returns the existing trace
    so generations nest under the conductor's span. Otherwise returns None
    (caller creates a new top-level trace).
    """
    if trace_id and parent_span_id:
        try:
            # Re-open the existing trace by ID — Langfuse SDK merges into
            # the same trace when you pass an existing id.
            return lf.trace(id=trace_id)
        except Exception as exc:
            logger.debug("Failed to resolve parent trace %s: %s", trace_id, exc)
    return None


class LangfuseTracer:
    """Gateway-level Langfuse tracer. Safe to call even when Langfuse is down."""

    def trace_generation(
        self,
        *,
        trace_id: str,
        name: str,
        model: str = "qwen3-coder-next",
        prompt: list[dict] | None = None,
        completion: str = "",
        usage: dict | None = None,
        metadata: dict | None = None,
        slot_id: int | None = None,
        tier: int | None = None,
        candidate_idx: int | None = None,
        latency_ms: float | None = None,
        cache_status: str | None = None,
        lane: str | None = None,
        variant: str | None = None,
        # Trace propagation — nest under conductor's trace tree
        langfuse_trace_id: str | None = None,
        langfuse_parent_span_id: str | None = None,
    ) -> None:
        """Record a single LLM generation call.

        When langfuse_trace_id + langfuse_parent_span_id are provided,
        the generation nests under the conductor's agent span. Otherwise
        creates a standalone trace (legacy behavior).
        """
        lf = _get_langfuse()
        if lf is None:
            return

        tags = [lane] if lane else []

        try:
            # Resolve parent: nest under conductor trace or create new
            parent = _get_observation_parent(lf, langfuse_trace_id, langfuse_parent_span_id)
            base_meta = {
                **(metadata or {}),
                "slot_id": slot_id,
                "tier": tier,
                "cache_status": cache_status,
                "lane": lane,
                "variant": variant,
            }

            if parent is not None:
                # Nest: create a span under the conductor's agent span
                span = parent.span(
                    name=name,
                    parent_observation_id=langfuse_parent_span_id,
                    metadata={**base_meta, "source": "gateway"},
                )
            else:
                # Legacy: standalone trace
                span = lf.trace(
                    id=trace_id,
                    name=name,
                    tags=tags,
                    metadata=base_meta,
                )

            input_messages = prompt or []
            prompt_tokens = usage.get("prompt_tokens", 0) if usage else 0
            completion_tokens = usage.get("completion_tokens", 0) if usage else 0

            span.generation(
                name=f"generation{'_' + str(candidate_idx) if candidate_idx is not None else ''}",
                model=model,
                input=input_messages,
                output=completion,
                usage={
                    "input": prompt_tokens,
                    "output": completion_tokens,
                    "total": prompt_tokens + completion_tokens,
                },
                metadata={
                    "slot_id": slot_id,
                    "candidate_idx": candidate_idx,
                    "latency_ms": latency_ms,
                },
            )
        except Exception as exc:
            logger.debug("Langfuse trace_generation failed: %s", exc)

    def trace_ultra_think(
        self,
        *,
        task_id: str,
        tier: int,
        candidates: list[dict],
        errors: list[str],
        total_ms: float,
        metadata: dict | None = None,
        lane: str | None = None,
        # Trace propagation
        langfuse_trace_id: str | None = None,
        langfuse_parent_span_id: str | None = None,
    ) -> None:
        """Record an Ultra Think multi-candidate generation.

        When trace propagation fields are set, nests under the conductor's
        agent span instead of creating a standalone trace.
        """
        lf = _get_langfuse()
        if lf is None:
            return

        tags = [lane] if lane else []

        try:
            parent = _get_observation_parent(lf, langfuse_trace_id, langfuse_parent_span_id)
            if parent is not None:
                trace = parent.span(
                    name=f"ultra-think-t{tier}",
                    parent_observation_id=langfuse_parent_span_id,
                    metadata={
                        **(metadata or {}),
                        "task_id": task_id,
                        "tier": tier,
                        "candidate_count": len(candidates),
                        "error_count": len(errors),
                        "total_ms": total_ms,
                        "lane": lane,
                        "source": "gateway",
                    },
                )
            else:
                lf.trace(
                    name=f"ultra-think-t{tier}",
                    tags=tags,
                    metadata={
                        **(metadata or {}),
                        "task_id": task_id,
                        "tier": tier,
                        "candidate_count": len(candidates),
                        "error_count": len(errors),
                        "total_ms": total_ms,
                        "lane": lane,
                    },
                )

            for i, candidate in enumerate(candidates):
                trace.generation(
                    name=f"candidate_{i}",
                    model="qwen3-coder-next",
                    output=candidate.get("content", ""),
                    usage={
                        "input": candidate.get("prompt_tokens", 0),
                        "output": candidate.get("completion_tokens", 0),
                    },
                    metadata={
                        "slot_id": candidate.get("slot_id"),
                        "profile": candidate.get("profile_name"),
                    },
                )

            for error in errors:
                trace.event(name="generation_error", metadata={"error": error})

        except Exception as exc:
            logger.debug("Langfuse trace_ultra_think failed: %s", exc)

    def trace_spawn(
        self,
        *,
        trace_id: str,
        agent_id: str,
        role: str,
        task_id: str,
        subtask_id: str,
        tier: int,
        attempt: int = 1,
        parent_span_id: str | None = None,
        lane: str | None = None,
        metadata: dict | None = None,
    ) -> str | None:
        """Record an agent spawn event and return the span ID for nesting.

        Creates a span under the task trace. Returns the span ID so downstream
        gateway calls can nest their generations under this agent's span.
        """
        lf = _get_langfuse()
        if lf is None:
            return None

        try:
            trace = lf.trace(id=trace_id)
            span = trace.span(
                name=f"agent:{role}",
                parent_observation_id=parent_span_id,
                metadata={
                    **(metadata or {}),
                    "agent_id": agent_id,
                    "role": role,
                    "task_id": task_id,
                    "subtask_id": subtask_id,
                    "tier": tier,
                    "attempt": attempt,
                    "lane": lane,
                },
            )
            return span.id
        except Exception as exc:
            logger.debug("Langfuse trace_spawn failed: %s", exc)
            return None

    def end_spawn_span(
        self,
        *,
        trace_id: str,
        span_id: str,
        success: bool,
        output_preview: str = "",
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Close an agent spawn span with result metadata."""
        lf = _get_langfuse()
        if lf is None:
            return

        try:
            trace = lf.trace(id=trace_id)
            # End the span by updating it
            trace.span(
                id=span_id,
                end_time=None,  # Langfuse auto-fills
                metadata={
                    "success": success,
                    "error": error,
                    "duration_ms": duration_ms,
                },
                output=output_preview[:500] if output_preview else None,
            )
        except Exception as exc:
            logger.debug("Langfuse end_spawn_span failed: %s", exc)

    def trace_cache_event(
        self,
        *,
        project_id: str,
        action: str,
        content_hash: str,
        latency_ms: float | None = None,
    ) -> None:
        """Record a prefix cache hit/miss/recompute event."""
        lf = _get_langfuse()
        if lf is None:
            return

        try:
            lf.trace(
                name=f"cache-{action}",
                metadata={
                    "project_id": project_id,
                    "action": action,
                    "content_hash": content_hash,
                    "latency_ms": latency_ms,
                },
            )
        except Exception as exc:
            logger.debug("Langfuse trace_cache_event failed: %s", exc)

    def score_output(
        self,
        *,
        trace_id: str,
        span_id: str | None = None,
        scores: dict[str, float],
        variant: str | None = None,
    ) -> None:
        """Record dimension scores for an agent output.

        Used by the factory pipeline to score outputs per variant,
        feeding into Thompson sampling for variant selection.
        """
        lf = _get_langfuse()
        if lf is None:
            return

        try:
            for dimension, value in scores.items():
                comment = f"variant={variant}" if variant else None
                lf.score(
                    trace_id=trace_id,
                    observation_id=span_id,
                    name=dimension,
                    value=value,
                    comment=comment,
                )
        except Exception as exc:
            logger.debug("Langfuse score_output failed: %s", exc)

    def annotate(
        self,
        *,
        trace_id: str,
        span_id: str | None = None,
        key: str,
        value: str,
    ) -> None:
        """Add an annotation to a trace or span for variant tracking."""
        lf = _get_langfuse()
        if lf is None:
            return

        try:
            trace = lf.trace(id=trace_id)
            trace.event(
                name=f"annotation:{key}",
                metadata={"key": key, "value": value},
                parent_observation_id=span_id,
            )
        except Exception as exc:
            logger.debug("Langfuse annotate failed: %s", exc)

    def trace_review(
        self,
        *,
        task_id: str,
        scores: dict,
        selected_idx: int,
        accepted: bool,
        metadata: dict | None = None,
    ) -> None:
        """Record a reviewer scoring event."""
        lf = _get_langfuse()
        if lf is None:
            return

        try:
            trace = lf.trace(
                name="review",
                metadata={
                    **(metadata or {}),
                    "task_id": task_id,
                    "selected_idx": selected_idx,
                    "accepted": accepted,
                },
            )

            # Record each score dimension as a Langfuse score
            for dimension, value in scores.items():
                lf.score(
                    trace_id=trace.id,
                    name=dimension,
                    value=value,
                )

        except Exception as exc:
            logger.debug("Langfuse trace_review failed: %s", exc)

    def flush(self) -> None:
        """Flush pending events. Call before shutdown."""
        lf = _get_langfuse()
        if lf is not None:
            try:
                lf.flush()
            except Exception as exc:
                logger.debug("Langfuse flush failed: %s", exc)


# Module-level singleton
tracer = LangfuseTracer()
