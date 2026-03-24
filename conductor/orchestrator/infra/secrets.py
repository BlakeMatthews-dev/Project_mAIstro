"""
Secrets Interface — Pluggable secret storage backends.

Every backend implements the same interface. The conductor never imports
a cloud SDK directly — it always goes through this abstraction.

Backends:
  - EnvSecretsBackend: Environment variables (homelab default, systemd EnvironmentFile)
  - VaultwardenBackend: Bitwarden-compatible API (homelab upgrade path)
  - KubernetesBackend: K8s Secrets via service account (cloud default)
  - ExternalVaultBackend: HashiCorp Vault, AWS SM, Azure KV, GCP SM (pluggable)

Selection: CONDUCTOR_SECRETS_BACKEND env var, defaults to "env".
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class SecretsBackend(ABC):
    """Abstract interface for secret storage."""

    @abstractmethod
    async def get(self, name: str) -> str | None:
        """Fetch a secret by name. Returns None if not found."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get_many(self, names: list[str]) -> dict[str, str]:
        """Fetch multiple secrets. Returns only resolved ones."""
        raise NotImplementedError

    async def close(self) -> None:
        """Cleanup resources."""
        pass


class EnvSecretsBackend(SecretsBackend):
    """Read secrets from environment variables.

    This is the simplest backend — secrets are injected by systemd
    EnvironmentFile or K8s env: from Secret references.
    """

    async def get(self, name: str) -> str | None:
        return os.environ.get(name)

    async def get_many(self, names: list[str]) -> dict[str, str]:
        return {n: v for n in names if (v := os.environ.get(n))}


class KubernetesBackend(SecretsBackend):
    """Read secrets from K8s mounted secret volumes.

    K8s mounts secrets as files at /var/run/secrets/conductor/<name>.
    This avoids env var leakage in process listings.
    """

    def __init__(self, mount_path: str = "/var/run/secrets/conductor") -> None:
        self._path = mount_path

    async def get(self, name: str) -> str | None:
        from pathlib import Path
        secret_file = Path(self._path) / name
        if secret_file.exists():
            return secret_file.read_text().strip()
        # Fallback to env
        return os.environ.get(name)

    async def get_many(self, names: list[str]) -> dict[str, str]:
        result = {}
        for name in names:
            value = await self.get(name)
            if value:
                result[name] = value
        return result


class VaultwardenBackend(SecretsBackend):
    """Read secrets from Vaultwarden (Bitwarden-compatible API)."""

    def __init__(self, vault_url: str = "", vault_token: str = "") -> None:
        self._url = vault_url.rstrip("/") if vault_url else ""
        self._token = vault_token
        self._client: httpx.AsyncClient | None = None  # type: ignore[name-defined]
        self._cache: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        if name in self._cache:
            return self._cache[name]

        if not self._url or not self._token:
            return os.environ.get(name)  # Fallback

        try:
            import httpx
            if not self._client:
                self._client = httpx.AsyncClient(timeout=10)

            resp = await self._client.get(
                f"{self._url}/api/vault/items",
                params={"search": name},
                headers={"Authorization": f"Bearer {self._token}"},
            )
            if resp.status_code == 200:
                for item in resp.json().get("data", []):
                    if item.get("name") == name:
                        login = item.get("login", {})
                        value = login.get("password") or item.get("notes", "")
                        if value:
                            self._cache[name] = value
                            return value
        except Exception as exc:
            logger.debug("Vaultwarden fetch failed for %s: %s", name, exc)

        return os.environ.get(name)  # Fallback

    async def get_many(self, names: list[str]) -> dict[str, str]:
        result = {}
        for name in names:
            value = await self.get(name)
            if value:
                result[name] = value
        return result

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class ExternalVaultBackend(SecretsBackend):
    """Generic external vault via HTTP API.

    Works with HashiCorp Vault, or any secrets manager that exposes
    a GET endpoint returning JSON with the secret value.

    Config:
      CONDUCTOR_VAULT_URL=https://vault.example.com
      CONDUCTOR_VAULT_TOKEN=hvs.xxx
      CONDUCTOR_VAULT_PATH_TEMPLATE=/v1/secret/data/{name}
      CONDUCTOR_VAULT_VALUE_JSONPATH=data.data.value
    """

    def __init__(
        self,
        url: str = "",
        token: str = "",
        path_template: str = "/v1/secret/data/{name}",
        value_path: str = "data.data.value",
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._path_template = path_template
        self._value_path = value_path.split(".")
        self._client: httpx.AsyncClient | None = None  # type: ignore[name-defined]

    async def get(self, name: str) -> str | None:
        if not self._url:
            return os.environ.get(name)

        try:
            import httpx
            if not self._client:
                self._client = httpx.AsyncClient(timeout=10)

            path = self._path_template.format(name=name)
            resp = await self._client.get(
                f"{self._url}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                # Navigate the JSON path to extract value
                for key in self._value_path:
                    if isinstance(data, dict):
                        data = data.get(key)
                    else:
                        break
                if isinstance(data, str):
                    return data
        except Exception as exc:
            logger.debug("External vault fetch failed for %s: %s", name, exc)

        return os.environ.get(name)

    async def get_many(self, names: list[str]) -> dict[str, str]:
        result = {}
        for name in names:
            value = await self.get(name)
            if value:
                result[name] = value
        return result

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()


def create_secrets_backend() -> SecretsBackend:
    """Factory: create the right backend based on environment config.

    CONDUCTOR_SECRETS_BACKEND: env | kubernetes | vaultwarden | vault
    """
    backend = os.environ.get("CONDUCTOR_SECRETS_BACKEND", "env")

    if backend == "kubernetes":
        mount = os.environ.get("CONDUCTOR_SECRETS_MOUNT", "/var/run/secrets/conductor")
        logger.info("Secrets backend: Kubernetes (mount=%s)", mount)
        return KubernetesBackend(mount_path=mount)

    elif backend == "vaultwarden":
        url = os.environ.get("CONDUCTOR_VAULT_URL", "")
        token = os.environ.get("CONDUCTOR_VAULT_TOKEN", "")
        logger.info("Secrets backend: Vaultwarden (url=%s)", url)
        return VaultwardenBackend(vault_url=url, vault_token=token)

    elif backend == "vault":
        url = os.environ.get("CONDUCTOR_VAULT_URL", "")
        token = os.environ.get("CONDUCTOR_VAULT_TOKEN", "")
        path_tpl = os.environ.get("CONDUCTOR_VAULT_PATH_TEMPLATE", "/v1/secret/data/{name}")
        val_path = os.environ.get("CONDUCTOR_VAULT_VALUE_JSONPATH", "data.data.value")
        logger.info("Secrets backend: External Vault (url=%s)", url)
        return ExternalVaultBackend(url=url, token=token, path_template=path_tpl, value_path=val_path)

    else:
        logger.info("Secrets backend: Environment variables")
        return EnvSecretsBackend()
