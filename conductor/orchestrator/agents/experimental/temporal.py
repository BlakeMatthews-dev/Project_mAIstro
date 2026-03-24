"""
Temporal Intelligence — Pattern recognition, mood ring, and time capsules.

Three features that give the conductor temporal awareness:

1. Pattern Recognition — Discovers recurring patterns across time by
   analyzing memory timestamps, system metrics, and task outcomes.
   "Disk spikes every Tuesday at 2am" / "GPU crashes every 11 days"

2. Mood Ring — Adaptive behavior based on real-time system health.
   Healthy system → adventurous (explore new variants, run stress rehearsals)
   Stressed system → conservative (proven variants only, skip optional work)

3. Time Capsules — Scheduled self-reminders with context.
   "In 30 days, check if Keycloak migration is done."
   When capsule opens, re-evaluates with current data.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Mood Ring
# ──────────────────────────────────────────────────────────────────

class Mood(StrEnum):
    ADVENTUROUS = "adventurous"    # Healthy: explore, experiment, dream more
    NORMAL = "normal"              # Baseline: standard operations
    CAUTIOUS = "cautious"          # Some pressure: reduce exploration
    CONSERVATIVE = "conservative"  # Stressed: proven paths only, alert more


class MoodRing:
    """Computes system mood from vitals — affects exploration and behavior."""

    def __init__(self) -> None:
        self._current_mood = Mood.NORMAL
        self._vitals: dict = {}

    async def assess(self) -> Mood:
        """Read system vitals and compute current mood."""
        
        stress_score = 0  # 0 = healthy, higher = more stressed

        # Disk pressure
        try:
            import asyncio as _aio
            proc = await _aio.create_subprocess_exec(
                "df", "--output=pcent", "/",
                stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.PIPE,
            )
            stdout, _ = await _aio.wait_for(proc.communicate(), timeout=5)
            pct = int(stdout.decode().strip().splitlines()[-1].strip().rstrip("%"))
            self._vitals["disk_pct"] = pct
            if pct > 85:
                stress_score += 3
            elif pct > 70:
                stress_score += 1
        except Exception:
            pass

        # GPU temperature
        try:
            proc = await _aio.create_subprocess_exec(
                "nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits",
                stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.PIPE,
            )
            stdout, _ = await _aio.wait_for(proc.communicate(), timeout=5)
            temp = float(stdout.decode().strip().split("\n")[0])
            self._vitals["gpu_temp"] = temp
            if temp > 80:
                stress_score += 3
            elif temp > 65:
                stress_score += 1
        except Exception:
            pass

        # Quota pressure (check via router API)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    "http://localhost:8100/status/quota-daily",
                    headers={"Authorization": f"Bearer {os.environ.get('ROUTER_API_KEY', '')}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    overage_count = sum(
                        1 for v in data.values()
                        if isinstance(v, dict) and v.get("overage")
                    )
                    self._vitals["providers_over_budget"] = overage_count
                    stress_score += overage_count * 2
        except Exception:
            pass

        # Compute mood
        if stress_score == 0:
            self._current_mood = Mood.ADVENTUROUS
        elif stress_score <= 2:
            self._current_mood = Mood.NORMAL
        elif stress_score <= 4:
            self._current_mood = Mood.CAUTIOUS
        else:
            self._current_mood = Mood.CONSERVATIVE

        self._vitals["stress_score"] = stress_score
        self._vitals["mood"] = self._current_mood.value
        logger.debug("Mood assessment: %s (stress=%d)", self._current_mood, stress_score)
        return self._current_mood

    @property
    def mood(self) -> Mood:
        return self._current_mood

    @property
    def vitals(self) -> dict:
        return dict(self._vitals)

    def get_exploration_rate(self, base_rate: float = 0.1) -> float:
        """Adjust exploration rate based on mood."""
        multipliers = {
            Mood.ADVENTUROUS: 2.0,    # Double exploration
            Mood.NORMAL: 1.0,         # Baseline
            Mood.CAUTIOUS: 0.5,       # Half exploration
            Mood.CONSERVATIVE: 0.0,   # No exploration — proven paths only
        }
        return base_rate * multipliers.get(self._current_mood, 1.0)

    def should_dream(self) -> bool:
        """Whether to run dream loop this heartbeat."""
        return self._current_mood in (Mood.ADVENTUROUS, Mood.NORMAL)

    def should_run_stress_rehearsal(self) -> bool:
        """Whether to run stress rehearsals (controlled chaos) this heartbeat."""
        return self._current_mood == Mood.ADVENTUROUS

    def should_run_red_team(self) -> bool:
        """Whether to run red team exercises."""
        return self._current_mood in (Mood.ADVENTUROUS, Mood.NORMAL)


# ──────────────────────────────────────────────────────────────────
# Time Capsules
# ──────────────────────────────────────────────────────────────────

class TimeCapsule:
    """Scheduled self-reminders with context-aware re-evaluation."""

    def __init__(self, capsule_dir: str | Path) -> None:
        self._dir = Path(capsule_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        title: str,
        concern: str,
        open_after: datetime,
        *,
        check_condition: str = "",
        context: dict | None = None,
    ) -> Path:
        """Create a time capsule that opens after a specified date.

        Args:
            title: Short description
            concern: What to check when the capsule opens
            open_after: When to open (UTC datetime)
            check_condition: How to verify if the concern is resolved
            context: Snapshot of relevant state at creation time
        """
        capsule = {
            "title": title,
            "concern": concern,
            "check_condition": check_condition,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "open_after": open_after.isoformat(),
            "context": context or {},
            "status": "sealed",
        }

        slug = title.lower().replace(" ", "-")[:30]
        ts = open_after.strftime("%Y%m%d")
        filename = f"capsule-{ts}-{slug}.json"
        path = self._dir / filename
        path.write_text(json.dumps(capsule, indent=2, default=str), encoding="utf-8")
        logger.info("Time capsule created: %s (opens %s)", title, open_after.date())
        return path

    def check_due(self) -> list[dict]:
        """Check for capsules that are due to open."""
        now = datetime.now(timezone.utc)
        due = []

        for path in self._dir.glob("capsule-*.json"):
            try:
                capsule = json.loads(path.read_text(encoding="utf-8"))
                if capsule.get("status") != "sealed":
                    continue
                open_after = datetime.fromisoformat(capsule["open_after"])
                if now >= open_after:
                    capsule["_path"] = str(path)
                    due.append(capsule)
            except Exception:
                pass

        return due

    def resolve(self, path: str | Path, resolution: str) -> None:
        """Mark a capsule as resolved with a resolution note."""
        p = Path(path)
        if not p.exists():
            return
        capsule = json.loads(p.read_text(encoding="utf-8"))
        capsule["status"] = "resolved"
        capsule["resolved_at"] = datetime.now(timezone.utc).isoformat()
        capsule["resolution"] = resolution
        p.write_text(json.dumps(capsule, indent=2, default=str), encoding="utf-8")

    def list_all(self) -> list[dict]:
        """List all capsules (sealed and resolved)."""
        capsules = []
        for path in sorted(self._dir.glob("capsule-*.json")):
            try:
                capsule = json.loads(path.read_text(encoding="utf-8"))
                capsule["_path"] = str(path)
                capsules.append(capsule)
            except Exception:
                pass
        return capsules


# ──────────────────────────────────────────────────────────────────
# Temporal Pattern Recognition
# ──────────────────────────────────────────────────────────────────

class PatternRecognizer:
    """Discovers recurring temporal patterns in memory and system metrics."""

    def __init__(self, episodic_memory=None) -> None:
        self._memory = episodic_memory

    async def analyze(self) -> list[dict]:
        """Analyze memories for temporal patterns.

        Looks for:
        - Recurring observations at similar times
        - Periodic failures (regrets) with regular intervals
        - Day-of-week correlations
        """
        if not self._memory or not self._memory._pool:
            return []

        patterns = []

        async with self._memory._pool.acquire() as conn:
            # Find observations that repeat with similar content
            rows = await conn.fetch("""
                SELECT content,
                       COUNT(*) as occurrences,
                       ARRAY_AGG(created_at ORDER BY created_at) as timestamps
                FROM memories
                WHERE tier = 'observation' AND NOT deleted
                GROUP BY content
                HAVING COUNT(*) >= 3
                ORDER BY COUNT(*) DESC
                LIMIT 10
            """)

            for row in rows:
                timestamps = row["timestamps"]
                if len(timestamps) >= 3:
                    # Calculate intervals between occurrences
                    intervals = []
                    for i in range(1, len(timestamps)):
                        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
                        intervals.append(delta)

                    avg_interval = sum(intervals) / len(intervals)
                    # Check if intervals are regular (stddev < 20% of mean)
                    if avg_interval > 0:
                        variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
                        stddev = variance ** 0.5
                        regularity = 1.0 - min(1.0, stddev / avg_interval) if avg_interval > 0 else 0

                        if regularity > 0.6:  # Pretty regular
                            # Convert to human-readable interval
                            hours = avg_interval / 3600
                            if hours < 24:
                                interval_str = f"every {hours:.0f} hours"
                            elif hours < 168:
                                interval_str = f"every {hours/24:.0f} days"
                            else:
                                interval_str = f"every {hours/168:.0f} weeks"

                            patterns.append({
                                "content": row["content"][:100],
                                "occurrences": row["occurrences"],
                                "interval": interval_str,
                                "regularity": round(regularity, 2),
                                "avg_interval_hours": round(hours, 1),
                            })

            # Find day-of-week correlations for regrets
            rows = await conn.fetch("""
                SELECT EXTRACT(DOW FROM created_at)::int as dow,
                       COUNT(*) as count
                FROM memories
                WHERE tier = 'regret' AND NOT deleted
                GROUP BY EXTRACT(DOW FROM created_at)::int
                HAVING COUNT(*) >= 2
                ORDER BY COUNT(*) DESC
            """)

            day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            if rows:
                total_regrets = sum(r["count"] for r in rows)
                for row in rows:
                    pct = row["count"] / total_regrets
                    if pct > 0.3:  # 30%+ of regrets on one day = pattern
                        patterns.append({
                            "content": f"Regrets cluster on {day_names[row['dow']]}s ({row['count']}/{total_regrets})",
                            "occurrences": row["count"],
                            "interval": f"weekly on {day_names[row['dow']]}",
                            "regularity": round(pct, 2),
                        })

        return patterns
