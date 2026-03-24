"""
Task Progress Reporter — Reports real-time task status to the dashboard.

The conductor calls these methods at each pipeline step so the dashboard
can show live progress. Communicates via the conductor-router API.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class ProgressReporter:
    """Reports task progress to the conductor-router dashboard API."""

    def __init__(self, router_url: str = "http://localhost:8100", api_key: str = "") -> None:
        self._url = router_url.rstrip("/")
        self._key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5)
        return self._client

    async def update(
        self,
        task_id: str,
        status: str,
        *,
        filename: str = "",
        current_step: str = "",
        steps_total: int = 0,
        steps_completed: int = 0,
        details: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Report task progress to the dashboard.

        Status values: queued, screening, routing, planning, executing,
                       reviewing, testing, completed, failed
        """
        try:
            client = await self._ensure_client()
            await client.post(
                f"{self._url}/v1/conductor/progress",
                json={
                    "task_id": task_id,
                    "filename": filename,
                    "status": status,
                    "current_step": current_step,
                    "steps_total": steps_total,
                    "steps_completed": steps_completed,
                    "details": details or {},
                    "error": error,
                },
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except Exception as exc:
            # Never block task processing on progress reporting
            logger.debug("Progress report failed: %s", exc)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
