"""
Memory Evolution History — Git-tracked snapshots of all memory mutations.

Every time the APM, episodic memory, or any persistent surface changes,
this module records the change with a commit message explaining what and why.
The human can:
  - `git log memory/` to see all changes
  - `git diff HEAD~3 memory/` to see what changed recently
  - `git revert <hash>` to undo a change the agent made
  - Edit a memory file and the agent picks up the change on next heartbeat

Structure in git:
  memory/
    apm.yaml                    — Agent Personality Matrix
    episodic/
      snapshot-{timestamp}.json — Periodic full dumps of memory state
    board/                      — Message board posts (already in vault)
    evolution.log               — Append-only log of all mutations

This is NOT a database — the database (PostgreSQL) is the source of truth for
episodic memories. This is an audit trail and human-editable interface.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class EvolutionHistory:
    """Tracks and versions all memory mutations in git."""

    def __init__(self, memory_dir: str | Path) -> None:
        self._dir = Path(memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / "episodic").mkdir(exist_ok=True)
        self._log_path = self._dir / "evolution.log"
        self._git_initialized = False

    def _ensure_git(self) -> bool:
        """Ensure the memory directory is git-tracked."""
        if self._git_initialized:
            return True

        git_dir = self._dir / ".git"
        if not git_dir.exists():
            try:
                subprocess.run(
                    ["git", "init"],
                    cwd=self._dir, capture_output=True, check=True,
                )
                subprocess.run(
                    ["git", "config", "user.name", "Conductor Agent"],
                    cwd=self._dir, capture_output=True, check=True,
                )
                subprocess.run(
                    ["git", "config", "user.email", "conductor@emeraldfam.org"],
                    cwd=self._dir, capture_output=True, check=True,
                )
                logger.info("Initialized git repo for memory evolution at %s", self._dir)
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                logger.warning("Failed to initialize git for memory evolution: %s", exc)
                return False

        self._git_initialized = True
        return True

    def record_mutation(
        self,
        surface: str,
        action: str,
        description: str,
        *,
        details: dict | None = None,
    ) -> None:
        """Record a memory mutation to the evolution log and git.

        Args:
            surface: Which persistent surface changed (apm, episodic, board, etc.)
            action: What happened (create, update, reinforce, contradict, delete, prune)
            description: Human-readable explanation of what changed and why
            details: Optional structured data about the change
        """
        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "surface": surface,
            "action": action,
            "description": description,
        }
        if details:
            entry["details"] = details  # type: ignore[assignment]

        # Append to evolution log
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        logger.debug("Evolution: [%s] %s — %s", surface, action, description)

    def snapshot_episodic(self, memories: list[dict]) -> Path:
        """Dump a snapshot of all episodic memories to a JSON file.

        Called periodically by the heartbeat for human review.
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        path = self._dir / "episodic" / f"snapshot-{timestamp}.json"

        snapshot = {
            "timestamp": now.isoformat(),
            "count": len(memories),
            "memories": memories,
        }
        path.write_text(
            json.dumps(snapshot, indent=2, default=str),
            encoding="utf-8",
        )

        logger.info("Episodic snapshot: %d memories → %s", len(memories), path.name)
        return path

    def commit(self, message: str) -> bool:
        """Stage all changes in the memory dir and commit.

        Returns True if a commit was made, False if nothing to commit.
        """
        if not self._ensure_git():
            return False

        try:
            # Stage everything
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self._dir, capture_output=True, check=True,
            )

            # Check if there's anything to commit
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self._dir, capture_output=True, text=True, check=True,
            )
            if not status.stdout.strip():
                return False  # Nothing to commit

            # Commit
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self._dir, capture_output=True, check=True,
            )
            logger.info("Evolution commit: %s", message)
            return True

        except subprocess.CalledProcessError as exc:
            logger.warning("Git commit failed: %s", exc)
            return False

    def get_recent_log(self, limit: int = 50) -> list[dict]:
        """Read the most recent N entries from the evolution log."""
        if not self._log_path.exists():
            return []

        entries = []
        try:
            lines = self._log_path.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-limit:]:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        return entries

    def get_git_log(self, limit: int = 20) -> list[str]:
        """Get recent git commits for the memory directory."""
        if not self._ensure_git():
            return []

        try:
            result = subprocess.run(
                ["git", "log", f"--max-count={limit}", "--oneline"],
                cwd=self._dir, capture_output=True, text=True, check=True,
            )
            return result.stdout.strip().splitlines()
        except subprocess.CalledProcessError:
            return []
