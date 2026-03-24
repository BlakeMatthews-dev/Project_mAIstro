"""Conductor conversation agent — forwards voice/text to the Conductor Router."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.components.conversation import (
    AssistantContent,
    ChatLog,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
    UserContent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_URL, CONF_API_KEY, CONF_MODEL, DEFAULT_MODEL

_LOGGER = logging.getLogger(__name__)

# Conductor receives a system prompt tailored for voice interaction
VOICE_SYSTEM_PROMPT = (
    "You are the Conductor, a helpful AI assistant for the Emerald family. "
    "You are responding via voice through Alexa or Home Assistant. "
    "Keep responses SHORT and conversational — 1-3 sentences max. "
    "Do NOT use markdown, bullet points, code blocks, or URLs. "
    "Speak naturally as if talking to a person. "
    "Answer any question the user asks — general knowledge, trivia, math, "
    "advice, or anything else. You can do everything a smart assistant can do."
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Conductor conversation entity."""
    async_add_entities(
        [ConductorConversationEntity(config_entry)],
        update_before_add=False,
    )


class ConductorConversationEntity(ConversationEntity):
    """Conversation agent that forwards to the Conductor Router."""

    _attr_has_entity_name = True
    _attr_name = "Conductor"
    _attr_supported_languages = ["en"]

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self._entry = entry
        self._url = entry.data.get(CONF_URL, "").rstrip("/")
        self._api_key = entry.data.get(CONF_API_KEY, "")
        self._model = entry.data.get(CONF_MODEL, DEFAULT_MODEL)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"

    @property
    def supported_languages(self) -> list[str]:
        """Return supported languages."""
        return ["en"]

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Forward the user's message to the Conductor Router."""

        # Build messages array from chat log for multi-turn context
        messages: list[dict[str, str]] = [
            {"role": "system", "content": VOICE_SYSTEM_PROMPT},
        ]

        for content in chat_log.content:
            if isinstance(content, AssistantContent):
                if content.content:
                    messages.append({
                        "role": "assistant",
                        "content": content.content,
                    })
            elif isinstance(content, UserContent):
                if content.content:
                    messages.append({
                        "role": "user",
                        "content": content.content,
                    })

        # Ensure the current user message is included
        if not messages or messages[-1].get("content") != user_input.text:
            messages.append({"role": "user", "content": user_input.text})

        # Build the Conductor Router request
        # Use "voice" model group for fast responses, fall back to configured model
        model = "voice" if self._model == "auto" else self._model
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "session_id": f"ha_voice_{chat_log.conversation_id or 'default'}",
            "stream": False,
        }

        response_text = await self._call_conductor(payload)

        # Add to chat log so HA tracks the conversation
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(
                agent_id=user_input.agent_id,
                content=response_text,
            )
        )

        # Build HA response
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_text)

        return ConversationResult(
            response=intent_response,
            conversation_id=chat_log.conversation_id,
            continue_conversation=False,
        )

    async def _call_conductor(self, payload: dict[str, Any]) -> str:
        """POST to the Conductor Router and extract the response text."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        _LOGGER.error(
                            "Conductor returned %s: %s",
                            resp.status,
                            error_text[:200],
                        )
                        return "Sorry, I couldn't reach the Conductor right now."

                    data = await resp.json()

        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to connect to Conductor: %s", err)
            return "Sorry, the Conductor is not responding."
        except TimeoutError:
            _LOGGER.error("Conductor request timed out")
            return "Sorry, that took too long. Try again."

        # Extract the assistant's response
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            _LOGGER.error("Unexpected response format: %s", data)
            return "Sorry, I got an unexpected response."

        if not content or not content.strip():
            return "I processed that but have nothing to say."

        # Log routing info for debugging
        routing = data.get("_routing", {})
        if routing:
            _LOGGER.info(
                "Conductor routed to %s (reason: %s, score: %s)",
                routing.get("router_model", "?"),
                routing.get("router_reason", "?"),
                routing.get("router_score", "?"),
            )

        return content.strip()
