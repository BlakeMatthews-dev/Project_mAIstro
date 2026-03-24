"""Shared gateway client — single abstraction for all gateway calls.

Every component that talks to the gateway uses this module instead of
creating its own httpx.AsyncClient. This prevents auth header drift
and ensures consistent timeout/retry behavior.

Timeouts: The shared client uses a generous default (300s) to accommodate
long model generation. Callers that need shorter timeouts pass them
per-request via httpx's timeout parameter on individual calls.
"""
from __future__ import annotations

import os

import httpx

_gateway_url: str = ""
_gateway_key: str = ""
_client: httpx.AsyncClient | None = None

# Default timeout accommodates long model generation (Ultra Think, coder)
# Individual callers can pass shorter timeouts per-request
DEFAULT_TIMEOUT = 300


def configure(gateway_url: str = "") -> None:
    """Set the gateway URL. Called once at conductor startup."""
    global _gateway_url, _gateway_key
    _gateway_url = gateway_url or os.environ.get("CONDUCTOR_GATEWAY_URL", "http://localhost:9090")
    _gateway_key = os.environ.get("CONDUCTOR_GATEWAY_KEY", "")


def gateway_headers() -> dict[str, str]:
    """Return auth headers for gateway requests."""
    if _gateway_key:
        return {"Authorization": f"Bearer {_gateway_key}"}
    return {}


def gateway_url() -> str:
    """Return the configured gateway URL."""
    return _gateway_url or "http://localhost:9090"


async def gateway_client() -> httpx.AsyncClient:
    """Get or create the shared gateway httpx client.

    Uses a 300s default timeout for long generation paths.
    Callers needing shorter timeouts can pass timeout= on individual requests.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=gateway_url(),
            headers=gateway_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
    return _client


async def gateway_chat(
    messages: list[dict],
    max_tokens: int = 2048,
    temperature: float = 0.7,
    model: str | None = None,
    timeout: int | None = None,
) -> str:
    """Send a chat completion to the gateway and return the content.

    This is the ONE function all components should use for simple
    gateway calls. Handles auth, timeouts, and response extraction.

    Args:
        timeout: Per-request timeout override (seconds). Uses client
                 default (300s) if not specified.
    """
    client = await gateway_client()
    payload: dict = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if model:
        payload["model"] = model

    kwargs: dict = {}
    if timeout is not None:
        kwargs["timeout"] = timeout

    resp = await client.post("/v1/chat/completions", json=payload, **kwargs)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def close() -> None:
    """Close the shared client."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
