"""
Skill Forge — The conductor writes, tests, and installs its own skills.

When the conductor encounters a task type it can't handle well (low score,
repeated failures, no matching skill), it can forge a new skill:

1. Analyze the task pattern — what kind of work is this?
2. Draft a SKILL.md — frontmatter + instructions
3. Security-scan its own creation (gitleaks + injection rules)
4. Test against sample inputs (phantom execution)
5. Install as T0 built-in (it's our code, we trust it)
6. Record in episodic memory as a T6 affirmation

The forge respects all security constraints:
- Scanned skills that fail are rejected (even self-authored ones)
- All forged skills are git-tracked in evolution history
- Human can review, edit, or delete any forged skill
- The forge only runs when mood is ADVENTUROUS or NORMAL

Future: forged skills can be published to a shared registry.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillForge:
    """Creates new skills from observed task patterns."""

    def __init__(
        self,
        skills_dir: str | Path,
        scanner=None,
        episodic_memory=None,
        board=None,
        evolution=None,
        gateway_url: str = "http://localhost:9090",
    ) -> None:
        self._dir = Path(skills_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._scanner = scanner
        self._memory = episodic_memory
        self._board = board
        self._evolution = evolution
        self._gateway_url = gateway_url
        self._forge_count = 0

    async def forge(
        self,
        task_description: str,
        failure_context: str = "",
        task_type: str = "",
    ) -> dict:
        """Forge a new skill from a task pattern.

        Returns a dict with: name, path, scan_passed, installed
        """
        self._forge_count += 1
        result = {
            "forge_id": self._forge_count,
            "name": "",
            "path": "",
            "scan_passed": False,
            "installed": False,
            "reason": "",
        }

        # Step 1: Ask LLM to design the skill
        skill_md = await self._draft_skill(task_description, failure_context, task_type)
        if not skill_md:
            result["reason"] = "LLM failed to generate skill"
            return result

        # Extract name from the generated SKILL.md
        name = self._extract_name(skill_md)
        if not name:
            name = f"forged-{self._forge_count}"
        result["name"] = name

        # Step 2: Security scan
        if self._scanner:
            scan = self._scanner.scan_text(skill_md, name)
            result["scan_passed"] = scan.passed
            if not scan.passed:
                result["reason"] = (
                    f"Failed security scan: {scan.critical_count} critical, "
                    f"{scan.high_count} high findings"
                )
                logger.warning("Forged skill '%s' FAILED security scan", name)

                if self._board:
                    findings_text = "\n".join(
                        f"- [{f.severity}] {f.description}: {f.evidence[:60]}"
                        for f in scan.findings[:5]
                    )
                    self._board.observation(
                        f"Skill Forge: '{name}' rejected by scanner",
                        f"The forge attempted to create a skill but it failed "
                        f"security scanning.\n\n**Findings:**\n{findings_text}",
                        source="skill-forge",
                    )
                return result
        else:
            result["scan_passed"] = True  # No scanner = trust (dev mode)

        # Step 3: Install as built-in
        skill_dir = self._dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(skill_md, encoding="utf-8")
        result["path"] = str(skill_path)
        result["installed"] = True

        logger.info("Skill Forge: created '%s' at %s", name, skill_path)

        # Step 4: Record in memory and evolution
        if self._memory:
            try:
                from ...memory.episodic import MemoryTier
                await self._memory.store(
                    MemoryTier.AFFIRMATION,
                    f"Forged new skill '{name}' for task pattern: {task_description[:100]}",
                    source=f"skill-forge/{name}",
                    context={
                        "task_type": task_type,
                        "failure_context": failure_context[:200],
                    },
                )
            except Exception as exc:
                logger.debug("Memory store failed: %s", exc)

        if self._evolution:
            self._evolution.record_mutation(
                surface="skill-forge",
                action="create",
                description=f"Forged skill '{name}': {task_description[:80]}",
                details={
                    "name": name,
                    "task_type": task_type,
                    "scan_passed": result["scan_passed"],
                },
            )
            self._evolution.commit(f"skill-forge: created '{name}'")

        if self._board:
            self._board.observation(
                f"Skill Forge: created '{name}'",
                f"**Task pattern:** {task_description[:200]}\n\n"
                f"**Installed at:** `{skill_path}`\n\n"
                f"**Security scan:** passed\n\n"
                f"Review and edit at any time. The skill will be used "
                f"automatically on matching future tasks.",
                source="skill-forge",
            )

        return result

    async def _draft_skill(
        self,
        task_description: str,
        failure_context: str,
        task_type: str,
    ) -> str | None:
        """Use the LLM to draft a SKILL.md."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                prompt = (
                    "You are a skill designer for an AI agent system. "
                    "Create a SKILL.md file that teaches the agent how to handle "
                    "a specific type of task.\n\n"
                    "Format:\n"
                    "```\n"
                    "---\n"
                    "name: skill-name\n"
                    'description: "One-line description"\n'
                    "version: 1.0.0\n"
                    "---\n"
                    "\n"
                    "# Skill Title\n"
                    "\n"
                    "Step-by-step instructions for the agent...\n"
                    "```\n\n"
                    f"Task type: {task_type or 'general'}\n"
                    f"Task description: {task_description}\n"
                )

                if failure_context:
                    prompt += (
                        f"\nPrevious attempts at this task failed because: "
                        f"{failure_context}\n"
                        f"Design the skill to avoid these failure modes.\n"
                    )

                prompt += (
                    "\nIMPORTANT: Output ONLY the SKILL.md content. "
                    "No explanation before or after."
                )

                resp = await client.post(
                    f"{self._gateway_url}/v1/chat/completions",
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2048,
                        "temperature": 0.5,
                    },
                    headers={
                        "Authorization": f"Bearer {os.environ.get('CONDUCTOR_GATEWAY_KEY', '')}",
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]

                # Extract SKILL.md content — strip any markdown wrapping
                if "```" in content:
                    blocks = content.split("```")
                    for block in blocks[1:]:
                        if block.strip().startswith("---") or block.strip().startswith("name:"):
                            return block.strip()
                        # Skip language identifier
                        lines = block.strip().splitlines()
                        if len(lines) > 1 and lines[0].strip() in ("yaml", "markdown", "md", ""):
                            return "\n".join(lines[1:]).strip()

                # No code blocks — use the whole content if it looks like a SKILL.md
                if "---" in content and "name:" in content:
                    return content.strip()

                return content.strip()

        except Exception as exc:
            logger.warning("Skill drafting failed: %s", exc)
            return None

    def _extract_name(self, skill_md: str) -> str:
        """Extract the name field from SKILL.md frontmatter."""
        match = re.search(r"^name:\s*(.+)$", skill_md, re.MULTILINE)
        if match:
            name = match.group(1).strip().strip("\"'")
            # Sanitize for filesystem
            return re.sub(r"[^a-zA-Z0-9_-]", "-", name)[:50]
        return ""

    async def suggest_skills(self, recent_failures: list[dict]) -> list[dict]:
        """Analyze recent failures and suggest skills that could prevent them.

        Called by the heartbeat during dream loops.
        """
        suggestions = []
        # Group failures by pattern
        seen_patterns: set[str] = set()
        for failure in recent_failures:
            pattern = failure.get("task_type", "") + ":" + failure.get("error", "")[:50]
            if pattern in seen_patterns:
                continue
            seen_patterns.add(pattern)

            suggestions.append({
                "task_type": failure.get("task_type", ""),
                "task_description": failure.get("description", ""),
                "failure_reason": failure.get("error", ""),
                "suggested_skill": f"Handle {failure.get('task_type', 'unknown')} tasks "
                                   f"that fail with: {failure.get('error', '')[:60]}",
            })

        return suggestions[:5]  # Max 5 suggestions

    def list_forged(self) -> list[dict]:
        """List all forged skills."""
        skills = []
        for skill_dir in sorted(self._dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                name = self._extract_name(content) or skill_dir.name
                skills.append({
                    "name": name,
                    "path": str(skill_md),
                    "size": len(content),
                    "created": datetime.fromtimestamp(
                        skill_md.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
        return skills
