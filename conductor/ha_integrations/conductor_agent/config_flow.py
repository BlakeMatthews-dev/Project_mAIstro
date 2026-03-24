"""Config flow for Conductor AI Agent."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_URL, CONF_API_KEY, CONF_MODEL, DEFAULT_URL, DEFAULT_MODEL

_LOGGER = logging.getLogger(__name__)


async def _validate_connection(url: str, api_key: str) -> dict[str, Any]:
    """Validate we can connect to the Conductor Router."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{url.rstrip('/')}/health",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise ConnectionError(f"Health check returned {resp.status}")
                data = await resp.json()
                return {"title": f"Conductor ({data.get('service', 'router')})"}
        except aiohttp.ClientError as err:
            raise ConnectionError(f"Cannot connect to {url}: {err}") from err


class ConductorAgentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Conductor AI Agent."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _validate_connection(
                    user_input[CONF_URL],
                    user_input[CONF_API_KEY],
                )
            except ConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"], data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional(CONF_MODEL, default=DEFAULT_MODEL): str,
                }
            ),
            errors=errors,
        )
