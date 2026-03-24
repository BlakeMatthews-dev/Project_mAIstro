"""
Intent Router (Bouncer) — determines what the user wants and routes to the right agent.

Routing logic:
  1. Pattern matching (fast, deterministic):
     - Trigger phrases like "tell abra to..." → home automation
     - "let's make/build/create..." → coding/artifacts
     - Known malicious patterns → deny

  2. LLM classification (when patterns don't match):
     - Sends task text to gateway for intent classification
     - Returns intent + confidence
     - If confidence < threshold → ask user to clarify

  3. Safety check (always runs):
     - Jailbreak / prompt injection detection
     - Malicious intent patterns
     - Runs BEFORE routing to any agent

Intents:
  - CODE: write, fix, refactor, test code
  - HOME_AUTOMATION: control devices via Abra → Home Assistant API
      Abra translates natural language into HA service calls
      (light.turn_off, climate.set_temperature, etc.)
  - ARTIFACT: create documents, presentations, etc.
  - ANALYSIS: review, audit, assess code/architecture
  - CONVERSATION: general question, clarification
  - DENIED: malicious/jailbreak attempt
  - UNCLEAR: low confidence — needs user clarification
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

import httpx

from .. import _gateway_auth

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    CODE = "code"
    HOME_AUTOMATION = "home_automation"
    ARTIFACT = "artifact"
    ANALYSIS = "analysis"
    CONVERSATION = "conversation"
    DENIED = "denied"
    UNCLEAR = "unclear"


@dataclass
class RoutingResult:
    intent: Intent
    confidence: float            # 0.0 - 1.0
    agent_name: str              # Which agent/prompt set to use
    rewritten_task: str          # Cleaned/normalized task text
    clarification_prompt: str    # If intent == UNCLEAR, what to ask the user
    denial_reason: str           # If intent == DENIED, why
    raw_input: str               # Original user input


# ------------------------------------------------------------------
# Pattern matchers (fast, deterministic)
# ------------------------------------------------------------------

# Trigger phrases → intent mappings
_TRIGGER_PATTERNS: list[tuple[re.Pattern, Intent, str]] = [
    # Home automation (Abra)
    (re.compile(r"\btell\s+abra\s+to\b", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),
    (re.compile(r"\babra[\s,]+", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),
    (re.compile(r"\bturn\s+(on|off)\s+(the\s+)?", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),
    (re.compile(r"\b(kill|cut)\s+(the\s+)?light", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),
    (re.compile(r"\bset\s+(the\s+)?(thermostat|thermo|temperature|lights?|lites?|brightness)\b", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),
    (re.compile(r"\b(light|lite)[s]?\s+(on|off|dim|bright)", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),
    (re.compile(r"\block\s+(the\s+)?door", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),
    (re.compile(r"\barm\s+(the\s+)?(alarm|security)", re.IGNORECASE), Intent.HOME_AUTOMATION, "abra"),

    # Coding
    (re.compile(r"\b(let'?s|please)\s+(make|build|create|write|implement)\b", re.IGNORECASE), Intent.CODE, "coder"),
    (re.compile(r"\bfix\s+(the\s+|this\s+)?(bug|error|issue|crash|problem)\b", re.IGNORECASE), Intent.CODE, "coder"),
    (re.compile(r"\brefactor\b", re.IGNORECASE), Intent.CODE, "coder"),
    (re.compile(r"\badd\s+(a\s+)?(test|feature|endpoint|route|function|class|method)\b", re.IGNORECASE), Intent.CODE, "coder"),
    (re.compile(r"\bimplement\b", re.IGNORECASE), Intent.CODE, "coder"),
    (re.compile(r"\b(write|create)\s+(a\s+)?(script|function|class|module|decorator|test)\b", re.IGNORECASE), Intent.CODE, "coder"),

    # Analysis
    (re.compile(r"\b(review|audit|assess|analyze|evaluate)\s+(the\s+|this\s+)?", re.IGNORECASE), Intent.ANALYSIS, "coder"),
    (re.compile(r"\bsecurity\s+(review|audit|check)\b", re.IGNORECASE), Intent.ANALYSIS, "coder"),
    (re.compile(r"\bcode\s+review\b", re.IGNORECASE), Intent.ANALYSIS, "coder"),

    # Artifacts
    (re.compile(r"\b(create|make|generate|write)\s+(a\s+)?(document|doc|presentation|report|readme|proposal)\b", re.IGNORECASE), Intent.ARTIFACT, "artifact"),
    (re.compile(r"\bdraft\s+(a\s+)?(email|memo|spec|rfc|design\s+doc)\b", re.IGNORECASE), Intent.ARTIFACT, "artifact"),
]

# Safety patterns — always checked first
_SAFETY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE), "Prompt injection attempt"),
    (re.compile(r"you\s+are\s+now\s+(a|an|the)\b", re.IGNORECASE), "Role override attempt"),
    (re.compile(r"pretend\s+(you('re|\s+are)\s+)?(a|an|not)\b", re.IGNORECASE), "Role override attempt"),
    (re.compile(r"system\s*:\s*", re.IGNORECASE), "System prompt injection"),
    (re.compile(r"\bsudo\s+", re.IGNORECASE), "Privilege escalation attempt"),
    (re.compile(r"rm\s+-rf\s+/", re.IGNORECASE), "Destructive command"),
    (re.compile(r"\b(hack|exploit|ddos|phish|malware|ransomware)\b.*\b(how|tutorial|guide|script)\b", re.IGNORECASE), "Malicious intent"),
    (re.compile(r"\b(steal|exfiltrate|dump)\s+(credentials?|passwords?|data|tokens?|keys?)\b", re.IGNORECASE), "Data theft intent"),
    (re.compile(r"<\|.*?\|>", re.IGNORECASE), "Token manipulation attempt"),
    (re.compile(r"\[\[.*?SYSTEM.*?\]\]", re.IGNORECASE), "System prompt injection"),
]

# Intent keywords for LLM fallback classification
_INTENT_DESCRIPTIONS = {
    Intent.CODE: "Writing, fixing, or modifying software code (Python, JavaScript, etc.)",
    Intent.HOME_AUTOMATION: (
        "Controlling smart home devices via Home Assistant — lights, thermostat, "
        "locks, alarms, fans, blinds. The user may say 'tell abra to...' or just "
        "describe what they want (e.g. 'it's too bright', 'warm it up'). Abra "
        "translates to HA service calls like light.turn_off, climate.set_temperature."
    ),
    Intent.ARTIFACT: "Creating documents, presentations, reports, or other text artifacts",
    Intent.ANALYSIS: "Reviewing, auditing, or analyzing existing code or architecture",
    Intent.CONVERSATION: "General question, greeting, or conversational exchange",
}


# ------------------------------------------------------------------
# Router class
# ------------------------------------------------------------------


class IntentRouter:
    """Classifies user intent and routes to the appropriate agent."""

    def __init__(
        self,
        gateway_url: str = "http://localhost:9090",
        confidence_threshold: float = 0.7,
        routing_model: str | None = None,
        routing_provider: str | None = None,
        routing_api_key: str | None = None,
        routing_api_base: str | None = None,
    ) -> None:
        self._gateway_url = gateway_url
        self._confidence_threshold = confidence_threshold
        self._routing_model = routing_model
        self._routing_provider = routing_provider
        self._routing_api_key = routing_api_key
        self._routing_api_base = routing_api_base
        self._client: httpx.AsyncClient | None = None
        self._routing_client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = await _gateway_auth.gateway_client()  # Shared client
        return self._client

    async def _ensure_routing_client(self) -> httpx.AsyncClient | None:
        """Create a direct-to-cloud client for classification, if configured."""
        if not self._routing_provider or not self._routing_api_key:
            return None
        if self._routing_client is None:
            if self._routing_provider == "anthropic":
                self._routing_client = httpx.AsyncClient(
                    timeout=30,
                    headers={
                        "x-api-key": self._routing_api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                )
            else:
                # OpenAI / OpenRouter / any OpenAI-compat
                self._routing_client = httpx.AsyncClient(
                    timeout=30,
                    headers={
                        "Authorization": f"Bearer {self._routing_api_key}",
                        "Content-Type": "application/json",
                    },
                )
        return self._routing_client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._routing_client:
            await self._routing_client.aclose()
            self._routing_client = None

    async def route(self, task_text: str) -> RoutingResult:
        """Classify intent and return routing decision.

        Order of operations:
          1. Safety check (always first)
          2. Pattern matching (fast, deterministic)
          3. LLM classification (fallback for ambiguous input)
          4. Confidence check (ask user if unsure)
        """
        # ── 1. Safety check ──────────────────────────────────────
        denial = self._check_safety(task_text)
        if denial:
            return RoutingResult(
                intent=Intent.DENIED,
                confidence=1.0,
                agent_name="",
                rewritten_task="",
                clarification_prompt="",
                denial_reason=denial,
                raw_input=task_text,
            )

        # ── 2. Pattern matching ──────────────────────────────────
        pattern_result = self._match_patterns(task_text)
        if pattern_result:
            return pattern_result

        # ── 3. LLM classification ────────────────────────────────
        llm_result = await self._classify_with_llm(task_text)
        if llm_result.confidence >= self._confidence_threshold:
            return llm_result

        # ── 4. Low confidence → ask for clarification ────────────
        return RoutingResult(
            intent=Intent.UNCLEAR,
            confidence=llm_result.confidence,
            agent_name="",
            rewritten_task=task_text,
            clarification_prompt=self._build_clarification(task_text, llm_result),
            denial_reason="",
            raw_input=task_text,
        )

    def _check_safety(self, text: str) -> str:
        """Check for malicious/jailbreak patterns. Returns denial reason or empty string."""
        for pattern, reason in _SAFETY_PATTERNS:
            if pattern.search(text):
                logger.warning("Safety check triggered: %s (reason: %s)", text[:80], reason)
                return reason
        return ""

    def _match_patterns(self, text: str) -> RoutingResult | None:
        """Try deterministic pattern matching. Returns None if no match."""
        for pattern, intent, agent in _TRIGGER_PATTERNS:
            if pattern.search(text):
                # Strip trigger phrase to get the actual task
                cleaned = pattern.sub("", text).strip()
                if not cleaned:
                    cleaned = text  # Keep original if stripping leaves nothing

                return RoutingResult(
                    intent=intent,
                    confidence=0.95,  # High but not 1.0 (patterns can be wrong)
                    agent_name=agent,
                    rewritten_task=cleaned,
                    clarification_prompt="",
                    denial_reason="",
                    raw_input=text,
                )
        return None

    async def _classify_with_llm(self, text: str) -> RoutingResult:
        """Use the LLM to classify intent when patterns don't match.

        If a routing_provider is configured, calls the cloud API directly
        (bypassing the gateway) for better classification accuracy.
        Otherwise falls back to the gateway's default model.
        """
        intent_list = "\n".join(
            f"- {intent.value}: {desc}"
            for intent, desc in _INTENT_DESCRIPTIONS.items()
        )

        system_msg = "You are an intent classifier. Respond only with JSON."
        prompt = f"""\
Classify the user's intent. Respond with ONLY a JSON object:
{{"intent": "<one of: code, home_automation, artifact, analysis, conversation>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}

Available intents:
{intent_list}

User message: {text}"""

        try:
            content = await self._call_routing_llm(system_msg, prompt)

            # Parse response
            import json
            cleaned = content.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned)

            intent_str = data.get("intent", "conversation")
            confidence = float(data.get("confidence", 0.5))

            try:
                intent = Intent(intent_str)
            except ValueError:
                intent = Intent.CONVERSATION
                confidence = 0.3

            # Map intent to agent
            agent_map = {
                Intent.CODE: "coder",
                Intent.HOME_AUTOMATION: "abra",
                Intent.ARTIFACT: "artifact",
                Intent.ANALYSIS: "coder",
                Intent.CONVERSATION: "conversation",
            }

            return RoutingResult(
                intent=intent,
                confidence=confidence,
                agent_name=agent_map.get(intent, "coder"),
                rewritten_task=text,
                clarification_prompt="",
                denial_reason="",
                raw_input=text,
            )

        except Exception as exc:
            logger.warning("LLM classification failed, defaulting to CODE: %s", exc)
            return RoutingResult(
                intent=Intent.CODE,
                confidence=0.4,
                agent_name="coder",
                rewritten_task=text,
                clarification_prompt="",
                denial_reason="",
                raw_input=text,
            )

    def _build_clarification(self, text: str, best_guess: RoutingResult) -> str:
        """Build a clarification message when confidence is low."""
        guess_desc = _INTENT_DESCRIPTIONS.get(best_guess.intent, "unknown")
        return (
            f"I want to make sure I understand your request correctly.\n\n"
            f"I interpreted this as: **{guess_desc}**\n"
            f"(confidence: {best_guess.confidence:.0%})\n\n"
            f'Your message: "{text[:200]}"\n\n'
            f"Is this correct? If not, could you rephrase what you'd like me to do?\n"
            f"For example:\n"
            f'  - For coding: "fix the bug in...", "create a function that..."\n'
            f'  - For home automation: "tell Abra to turn off the lights"\n'
            f'  - For documents: "create a report about..."\n'
        )

    async def _call_routing_llm(self, system_msg: str, user_msg: str) -> str:
        """Call the routing LLM — cloud API if configured, gateway otherwise."""
        routing_client = await self._ensure_routing_client()

        if routing_client and self._routing_provider == "anthropic":
            # Anthropic Messages API (different shape)
            base = (self._routing_api_base or "https://api.anthropic.com").rstrip("/")
            resp = await routing_client.post(
                f"{base}/v1/messages",
                json={
                    "model": self._routing_model or "claude-haiku-4-5-20251001",
                    "system": system_msg,
                    "messages": [{"role": "user", "content": user_msg}],
                    "max_tokens": 128,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            blocks = resp.json().get("content", [])
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

        elif routing_client:
            # OpenAI-compatible (OpenAI, OpenRouter, etc.)
            base = (self._routing_api_base or "https://api.openai.com/v1").rstrip("/")
            resp = await routing_client.post(
                f"{base}/chat/completions",
                json={
                    "model": self._routing_model or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 128,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        else:
            # Fallback: route through the gateway
            client = await self._ensure_client()
            payload: dict = {
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 128,
                "temperature": 0.1,
            }
            if self._routing_model:
                payload["model"] = self._routing_model
            resp = await client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
