"""
Agent Spawner — Dynamic agent execution via the gateway.

The spawn() function is the single entry point for the conductor to run any agent.
It handles the full lifecycle:

1. Fill role-specific defaults on the AgentSpec
2. Fetch prompt from PromptManager (Langfuse-backed with local fallback)
3. Inject few-shot exemplars from ExemplarLibrary
4. Create a Langfuse span for observability
5. POST to the gateway (/v1/chat/completions or /v1/ultra-think)
6. Parse the response into a uniform AgentOutput
7. Categorize errors for retry/escalation decisions

The conductor never calls the gateway directly — it always goes through spawn().
"""

from __future__ import annotations

import json
import logging

import httpx
from pydantic import ValidationError

from .agent_spec import (
    AgentOutput,
    AgentSpec,
    ErrorType,
)
from .schemas import resolve_schema
from .structured_output import StructuredOutputParser

logger = logging.getLogger(__name__)


class Spawner:
    """Manages agent lifecycle: prompt assembly, gateway calls, tracing."""

    def __init__(
        self,
        gateway_url: str,
        prompt_manager=None,       # PromptManager instance (optional)
        exemplar_library=None,     # ExemplarLibrary instance (optional)
        langfuse_tracer=None,      # LangfuseTracer instance (optional)
        variant_selector=None,     # VariantSelector instance (optional)
        recipe_registry=None,      # RecipeRegistry instance (optional)
    ) -> None:
        self._gateway_url = gateway_url
        self._prompt_manager = prompt_manager
        self._exemplar_library = exemplar_library
        self._tracer = langfuse_tracer
        self._variant_selector = variant_selector
        self._recipe_registry = recipe_registry
        self._structured_output = StructuredOutputParser(max_retries=2)
        from .. import _gateway_auth
        self._gateway_auth = _gateway_auth

    async def spawn(self, spec: AgentSpec) -> AgentOutput:
        """Execute an agent according to its spec and return structured output.

        This is the main entry point. The conductor builds an AgentSpec,
        calls spawn(), and gets back an AgentOutput with categorized errors,
        timing, and Langfuse trace context.

        When spec.recipe_name is set, the factory pipeline activates:
        1. Load recipe → select variant via Thompson sampling → set prompt_label
        2. If result_type is set → inject JSON schema into system prompt
        3. After response → validate against Pydantic model with retry
        """
        # 1. Fill role defaults
        spec = spec.with_defaults()

        # 1b. Recipe-driven variant selection
        recipe = None
        if spec.recipe_name and self._recipe_registry:
            recipe = self._recipe_registry.get(spec.recipe_name)
            if recipe:
                # Apply recipe defaults to spec
                if not spec.result_type and recipe.result_schema:
                    spec.result_type = recipe.result_schema
                if not spec.prompt_name:
                    spec.prompt_name = recipe.prompt_name
                if spec.temperature is None:
                    spec.temperature = recipe.temperature
                if spec.max_tokens is None:
                    spec.max_tokens = recipe.max_tokens

                # Select variant via Thompson sampling
                if self._variant_selector and len(recipe.prompt_variants) > 1:
                    spec.prompt_label = self._variant_selector.select(recipe)
                    logger.info(
                        "Recipe %s: selected variant '%s'",
                        recipe.name, spec.prompt_label,
                    )

        # Resolve result type for structured output
        result_type = None
        if spec.result_type:
            result_type = resolve_schema(spec.result_type)

        # 2. Build the output envelope (pre-fill identity fields)
        output = AgentOutput(
            agent_id=spec.agent_id,
            role=spec.role,
            task_id=spec.task_id,
            subtask_id=spec.subtask_id,
            attempt=spec.attempt,
            tier_used=spec.tier,
            variant_used=spec.prompt_label,
        )

        # 3. Create Langfuse span for this agent
        span_id = None
        if self._tracer and spec.langfuse_trace_id:
            span_id = self._tracer.trace_spawn(
                trace_id=spec.langfuse_trace_id,
                agent_id=spec.agent_id,
                role=spec.role.value,
                task_id=spec.task_id,
                subtask_id=spec.subtask_id,
                tier=spec.tier,
                attempt=spec.attempt,
                parent_span_id=spec.langfuse_parent_span_id,
                lane=spec.lane.value,
                metadata={
                    "model_override": spec.model_override,
                    "variant": spec.prompt_label,
                    "recipe": spec.recipe_name,
                },
            )
            # Pass our span ID down so gateway generations nest under us
            spec.langfuse_parent_span_id = span_id
            output.langfuse_span_id = span_id

        try:
            # 4. Assemble the prompt
            system_prompt, user_prompt = self._build_prompts(spec)

            # 4b. Inject JSON schema if typed output is expected
            if result_type:
                system_prompt = self._structured_output.inject_schema(
                    system_prompt, result_type
                )

            # 5. Call the gateway
            if spec.parallel_generations > 1:
                result = await self._call_ultra_think(spec, system_prompt, user_prompt)
            else:
                result = await self._call_chat(spec, system_prompt, user_prompt)

            # 6. Fill output
            output.output = result.get("content", "")
            output.model_used = result.get("model")
            output.tokens_used = result.get("usage", {})
            output.success = True

            # 7. Parse structured output (typed or untyped)
            if result_type:
                output.output_parsed = self._parse_typed_output(
                    output.output, result_type, spec, system_prompt
                )
            else:
                output.output_parsed = self._try_parse_json(output.output)

        except httpx.TimeoutException as exc:
            output.mark_error(
                f"Gateway timeout: {exc}",
                ErrorType.TIMEOUT,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 502:
                output.mark_error(
                    f"Gateway backend error: {exc}",
                    ErrorType.MODEL_ERROR,
                )
            else:
                output.mark_error(
                    f"Gateway HTTP error {exc.response.status_code}: {exc}",
                    ErrorType.MODEL_ERROR,
                )
        except json.JSONDecodeError as exc:
            output.mark_error(
                f"Failed to parse gateway response: {exc}",
                ErrorType.PARSE_FAILURE,
            )
        except Exception as exc:
            output.mark_error(
                f"Unexpected error: {exc}",
                ErrorType.MODEL_ERROR,
            )

        # 8. Close Langfuse span
        output.mark_complete()
        if self._tracer and spec.langfuse_trace_id and span_id:
            self._tracer.end_spawn_span(
                trace_id=spec.langfuse_trace_id,
                span_id=span_id,
                success=output.success,
                output_preview=output.output[:500],
                error=output.error,
                duration_ms=output.duration_ms,
            )

        return output

    # ------------------------------------------------------------------
    # Typed output parsing (Pydantic AI concept)
    # ------------------------------------------------------------------

    def _parse_typed_output(
        self,
        raw: str,
        result_type: type,
        spec: AgentSpec,
        system_prompt: str,
    ) -> dict | None:
        """Parse typed output with validation. Returns dict on success, None on failure.

        Uses StructuredOutputParser to validate against the Pydantic model.
        Does NOT retry here — retry requires another gateway call which is
        handled by the conductor's retry loop (AgentSpec.attempt).
        """
        try:
            parsed = self._structured_output.parse(raw, result_type)
            return parsed.model_dump()
        except (ValidationError, ValueError) as exc:
            logger.warning(
                "Typed output validation failed for %s (variant=%s): %s",
                spec.agent_id, spec.prompt_label, exc,
            )
            # Fall back to untyped JSON parse
            return self._try_parse_json(raw)

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def _build_prompts(self, spec: AgentSpec) -> tuple[str, str]:
        """Assemble system prompt and user prompt from spec.

        Layers:
        1. Context dict (memory layers, upstream outputs)
        2. PromptManager template (Langfuse-backed)
        3. Few-shot exemplars from ExemplarLibrary
        4. Task description
        """
        # System prompt: context + role template
        system_parts: list[str] = []

        # Context from memory layers
        for key in ("layer0", "layer1", "layer2", "knowledge"):
            if key in spec.context:
                system_parts.append(spec.context[key])

        # Upstream agent outputs (e.g., planner output → coder)
        # Screen for injection before injecting into downstream context
        for agent_name, output_text in spec.upstream_outputs.items():
            if _upstream_output_is_suspicious(output_text):
                logger.warning(
                    "Upstream output from %s flagged by inter-agent screening — sanitizing",
                    agent_name,
                )
                output_text = _sanitize_upstream(output_text)
            system_parts.append(f"=== {agent_name.upper()} OUTPUT ===\n{output_text}")

        # Role-specific prompt from PromptManager
        if self._prompt_manager and spec.prompt_name:
            variables = {
                "task_id": spec.task_id,
                "subtask_id": spec.subtask_id,
                "description": spec.description,
                **spec.prompt_variables,
            }
            role_prompt = self._prompt_manager.get_prompt(
                spec.prompt_name,
                variables=variables,
                label=spec.prompt_label,
            )
            if role_prompt:
                system_parts.append(role_prompt)

        system_prompt = "\n\n".join(p for p in system_parts if p)

        # User prompt: exemplars + task description
        user_parts: list[str] = []

        # Few-shot exemplars
        if self._exemplar_library and spec.exemplar_task_type:
            few_shot = self._exemplar_library.build_few_shot_section(
                task_type=spec.exemplar_task_type,
                n=spec.exemplar_count,
            )
            if few_shot:
                user_parts.append(few_shot)

        # Task description
        user_parts.append(f"## Task\n{spec.description}")

        user_prompt = "\n\n".join(user_parts)

        return system_prompt, user_prompt

    # ------------------------------------------------------------------
    # Gateway calls
    # ------------------------------------------------------------------

    async def _call_chat(
        self, spec: AgentSpec, system_prompt: str, user_prompt: str
    ) -> dict:
        """Call /v1/chat/completions and return extracted content + usage."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: dict = {
            "model": spec.model_override or "conductor",
            "messages": messages,
            "max_tokens": spec.max_tokens or 4096,
            "temperature": spec.temperature if spec.temperature is not None else 0.7,
        }

        # Langfuse trace propagation + lane
        if spec.langfuse_trace_id:
            payload["langfuse_trace_id"] = spec.langfuse_trace_id
        if spec.langfuse_parent_span_id:
            payload["langfuse_parent_span_id"] = spec.langfuse_parent_span_id
        payload["lane"] = spec.lane.value

        client = await self._gateway_auth.gateway_client()
        resp = await client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {
            "content": content,
            "model": data.get("model"),
            "usage": data.get("usage", {}),
        }

    async def _call_ultra_think(
        self, spec: AgentSpec, system_prompt: str, user_prompt: str
    ) -> dict:
        """Call /v1/ultra-think for parallel diverse generation."""
        payload: dict = {
            "task_id": spec.subtask_id,
            "prompt": user_prompt,
            "system_prompt": system_prompt,
            "tier": spec.tier,
            "max_tokens": spec.max_tokens,
        }
        if spec.project_id:
            payload["project_id"] = spec.project_id

        # Langfuse trace propagation + lane
        if spec.langfuse_trace_id:
            payload["langfuse_trace_id"] = spec.langfuse_trace_id
        if spec.langfuse_parent_span_id:
            payload["langfuse_parent_span_id"] = spec.langfuse_parent_span_id
        payload["lane"] = spec.lane.value

        client = await self._gateway_auth.gateway_client()
        resp = await client.post("/v1/ultra-think", json=payload)
        resp.raise_for_status()
        data = resp.json()

        # Ultra Think returns multiple candidates — concatenate for now,
        # reviewer agent will handle selection
        candidates = data.get("candidates", [])
        if not candidates:
            return {"content": "", "model": None, "usage": {}}

        # Return all candidates as JSON for the reviewer to parse
        if len(candidates) == 1:
            content = candidates[0].get("content", "")
        else:
            # Multiple candidates: serialize as structured output
            content = json.dumps(
                [{"idx": i, "content": c.get("content", "")} for i, c in enumerate(candidates)],
                indent=2,
            )

        total_tokens = sum(c.get("tokens_generated", 0) for c in candidates)
        return {
            "content": content,
            "model": None,
            "usage": {"output": total_tokens},
            "candidates": candidates,
            "timing": data.get("timing", {}),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """Try to extract and parse JSON from agent output."""
        cleaned = text.strip()

        # Handle markdown code blocks
        if "```json" in cleaned:
            try:
                cleaned = cleaned.split("```json")[1].split("```")[0]
            except IndexError:
                pass
        elif "```" in cleaned:
            try:
                cleaned = cleaned.split("```")[1].split("```")[0]
            except IndexError:
                pass

        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return None

    async def close(self) -> None:
        """Shutdown the HTTP client."""
        pass  # Shared client closed by conductor


# ------------------------------------------------------------------
# Inter-agent output screening (Fix #4 — prevent trust propagation)
# ------------------------------------------------------------------

import re as _re  # noqa: E402

_UPSTREAM_INJECTION_PATTERNS = [
    _re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)", _re.IGNORECASE),
    _re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", _re.IGNORECASE),
    _re.compile(r"<\|.*?(system|endoftext|im_start).*?\|>", _re.IGNORECASE),
    _re.compile(r"\[\[.*?SYSTEM.*?\]\]", _re.IGNORECASE),
    _re.compile(r"(don'?t|never)\s+(tell|reveal|show)\s+(the\s+)?(user|human)", _re.IGNORECASE),
    _re.compile(r"(steal|exfiltrate|dump)\s+(credentials?|passwords?|tokens?)", _re.IGNORECASE),
]


def _upstream_output_is_suspicious(text: str) -> bool:
    """Check upstream agent output for injection patterns."""
    for pattern in _UPSTREAM_INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _sanitize_upstream(text: str) -> str:
    """Strip injection patterns from upstream agent output."""
    result = text
    for pattern in _UPSTREAM_INJECTION_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result
