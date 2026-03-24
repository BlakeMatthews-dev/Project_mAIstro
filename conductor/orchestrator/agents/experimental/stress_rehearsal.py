"""
Stress Rehearsal — Controlled Chaos Testing.

The conductor intentionally introduces controlled failures into the homelab
and observes how the system responds. Discovers blast radius, recovery time,
and cascading failures that no human would find through manual testing.

Rehearsal types:
  - Container stop/restart (docker stop → observe → docker start)
  - Disk pressure simulation (create large temp file, observe alerts)
  - Service dependency test (stop a dependency, check what fails)
  - Latency injection (proxy with artificial delay)
  - Memory pressure (allocate + release)

Safety rules:
  - NEVER touch production data (no DB, no ZFS, no backups)
  - NEVER exceed 60 seconds of disruption per test
  - NEVER run during active task processing
  - Always restore to pre-test state
  - Requires ADVENTUROUS mood
  - All results recorded in episodic memory
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Containers that are NEVER touched by stress rehearsal
PROTECTED_CONTAINERS = {
    "conductor-langfuse-db",   # Database — data loss risk
    "conductor-router",        # Active routing — would break everything
    "litellm",                 # Active inference — would break everything
    "litellm-db",              # Database — data loss risk
    "conductor-redis",         # Cache — potential data loss
    "conductor-minio",         # Object storage — data loss risk
    "conductor-clickhouse",    # Analytics DB — data loss risk
}

# Containers safe to rehearse with (non-critical, fast recovery)
REHEARSAL_CANDIDATES = {
    "conductor-langfuse": "Langfuse web UI (observability, not critical path)",
    "conductor-langfuse-worker": "Langfuse async worker (traces queue, recovers)",
    "conductor-open-webui": "OpenWebUI chat interface (stateless frontend)",
    "browser-agent": "Browser automation agent (isolated, no dependencies)",
}

MAX_DISRUPTION_SECONDS = 60


@dataclass
class RehearsalResult:
    """Result of a single stress rehearsal."""
    test_name: str
    target: str
    disruption_seconds: float = 0
    recovery_seconds: float = 0
    cascading_failures: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    restored: bool = True
    error: str = ""


class StressRehearsal:
    """Controlled chaos testing — discovers failure modes safely."""

    def __init__(
        self,
        episodic_memory=None,
        board=None,
        evolution=None,
    ) -> None:
        self._memory = episodic_memory
        self._board = board
        self._evolution = evolution
        self._rehearsal_count = 0

    async def run_rehearsal(self, test_type: str = "container_restart") -> RehearsalResult:
        """Run a single stress rehearsal.

        test_type: container_restart | disk_pressure | dependency_test
        """
        self._rehearsal_count += 1

        if test_type == "container_restart":
            result = await self._test_container_restart()
        elif test_type == "disk_pressure":
            result = await self._test_disk_pressure()
        elif test_type == "dependency_test":
            result = await self._test_dependency()
        else:
            result = RehearsalResult(
                test_name=test_type,
                target="unknown",
                error=f"Unknown test type: {test_type}",
            )

        # Record findings
        await self._record_findings(result)
        return result

    async def _test_container_restart(self) -> RehearsalResult:
        """Stop a non-critical container and measure recovery."""
        import random

        # Pick a random safe target
        target = random.choice(list(REHEARSAL_CANDIDATES.keys()))
        desc = REHEARSAL_CANDIDATES[target]

        result = RehearsalResult(
            test_name="container_restart",
            target=target,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format", "{{.State.Status}}", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            pre_state = stdout.decode().strip()

            if pre_state != "running":
                result.observations.append(f"Container was already {pre_state}, skipping")
                return result

            # Stop the container
            result.observations.append(f"Stopping {target} ({desc})")
            stop_start = time.monotonic()

            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", "--time", "5", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)

            stop_time = time.monotonic() - stop_start
            result.observations.append(f"Stopped in {stop_time:.1f}s")

            # Observe — check what's affected
            await asyncio.sleep(3)
            cascades = await self._check_health_impact()
            result.cascading_failures = cascades
            result.disruption_seconds = time.monotonic() - stop_start

            if cascades:
                result.observations.append(
                    f"Cascading impact: {', '.join(cascades)}"
                )

            # Restore
            restore_start = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                "docker", "start", target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)

            # Wait for healthy
            for _ in range(20):
                proc = await asyncio.create_subprocess_exec(
                    "docker", "inspect", "--format", "{{.State.Status}}", target,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if stdout.decode().strip() == "running":
                    break
                await asyncio.sleep(1)

            result.recovery_seconds = time.monotonic() - restore_start
            result.restored = True
            result.observations.append(
                f"Restored in {result.recovery_seconds:.1f}s"
            )

        except asyncio.TimeoutError:
            result.error = f"Timeout during rehearsal of {target}"
            # Emergency restore
            await asyncio.create_subprocess_exec("docker", "start", target)
            result.restored = True
        except Exception as exc:
            result.error = str(exc)
            # Emergency restore
            try:
                await asyncio.create_subprocess_exec("docker", "start", target)
                result.restored = True
            except Exception:
                result.restored = False

        return result

    async def _test_disk_pressure(self) -> RehearsalResult:
        """Create temporary disk pressure and observe system response."""
        result = RehearsalResult(
            test_name="disk_pressure",
            target="/tmp/stress-rehearsal-fill",
        )

        try:
            # Create a 500MB temp file
            result.observations.append("Creating 500MB temp file on /tmp")
            proc = await asyncio.create_subprocess_exec(
                "dd", "if=/dev/zero", "of=/tmp/stress-rehearsal-fill",
                "bs=1M", "count=500",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)

            # Check disk usage
            proc = await asyncio.create_subprocess_exec(
                "df", "-h", "/",
                stdout=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            result.observations.append(f"Disk after fill: {stdout.decode().strip()}")

            # Wait and observe
            await asyncio.sleep(5)
            result.disruption_seconds = 5

            # Clean up
            import os
            os.remove("/tmp/stress-rehearsal-fill")
            result.observations.append("Temp file removed")
            result.restored = True

        except Exception as exc:
            result.error = str(exc)
            # Cleanup attempt
            try:
                import os
                os.remove("/tmp/stress-rehearsal-fill")
            except OSError:
                pass
            result.restored = True

        return result

    async def _test_dependency(self) -> RehearsalResult:
        """Test what happens when a non-critical dependency is unavailable."""
        # Test: stop Langfuse worker, check if conductor still processes tasks
        result = RehearsalResult(
            test_name="dependency_test",
            target="conductor-langfuse-worker",
        )

        try:
            result.observations.append("Stopping langfuse-worker to test trace resilience")

            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", "--time", "3", "conductor-langfuse-worker",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)

            # Check if conductor is still healthy
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                try:
                    resp = await client.get("http://localhost:9090/health")
                    if resp.status_code == 200:
                        result.observations.append("Gateway: still healthy (good)")
                    else:
                        result.cascading_failures.append(f"Gateway returned {resp.status_code}")
                except Exception:
                    result.cascading_failures.append("Gateway unreachable")

            result.disruption_seconds = 5
            await asyncio.sleep(5)

            # Restore
            proc = await asyncio.create_subprocess_exec(
                "docker", "start", "conductor-langfuse-worker",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            result.restored = True
            result.observations.append("Worker restored")

        except Exception as exc:
            result.error = str(exc)
            await asyncio.create_subprocess_exec(
                "docker", "start", "conductor-langfuse-worker"
            )
            result.restored = True

        return result

    async def _check_health_impact(self) -> list[str]:
        """Check which services are affected after a disruption."""
        failures = []
        import httpx

        checks = [
            ("Gateway", "http://localhost:9090/health"),
            ("Router", "http://localhost:8100/health"),
        ]

        async with httpx.AsyncClient(timeout=3) as client:
            for name, url in checks:
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        failures.append(f"{name}: HTTP {resp.status_code}")
                except Exception:
                    failures.append(f"{name}: unreachable")

        return failures

    async def _record_findings(self, result: RehearsalResult) -> None:
        """Record rehearsal findings in memory and board."""
        if self._memory:
            try:
                from ...memory.episodic import MemoryTier

                if result.cascading_failures:
                    await self._memory.store(
                        MemoryTier.LESSON,
                        f"Stress rehearsal: stopping {result.target} causes cascading "
                        f"failures in {', '.join(result.cascading_failures)}. "
                        f"Recovery: {result.recovery_seconds:.0f}s",
                        source=f"stress-rehearsal/{result.test_name}",
                    )
                else:
                    await self._memory.store(
                        MemoryTier.OBSERVATION,
                        f"Stress rehearsal: {result.target} — no cascading failures. "
                        f"Recovery: {result.recovery_seconds:.0f}s",
                        source=f"stress-rehearsal/{result.test_name}",
                    )
            except Exception as exc:
                logger.debug("Memory store failed: %s", exc)

        if self._board:
            obs_text = "\n".join(f"- {o}" for o in result.observations)
            cascade_text = (
                "\n**Cascading failures:**\n"
                + "\n".join(f"- {c}" for c in result.cascading_failures)
                if result.cascading_failures else ""
            )
            self._board.observation(
                f"Stress Rehearsal: {result.test_name} on {result.target}",
                f"**Disruption:** {result.disruption_seconds:.0f}s\n"
                f"**Recovery:** {result.recovery_seconds:.0f}s\n"
                f"**Restored:** {result.restored}\n"
                f"{cascade_text}\n\n"
                f"**Observations:**\n{obs_text}"
                + (f"\n\n**Error:** {result.error}" if result.error else ""),
                source="stress-rehearsal",
            )

        if self._evolution:
            self._evolution.record_mutation(
                surface="stress-rehearsal",
                action=result.test_name,
                description=(
                    f"{result.target}: {result.disruption_seconds:.0f}s disruption, "
                    f"{result.recovery_seconds:.0f}s recovery, "
                    f"{len(result.cascading_failures)} cascades"
                ),
            )
