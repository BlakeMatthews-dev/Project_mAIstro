"""
Heartbeat Loop — Autonomous initiative engine for the conductor.

The heartbeat gives the conductor proactive agency. Instead of only responding
when a human drops a task in the inbox, it periodically wakes up and evaluates
whether it should act on its own.

Cycle (every N minutes):
  1. Load APM → read standing orders
  2. Check task queue → any pending inbox work?
  3. Evaluate standing orders → any due for execution?
  4. Run due actions as isolated agent turns
  5. Post results to message board / changelog
  6. Update memory (observations, lessons from the cycle)
  7. Commit evolution history
  8. Sleep until next heartbeat

The heartbeat runs ALONGSIDE the reactive inbox watcher. They don't conflict:
- Inbox watcher: responds to human-initiated tasks (event-driven)
- Heartbeat: runs standing orders and proactive checks (time-driven)

Standing orders are defined in the APM under `standing_orders`. Each has:
  - name: human-readable label
  - schedule: "every N hours", "daily at Xam", "weekly on day"
  - action: what to do (free text, interpreted by the heartbeat)
  - escalate_if: condition that triggers a board alert
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class Heartbeat:
    """Autonomous heartbeat loop — periodic evaluation and action."""

    def __init__(
        self,
        apm=None,                  # AgentPersonalityMatrix
        episodic_memory=None,      # EpisodicMemory
        board=None,                # MessageBoard
        evolution=None,            # EvolutionHistory
        trace_reviewer=None,       # TraceReviewer
        prompt_evolver=None,       # PromptEvolver
        recipe_registry=None,      # RecipeRegistry
        bouncer=None,              # Bouncer (for red team)
        scanner=None,              # SkillScanner (for red team)
        interval_minutes: int = 30,
    ) -> None:
        self._apm = apm
        self._memory = episodic_memory
        self._board = board
        self._evolution = evolution
        self._trace_reviewer = trace_reviewer
        self._prompt_evolver = prompt_evolver
        self._recipe_registry = recipe_registry
        self._interval = interval_minutes * 60  # seconds
        self._running = False
        self._last_run_times: dict[str, datetime] = {}
        self._cycle_count = 0
        # Circuit breaker: track consecutive failures per standing order
        self._order_failures: dict[str, int] = {}
        self._order_disabled: set[str] = set()
        self._max_consecutive_failures = 3

        # Advanced features
        from .agents.experimental.dream_loop import DreamLoop
        from .agents.experimental.red_team import RedTeamExercise
        from .agents.experimental.temporal import MoodRing, PatternRecognizer, TimeCapsule
        from .agents.experimental.skill_forge import SkillForge
        from .agents.experimental.stress_rehearsal import StressRehearsal
        from .agents.experimental.tournament import ModelArena

        self._mood = MoodRing()
        self._dream = DreamLoop(
            episodic_memory=episodic_memory,
            board=board,
            evolution=evolution,
        )
        self._capsules = TimeCapsule(
            Path(apm._path).parent / "capsules" if apm else Path("./capsules")
        )
        self._patterns = PatternRecognizer(episodic_memory=episodic_memory)
        self._red_team = RedTeamExercise(
            bouncer=bouncer,
            scanner=scanner,
            episodic_memory=episodic_memory,
            board=board,
            evolution=evolution,
        )
        self._skill_forge = SkillForge(
            skills_dir=Path(apm._path).parent.parent / "skills" if apm else Path("./skills"),
            scanner=scanner,
            episodic_memory=episodic_memory,
            board=board,
            evolution=evolution,
        )
        self._stress = StressRehearsal(
            episodic_memory=episodic_memory,
            board=board,
            evolution=evolution,
        )
        self._arena = ModelArena()
        self._arena_initialized = False

    async def start(self) -> None:
        """Start the heartbeat loop. Runs until stop() is called."""
        self._running = True
        logger.info(
            "Heartbeat started (interval: %d minutes)", self._interval // 60
        )

        while self._running:
            try:
                await self._beat()
            except Exception as exc:
                logger.error("Heartbeat cycle failed: %s", exc, exc_info=True)
                if self._board:
                    self._board.alert(
                        "Heartbeat cycle failed",
                        f"Error during heartbeat cycle #{self._cycle_count}:\n\n```\n{exc}\n```",
                        source="heartbeat",
                    )

            # Sleep until next beat
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False
        logger.info("Heartbeat stopped after %d cycles", self._cycle_count)

    async def _beat(self) -> None:
        """Execute one heartbeat cycle."""
        self._cycle_count += 1
        start = time.monotonic()
        now = datetime.now(timezone.utc)
        actions_taken = 0

        logger.info("Heartbeat #%d starting", self._cycle_count)

        # 1. Reload APM (human may have edited it)
        if self._apm:
            self._apm.reload()

        # 2. Evaluate standing orders
        if self._apm:
            for order in self._apm.standing_orders:
                order_name = order.get("name", "unnamed")
                schedule = order.get("schedule", "")
                _action = order.get("action", "")  # Used by execute_standing_order via order dict

                if not self._is_due(order_name, schedule, now):
                    continue

                # Circuit breaker — skip disabled orders
                if order_name in self._order_disabled:
                    continue

                logger.info("Standing order due: %s", order_name)
                self._last_run_times[order_name] = now

                try:
                    result = await self._execute_standing_order(order)
                    actions_taken += 1
                    # Reset failure count on success
                    self._order_failures[order_name] = 0

                    # Check escalation condition
                    escalate_if = order.get("escalate_if", "")
                    if escalate_if and result.get("should_escalate"):
                        if self._board:
                            self._board.alert(
                                f"Standing order escalation: {order_name}",
                                f"**Condition:** {escalate_if}\n\n"
                                f"**Finding:** {result.get('escalation_reason', 'N/A')}",
                                source=f"heartbeat/standing-order/{order_name}",
                            )

                except Exception as exc:
                    # Circuit breaker: track consecutive failures
                    fails = self._order_failures.get(order_name, 0) + 1
                    self._order_failures[order_name] = fails
                    logger.warning(
                        "Standing order '%s' failed (%d/%d): %s",
                        order_name, fails, self._max_consecutive_failures, exc,
                    )
                    if fails >= self._max_consecutive_failures:
                        self._order_disabled.add(order_name)
                        logger.error(
                            "Circuit breaker TRIPPED: '%s' disabled after %d consecutive failures",
                            order_name, fails,
                        )
                        if self._board:
                            self._board.alert(
                                f"Standing order disabled: {order_name}",
                                f"**Disabled after {fails} consecutive failures.**\n\n"
                                f"Last error: {exc}\n\n"
                                f"Re-enable by restarting the conductor service.",
                                source="heartbeat/circuit-breaker",
                            )

        # 3. Mood assessment
        mood = await self._mood.assess()
        logger.info("Mood: %s (stress=%d)", mood, self._mood.vitals.get("stress_score", 0))

        # 4. Memory review (every 10th cycle)
        if self._memory and self._cycle_count % 10 == 0:
            await self._review_memories()
            actions_taken += 1

        # 5. Dream loop (when idle and mood allows)
        if self._mood.should_dream() and self._cycle_count % 5 == 0:
            try:
                dream_result = await self._dream.dream()
                actions_taken += 1
                logger.info("Dream: %s", dream_result)
            except Exception as exc:
                logger.debug("Dream loop failed: %s", exc)

        # 6. Time capsules — check for due capsules
        due_capsules = self._capsules.check_due()
        for capsule in due_capsules:
            if self._board:
                self._board.question(
                    f"Time capsule opened: {capsule['title']}",
                    f"**Original concern:** {capsule['concern']}\n\n"
                    f"**Check condition:** {capsule.get('check_condition', 'N/A')}\n\n"
                    f"**Created:** {capsule['created_at']}\n\n"
                    f"Please verify if this concern is still relevant.",
                    source="time-capsule",
                )
            self._capsules.resolve(capsule["_path"], "Opened and posted to board")
            actions_taken += 1

        # 7. Temporal pattern recognition (every 20th cycle)
        if self._cycle_count % 20 == 0:
            try:
                patterns = await self._patterns.analyze()
                if patterns and self._board:
                    pattern_text = "\n".join(
                        f"- {p['content']} ({p['interval']}, regularity={p['regularity']})"
                        for p in patterns
                    )
                    self._board.observation(
                        f"Temporal patterns discovered: {len(patterns)}",
                        pattern_text,
                        source="temporal-pattern-recognition",
                    )
                    actions_taken += 1
            except Exception as exc:
                logger.debug("Pattern recognition failed: %s", exc)

        # 8. Red team exercise (weekly, if mood allows)
        if self._mood.should_run_red_team() and self._cycle_count % 336 == 1:  # ~weekly at 30min intervals
            try:
                red_result = await self._red_team.run_exercise()
                actions_taken += 1
                logger.info("Red team: %s", red_result)
            except Exception as exc:
                logger.debug("Red team failed: %s", exc)

        # 9. Skill forge — suggest new skills from observed patterns (~daily)
        if self._cycle_count % 48 == 0 and self._cycle_count > 0:
            try:
                # Gather recent failures from the vault's failed/ directory
                recent_failures = []
                failed_dir = self._skill_forge._dir.parent / "vault" / "conductor" / "failed"
                if failed_dir.exists():
                    for f in sorted(failed_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                        recent_failures.append({"filename": f.name, "content": f.read_text(encoding="utf-8")[:500]})
                suggestions = await self._skill_forge.suggest_skills(recent_failures)
                if suggestions and self._board:
                    self._board.suggestion(
                        f"Skill Forge: {len(suggestions)} skill suggestion(s)",
                        "\n".join(f"- {s}" for s in suggestions[:5]),
                        source="heartbeat/skill-forge",
                    )
                actions_taken += 1
                logger.info("Skill forge: %d suggestions", len(suggestions) if suggestions else 0)
            except Exception as exc:
                logger.debug("Skill forge failed: %s", exc)

        # 10. Stress rehearsal (~biweekly, requires ADVENTUROUS mood)
        if (self._mood.should_run_stress_rehearsal()
                and self._cycle_count % 672 == 1  # ~biweekly at 30min intervals
                and self._cycle_count > 1):
            try:
                stress_result = await self._stress.run_rehearsal()
                actions_taken += 1
                logger.info("Stress rehearsal: %s", stress_result)
            except Exception as exc:
                logger.debug("Stress rehearsal failed: %s", exc)

        # 11. Model Arena — initialize if needed (lazy, once)
        if not self._arena_initialized and self._memory:
            try:
                await self._arena.initialize()
                self._arena_initialized = True
                logger.info("Model Arena initialized")
            except Exception as exc:
                logger.debug("Model Arena init failed (will retry): %s", exc)

        # Commit evolution history
        if self._evolution:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._evolution.record_mutation(
                surface="heartbeat",
                action="cycle",
                description=f"Heartbeat #{self._cycle_count}: "
                            f"{actions_taken} actions in {elapsed_ms:.0f}ms",
            )
            self._evolution.commit(
                f"heartbeat #{self._cycle_count}: {actions_taken} actions"
            )

        elapsed = time.monotonic() - start
        logger.info(
            "Heartbeat #%d complete: %d actions, %.1fs",
            self._cycle_count, actions_taken, elapsed,
        )

    def _is_due(self, order_name: str, schedule: str, now: datetime) -> bool:
        """Check if a standing order is due based on its schedule string.

        Supported formats:
          "every N hours"
          "every N minutes"
          "daily at Ham"  (e.g., "daily at 3am")
          "weekly on sunday"
        """
        last = self._last_run_times.get(order_name)
        schedule_lower = schedule.lower().strip()

        # "every N hours/minutes"
        m = re.match(r"every\s+(\d+)\s+(hour|minute)s?", schedule_lower)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            delta = timedelta(hours=n) if unit == "hour" else timedelta(minutes=n)
            if last is None:
                return True  # Never run → run now
            return now - last >= delta

        # "daily at Xam/Xpm"
        m = re.match(r"daily\s+at\s+(\d{1,2})(am|pm)?", schedule_lower)
        if m:
            hour = int(m.group(1))
            if m.group(2) == "pm" and hour < 12:
                hour += 12
            if last and last.date() == now.date():
                return False  # Already ran today
            return now.hour >= hour

        # "weekly on DAY"
        m = re.match(
            r"weekly\s+on\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
            schedule_lower,
        )
        if m:
            day_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6,
            }
            target_day = day_map[m.group(1)]
            if now.weekday() != target_day:
                return False
            if last and last.date() == now.date():
                return False
            return True

        # Unknown schedule — run every cycle as fallback
        logger.debug("Unknown schedule format: %r — running every cycle", schedule)
        return True

    async def _execute_standing_order(self, order: dict) -> dict:
        """Execute a standing order and return the result.

        Routes to specific handlers based on the order name/action.
        """
        name = order.get("name", "").lower()
        action = order.get("action", "")
        result: dict = {"executed": True, "should_escalate": False}

        # Infrastructure health check
        if "health check" in name or "infrastructure" in name:
            result = await self._check_infrastructure_health()

        # Prompt evolution
        elif "prompt evolution" in name or "prompt evolver" in name:
            result = await self._run_prompt_evolution()

        # Memory review
        elif "memory review" in name:
            await self._review_memories()

        # Trace review
        elif "trace review" in name:
            result = await self._run_trace_review()

        # Skill security scan
        elif "skill" in name and "scan" in name:
            result = await self._run_skill_scan()

        # Quota pressure check
        elif "quota" in name:
            result = await self._check_quota_pressure()

        # Generic — post the action to the board as a reminder
        else:
            if self._board:
                self._board.observation(
                    f"Standing order: {order.get('name', 'unnamed')}",
                    f"Action needed: {action}\n\n"
                    f"*This standing order doesn't have a built-in handler yet.*",
                    source="heartbeat",
                )

        return result

    async def _check_infrastructure_health(self) -> dict:
        """Check disk, GPU, container health."""
        import subprocess as sp

        findings = []
        should_escalate = False

        # Disk usage
        try:
            result = sp.run(
                ["df", "-h", "/", "/vmpool"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    use_pct = int(parts[4].rstrip("%"))
                    mount = parts[5]
                    if use_pct > 80:
                        findings.append(f"WARN: {mount} at {use_pct}%")
                        should_escalate = True
                    elif use_pct > 60:
                        findings.append(f"INFO: {mount} at {use_pct}%")
        except Exception as exc:
            findings.append(f"ERROR: disk check failed: {exc}")

        # GPU
        try:
            result = sp.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 4:
                    temp = float(parts[0])
                    if temp > 80:
                        findings.append(f"WARN: GPU at {temp}°C")
                        should_escalate = True
                    else:
                        findings.append(f"INFO: GPU {temp}°C, {parts[2]}/{parts[3]}MB")
        except Exception:
            findings.append("INFO: GPU check skipped (nvidia-smi not available)")

        # Store observation memory
        if self._memory and findings:
            from .memory.episodic import MemoryTier
            summary = "; ".join(findings)
            await self._memory.store(
                MemoryTier.OBSERVATION,
                f"Infrastructure health check: {summary}",
                source="heartbeat/infra-check",
            )

        # Post to board if escalating
        if should_escalate and self._board:
            self._board.alert(
                "Infrastructure health warning",
                "\n".join(f"- {f}" for f in findings),
                source="heartbeat/infra-check",
            )

        return {
            "executed": True,
            "findings": findings,
            "should_escalate": should_escalate,
            "escalation_reason": "; ".join(
                f for f in findings if f.startswith("WARN")
            ),
        }

    async def _run_prompt_evolution(self) -> dict:
        """Run the PromptEvolver on all recipes."""
        if not self._prompt_evolver or not self._recipe_registry:
            return {"executed": False, "reason": "evolver not configured"}

        results = self._prompt_evolver.evolve_all(self._recipe_registry)
        actions = [r for r in results if r.action != "hold"]

        if actions and self._board:
            lines = []
            for r in actions:
                lines.append(
                    f"- **{r.recipe_name}**: {r.action} "
                    f"({r.from_variant} → {r.to_variant}, "
                    f"confidence={r.confidence:.0%})"
                )
            self._board.suggestion(
                "Prompt evolution results",
                f"{len(actions)} action(s) from {len(results)} recipes:\n\n"
                + "\n".join(lines),
                source="heartbeat/prompt-evolver",
            )

        return {
            "executed": True,
            "recipes_evaluated": len(results),
            "actions_pending": len(actions),
            "should_escalate": any(
                r.action == "suggest_new" for r in results
            ),
            "escalation_reason": "Production variant underperforming"
            if any(r.action == "suggest_new" for r in results)
            else "",
        }

    async def _review_memories(self) -> None:
        """Review weak memories and update evolution history."""
        if not self._memory:
            return

        weak = await self._memory.review_weak_memories()
        stats = await self._memory.get_stats()

        if self._evolution:
            self._evolution.record_mutation(
                surface="episodic",
                action="review",
                description=f"Memory review: {stats['total']} total, "
                            f"{stats['weak_count']} weak",
                details=stats,
            )

        if weak and self._board:
            self._board.observation(
                f"Memory review: {len(weak)} weak memories",
                f"Total memories: {stats['total']}\n"
                f"Weak (< {0.15}): {len(weak)}\n\n"
                f"**Candidates for pruning:**\n"
                + "\n".join(
                    f"- [{m.tier.value}] (w={m.weight:.2f}) {m.content[:80]}..."
                    for m in weak[:10]
                ),
                source="heartbeat/memory-review",
            )

    async def _run_trace_review(self) -> dict:
        """Run the TraceReviewer and post findings."""
        if not self._trace_reviewer:
            return {"executed": False, "reason": "trace reviewer not configured"}

        try:
            report = await self._trace_reviewer.review()
            actions = [f for f in report.findings if f.severity == "action"]

            if actions and self._board:
                lines = [f"- [{f.category}] {f.title}" for f in actions]
                self._board.alert(
                    f"Trace review: {len(actions)} action items",
                    f"{report.summary}\n\n" + "\n".join(lines),
                    source="heartbeat/trace-review",
                )

            return {
                "executed": True,
                "findings": len(report.findings),
                "should_escalate": len(actions) > 0,
                "escalation_reason": f"{len(actions)} action items in trace review",
            }
        except Exception as exc:
            return {"executed": False, "reason": str(exc)}

    async def _run_skill_scan(self) -> dict:
        """Re-scan loaded skills for new vulnerabilities via PhantomExecutor."""
        from .agents.experimental.phantom import PhantomExecutor

        phantom = PhantomExecutor()
        violations_found = []

        # Scan all skill .md files in the forge directory
        skills_dir = self._skill_forge._dir if self._skill_forge else None
        if not skills_dir or not skills_dir.exists():
            return {"executed": True, "should_escalate": False, "reason": "no skills dir"}

        for skill_file in skills_dir.glob("*.md"):
            try:
                content = skill_file.read_text(encoding="utf-8")
                result = phantom.analyze_skill_instructions(
                    skill_name=skill_file.stem,
                    instructions=content,
                    declared_env=[],
                    declared_bins=[],
                )
                if not result.safe:
                    violations_found.append(
                        f"{skill_file.stem}: {', '.join(result.violations)}"
                    )
            except Exception as exc:
                logger.debug("Skill scan failed for %s: %s", skill_file.stem, exc)

        if violations_found and self._board:
            self._board.alert(
                f"Skill scan: {len(violations_found)} violation(s) found",
                "\n".join(f"- {v}" for v in violations_found),
                source="heartbeat/skill-scan",
            )

        return {
            "executed": True,
            "skills_scanned": len(list(skills_dir.glob("*.md"))),
            "violations": len(violations_found),
            "should_escalate": len(violations_found) > 0,
            "escalation_reason": f"{len(violations_found)} skill violations found",
        }

    async def _check_quota_pressure(self) -> dict:
        """Check provider quota usage and project burn rate."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "http://localhost:8100/status/quota-daily",
                    headers={"Authorization": f"Bearer {os.environ.get('ROUTER_API_KEY', '')}"},
                )
                if resp.status_code != 200:
                    return {"executed": False, "reason": f"HTTP {resp.status_code}"}

                data = resp.json()
                warnings = []
                for provider, info in data.items():
                    if info.get("overage"):
                        warnings.append(
                            f"{provider}: OVER daily ration "
                            f"(used {info.get('used_today', 0):,} / "
                            f"ration {info.get('daily_ration', 0):,})"
                        )

                if warnings and self._board:
                    self._board.alert(
                        "Quota pressure warning",
                        "\n".join(f"- {w}" for w in warnings),
                        source="heartbeat/quota-check",
                    )

                return {
                    "executed": True,
                    "providers_checked": len(data),
                    "should_escalate": len(warnings) > 0,
                    "escalation_reason": "; ".join(warnings),
                }

        except Exception as exc:
            return {"executed": False, "reason": str(exc)}
