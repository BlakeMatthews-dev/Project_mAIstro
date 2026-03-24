"""
Secrets Manager — Vaultwarden-backed secret storage.

Replaces plaintext .env files and hardcoded API keys with runtime secret
resolution from Vaultwarden (Bitwarden-compatible API).

Secrets flow:
  1. On startup: authenticate to Vaultwarden, cache session token
  2. On secret request: fetch from Vaultwarden by name, cache in-memory
  3. On skill execution: inject only declared secrets into skill context
  4. On shutdown: wipe in-memory cache

NEVER:
  - Write secrets to disk (no .env, no config files, no temp files)
  - Pass secrets through LLM context (the model never sees API keys)
  - Give skills access to undeclared secrets
  - Log secret values (only log secret names)

For skills, secrets are resolved via the `requires.env` declaration in
SKILL.md frontmatter. A skill declaring `requires.env: [TODOIST_API_KEY]`
gets exactly that secret and nothing else.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# In-memory secret cache TTL (seconds)
_CACHE_TTL = 600  # 10 minutes


@dataclass
class CachedSecret:
    value: str
    fetched_at: float


class SecretsManager:
    """Runtime secret resolution from Vaultwarden.

    Falls back to environment variables when Vaultwarden is unavailable,
    but logs a warning — env vars are the legacy path we're migrating away from.
    """

    def __init__(
        self,
        vault_url: str = "",
        vault_token: str = "",
        fallback_to_env: bool = True,
    ) -> None:
        self._vault_url = vault_url.rstrip("/") if vault_url else ""
        self._vault_token = vault_token
        self._fallback_to_env = fallback_to_env
        self._cache: dict[str, CachedSecret] = {}
        self._client: httpx.AsyncClient | None = None
        self._session_token: str | None = None

    async def get(self, name: str) -> str | None:
        """Fetch a secret by name.

        Resolution order:
        1. In-memory cache (if not expired)
        2. Vaultwarden API (if configured)
        3. Environment variable (if fallback enabled — logs warning)
        """
        # Check cache
        cached = self._cache.get(name)
        if cached and (time.monotonic() - cached.fetched_at) < _CACHE_TTL:
            return cached.value

        # Try Vaultwarden
        if self._vault_url:
            value = await self._fetch_from_vault(name)
            if value is not None:
                self._cache[name] = CachedSecret(
                    value=value, fetched_at=time.monotonic()
                )
                return value

        # Fallback to env var
        if self._fallback_to_env:
            env_value = os.environ.get(name)
            if env_value:
                logger.warning(
                    "Secret '%s' resolved from env var (migrate to Vaultwarden)", name
                )
                self._cache[name] = CachedSecret(
                    value=env_value, fetched_at=time.monotonic()
                )
                return env_value

        return None

    async def get_many(self, names: list[str]) -> dict[str, str]:
        """Fetch multiple secrets. Returns only the ones that resolved."""
        result = {}
        for name in names:
            value = await self.get(name)
            if value is not None:
                result[name] = value
        return result

    async def get_for_skill(
        self, declared_env: list[str], trust_tier: int
    ) -> dict[str, str]:
        """Fetch secrets for a skill, respecting trust tier restrictions.

        T0 (built-in): All declared secrets
        T1 (allowlisted): All declared secrets
        T2 (community): NO secrets (empty dict)
        T3 (untrusted): NO secrets (empty dict)
        """
        if trust_tier >= 2:
            if declared_env:
                logger.info(
                    "Skill at T%d requested secrets %s — denied (tier too low)",
                    trust_tier, declared_env,
                )
            return {}

        return await self.get_many(declared_env)

    def wipe_cache(self) -> None:
        """Clear all cached secrets from memory."""
        self._cache.clear()
        logger.info("Secret cache wiped")

    async def _fetch_from_vault(self, name: str) -> str | None:
        """Fetch a secret from Vaultwarden using the Bitwarden API.

        Searches vault items by name, returns the password/notes field.
        """
        if not self._vault_url or not self._vault_token:
            return None

        try:
            client = await self._ensure_client()

            # Bitwarden API: search items by name
            resp = await client.get(
                f"{self._vault_url}/api/vault/items",
                params={"search": name},
                headers={"Authorization": f"Bearer {self._vault_token}"},
            )

            if resp.status_code != 200:
                logger.debug(
                    "Vaultwarden search for '%s' returned %d", name, resp.status_code
                )
                return None

            items = resp.json().get("data", [])
            for item in items:
                if item.get("name") == name:
                    # Login items: use password field
                    login = item.get("login", {})
                    if login and login.get("password"):
                        return login["password"]
                    # Secure note items: use notes field
                    if item.get("notes"):
                        return item["notes"]

            return None

        except Exception as exc:
            logger.debug("Vaultwarden fetch failed for '%s': %s", name, exc)
            return None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10)
        return self._client

    async def close(self) -> None:
        self.wipe_cache()
        if self._client:
            await self._client.aclose()
            self._client = None
