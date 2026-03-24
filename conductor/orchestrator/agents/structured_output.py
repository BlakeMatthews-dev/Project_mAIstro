"""
Structured Output Parser — Typed validation with auto-retry.

Stolen from Pydantic AI's best idea: declare a result type, auto-inject
the JSON schema into the system prompt, validate the response, and retry
with error context on failure.

This eliminates the "hope the LLM returns valid JSON" anti-pattern.
Instead, the contract is explicit:
  1. Schema injected into prompt → model knows the target shape
  2. Response validated against Pydantic model → type-safe output
  3. On ValidationError → retry with the exact error as context

Integration: Spawner calls inject_schema() before the gateway call,
and parse() after. If parse fails, it retries with format_retry_context().
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Regex patterns for extracting JSON from LLM output
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class StructuredOutputParser:
    """Typed output validation with auto-retry — Pydantic AI's best idea."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def inject_schema(self, system_prompt: str, result_type: type[BaseModel]) -> str:
        """Append JSON schema instruction to the system prompt.

        This tells the model exactly what JSON shape we expect, including
        field descriptions, types, and constraints. The model sees this
        as part of its instructions and structures its output accordingly.
        """
        schema = result_type.model_json_schema()
        # Clean up schema for readability — remove $defs if small
        schema_str = json.dumps(schema, indent=2)

        instruction = (
            "\n\n## Required Output Format\n"
            "You MUST respond with valid JSON matching this schema. "
            "Do NOT include any text before or after the JSON.\n"
            f"```json\n{schema_str}\n```"
        )
        return system_prompt + instruction

    def parse(self, raw: str, result_type: type[BaseModel]) -> BaseModel:
        """Parse and validate raw LLM output against the expected type.

        Tries multiple extraction strategies:
        1. Direct JSON parse (output is pure JSON)
        2. Extract from markdown code block (```json ... ```)
        3. Find first JSON object in text ({ ... })

        Raises ValidationError if the JSON is valid but doesn't match the schema.
        Raises ValueError if no valid JSON can be extracted at all.
        """
        cleaned = _extract_json(raw)
        if cleaned is None:
            raise ValueError(
                f"Could not extract JSON from response. "
                f"Raw output starts with: {raw[:200]!r}"
            )
        return result_type.model_validate_json(cleaned)

    def format_retry_context(self, error: ValidationError | ValueError) -> str:
        """Format validation errors as re-prompt context for retry.

        The model receives this as a follow-up user message, so it can see
        exactly what went wrong and fix it. This is the key to high retry
        success rates — specificity.
        """
        if isinstance(error, ValidationError):
            error_details = []
            for e in error.errors():
                loc = " → ".join(str(x) for x in e["loc"])
                error_details.append(f"  - {loc}: {e['msg']} (type: {e['type']})")
            errors_str = "\n".join(error_details)
            return (
                "Your previous response had validation errors. "
                "Please fix these issues and respond with valid JSON only:\n"
                f"{errors_str}"
            )
        else:
            return (
                f"Your previous response could not be parsed as JSON. "
                f"Error: {error}\n"
                f"Please respond with ONLY valid JSON matching the required schema."
            )


def _extract_json(text: str) -> str | None:
    """Extract a JSON string from LLM output using multiple strategies."""
    text = text.strip()

    # Strategy 1: direct parse (pure JSON output)
    if text.startswith("{") or text.startswith("["):
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

    # Strategy 2: markdown code block
    match = _JSON_BLOCK_RE.search(text)
    if match:
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Strategy 3: first JSON object in text
    match = _JSON_OBJECT_RE.search(text)
    if match:
        candidate = match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return None
