"""Conductor AI Agent — routes voice commands through the Conductor Router.

This integration registers a conversation agent that forwards natural language
queries to the Conductor Router's /v1/chat/completions endpoint.  The router
handles intent classification, model selection, and tool dispatch (HA control,
family chores, CoinSwarm, browser automation) — then returns a text response
that HA speaks back via TTS.

Architecture:
  Alexa → Nabu Casa → HA Assist Pipeline → this agent → Conductor Router
  → LiteLLM → best model → tools → response → HA TTS → Alexa speaks
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CONVERSATION]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up Conductor Agent from YAML (not used, config flow only)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Conductor Agent from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Conductor Agent configured: url=%s, model=%s",
        entry.data.get("url"),
        entry.data.get("model", "auto"),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
