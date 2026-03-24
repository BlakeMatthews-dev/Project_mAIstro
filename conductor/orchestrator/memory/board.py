"""
Message Board — Agent-to-human non-urgent communication.

The board is how the conductor talks to you when it's not urgent enough
to block on. It drops timestamped markdown files into the vault's board
directory, organized by type.

Types:
  - alert: Something needs attention soon (but not blocking)
  - question: The agent needs human input to proceed on something
  - observation: FYI — noticed something worth knowing
  - suggestion: Idea for improvement, not actionable without approval

The human checks the board when they feel like it. The agent never blocks
on a response. If the agent needs a response to proceed, it logs the
question and moves on to other work.

Board location: {vault}/conductor/board/{type}-{timestamp}.md
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class MessageType(StrEnum):
    ALERT = "alert"
    QUESTION = "question"
    OBSERVATION = "observation"
    SUGGESTION = "suggestion"


class MessageBoard:
    """Writes non-urgent messages from the agent to the human."""

    def __init__(self, vault_path: str | Path) -> None:
        self._board_dir = Path(vault_path) / "conductor" / "board"
        self._board_dir.mkdir(parents=True, exist_ok=True)

    def post(
        self,
        msg_type: MessageType,
        title: str,
        body: str,
        *,
        source: str = "",
        priority: str = "normal",
    ) -> Path:
        """Post a message to the board.

        Returns the path to the created file.
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        slug = title.lower().replace(" ", "-")[:40]
        filename = f"{msg_type.value}-{timestamp}-{slug}.md"
        path = self._board_dir / filename

        icon = {
            MessageType.ALERT: "🔴",
            MessageType.QUESTION: "❓",
            MessageType.OBSERVATION: "👁",
            MessageType.SUGGESTION: "💡",
        }.get(msg_type, "📝")

        content = (
            f"# {icon} {title}\n\n"
            f"**Type:** {msg_type.value} | "
            f"**Priority:** {priority} | "
            f"**Time:** {now.isoformat()}\n"
        )
        if source:
            content += f"**Source:** {source}\n"
        content += f"\n---\n\n{body}\n"

        path.write_text(content, encoding="utf-8")
        logger.info("Board post: [%s] %s → %s", msg_type.value, title, path.name)
        return path

    def alert(self, title: str, body: str, **kwargs) -> Path:
        return self.post(MessageType.ALERT, title, body, priority="high", **kwargs)

    def question(self, title: str, body: str, **kwargs) -> Path:
        return self.post(MessageType.QUESTION, title, body, **kwargs)

    def observation(self, title: str, body: str, **kwargs) -> Path:
        return self.post(MessageType.OBSERVATION, title, body, **kwargs)

    def suggestion(self, title: str, body: str, **kwargs) -> Path:
        return self.post(MessageType.SUGGESTION, title, body, **kwargs)

    def list_unread(self) -> list[Path]:
        """List all board messages (newest first)."""
        files = sorted(self._board_dir.glob("*.md"), reverse=True)
        return files

    def count_by_type(self) -> dict[str, int]:
        """Count messages by type."""
        counts: dict[str, int] = {}
        for path in self._board_dir.glob("*.md"):
            msg_type = path.name.split("-")[0]
            counts[msg_type] = counts.get(msg_type, 0) + 1
        return counts


class WebhookDelivery:
    """Delivers board messages and heartbeat results to HTTP endpoints."""

    def __init__(self, webhooks: list[dict] | None = None) -> None:
        """
        webhooks: list of {"url": "https://...", "events": ["alert", "question"], "token": "..."}
        """
        self._webhooks = webhooks or []

    async def deliver(self, msg_type: str, title: str, body: str) -> list[dict]:
        """Send a message to all matching webhooks. Returns delivery results."""
        if not self._webhooks:
            return []

        import httpx

        results = []
        for hook in self._webhooks:
            events = hook.get("events", ["alert"])  # default: alerts only
            if msg_type not in events and "*" not in events:
                continue

            url = hook.get("url", "")
            if not url:
                continue

            headers = {"Content-Type": "application/json"}
            token = hook.get("token")
            if token:
                headers["Authorization"] = f"Bearer {token}"

            payload = {
                "type": msg_type,
                "title": title,
                "body": body,
                "source": "conductor",
            }

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    results.append({
                        "url": url, "status": resp.status_code, "ok": resp.is_success
                    })
            except Exception as exc:
                results.append({"url": url, "status": 0, "ok": False, "error": str(exc)})
                logger.debug("Webhook delivery failed to %s: %s", url, exc)

        return results
