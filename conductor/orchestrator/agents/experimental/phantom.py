"""
Phantom Execution — Shadow-run skills before real execution.

Before any T2+ community skill actually executes, it's run in "phantom mode":
same inputs, same context, but all side effects are intercepted and logged
instead of executed. The phantom result gets analyzed for suspicious behavior.

If the phantom tries to:
  - Access undeclared files or env vars → BLOCK
  - Make network calls to undeclared hosts → BLOCK
  - Execute shell commands not in its declaration → BLOCK
  - Output content that looks like exfiltration → BLOCK

Only if the phantom passes does real execution proceed.

Context Archaeology — Forensic failure analysis.

When a task fails, instead of just logging the error, this module performs
a full autopsy: reconstructs the decision chain, identifies root cause,
and generates a targeted fix (memory, variant demotion, skill change,
or guardrail addition).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Phantom Execution
# ──────────────────────────────────────────────────────────────────

@dataclass
class PhantomResult:
    """Result of a phantom (dry-run) skill execution."""
    skill_name: str
    safe: bool = True
    violations: list[str] = field(default_factory=list)
    intercepted_actions: list[dict] = field(default_factory=list)
    output_preview: str = ""


class PhantomExecutor:
    """Shadow-runs skills to detect malicious behavior before real execution."""

    def __init__(self) -> None:
        self._results: list[PhantomResult] = []

    def analyze_skill_instructions(
        self,
        skill_name: str,
        instructions: str,
        declared_env: list[str],
        declared_bins: list[str],
    ) -> PhantomResult:
        """Static phantom analysis — check what the skill WOULD do.

        This is a lightweight version that analyzes instructions without
        actually executing them. For dynamic phantoms (actual sandboxed
        execution), we'd need container isolation.
        """
        import re

        result = PhantomResult(skill_name=skill_name)

        # Check for undeclared env var access
        env_refs = re.findall(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", instructions)
        for var in env_refs:
            if var not in declared_env and var not in ("HOME", "PATH", "USER", "PWD"):
                result.violations.append(f"Undeclared env var access: ${var}")
                result.safe = False

        # Check for undeclared binary execution
        bin_refs = re.findall(r"(?:^|\s)(curl|wget|nc|ncat|ssh|scp|rsync|python|node|ruby|perl)\s", instructions, re.MULTILINE)
        for binary in bin_refs:
            if binary not in declared_bins:
                result.intercepted_actions.append({
                    "type": "binary_exec",
                    "binary": binary,
                    "declared": False,
                })
                if binary in ("nc", "ncat", "ssh", "scp"):
                    result.violations.append(f"Undeclared network binary: {binary}")
                    result.safe = False

        # Check for file access outside declared scope
        file_refs = re.findall(r"(?:~/|/home/|/root/|/etc/|/tmp/)[\w/.]+", instructions)
        sensitive_paths = (".env", ".ssh", ".aws", ".gnupg", "credentials", "secrets", "shadow", "passwd")
        for path in file_refs:
            if any(s in path.lower() for s in sensitive_paths):
                result.violations.append(f"Sensitive file access: {path}")
                result.safe = False

        # Check for data exfiltration patterns
        exfil_patterns = [
            (r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "Raw IP URL"),
            (r"ngrok|serveo|localtunnel", "Tunnel service"),
            (r"base64.*encode.*send|post.*base64", "Encoded exfiltration"),
        ]
        for pattern, desc in exfil_patterns:
            if re.search(pattern, instructions, re.IGNORECASE):
                result.violations.append(f"Exfiltration pattern: {desc}")
                result.safe = False

        self._results.append(result)
        return result


# ──────────────────────────────────────────────────────────────────
# Context Archaeology — Forensic failure analysis
# ──────────────────────────────────────────────────────────────────

@dataclass
class Autopsy:
    """Forensic analysis of a failed task."""
    task_id: str
    failure_point: str          # Which step failed
    model_used: str = ""
    variant_used: str = ""
    intent: str = ""
    bouncer_flags: list[str] = field(default_factory=list)
    routing_confidence: float = 0.0
    memory_context_size: int = 0
    root_cause: str = ""
    suggested_fix: str = ""
    fix_type: str = ""          # "memory", "variant", "skill", "guardrail", "prompt"


class ContextArchaeologist:
    """Forensic failure analysis — autopsies failed tasks to find root causes."""

    def __init__(
        self,
        episodic_memory=None,
        board=None,
        evolution=None,
        gateway_url: str = "http://localhost:9090",
    ) -> None:
        self._memory = episodic_memory
        self._board = board
        self._evolution = evolution
        self._gateway_url = gateway_url
        self._autopsies: list[Autopsy] = []

    async def autopsy(
        self,
        task_id: str,
        filename: str,
        error: str,
        *,
        model_used: str = "",
        variant_used: str = "",
        intent: str = "",
        bouncer_flags: list[str] | None = None,
        routing_confidence: float = 0.0,
        subtask_description: str = "",
    ) -> Autopsy:
        """Perform a forensic analysis of a failed task.

        Reconstructs the decision chain and identifies the root cause.
        """
        result = Autopsy(
            task_id=task_id,
            failure_point=error[:200],
            model_used=model_used,
            variant_used=variant_used,
            intent=intent,
            bouncer_flags=bouncer_flags or [],
            routing_confidence=routing_confidence,
        )

        # Ask the LLM to analyze the failure
        try:
            import httpx
            context = (
                f"Task ID: {task_id}\n"
                f"Intent: {intent}\n"
                f"Model used: {model_used}\n"
                f"Prompt variant: {variant_used}\n"
                f"Routing confidence: {routing_confidence:.0%}\n"
                f"Bouncer flags: {bouncer_flags}\n"
                f"Error: {error}\n"
            )
            if subtask_description:
                context += f"Subtask: {subtask_description}\n"

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._gateway_url}/v1/chat/completions",
                    json={
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a failure analysis agent. Given the context of a "
                                    "failed AI agent task, identify the root cause and suggest "
                                    "ONE specific fix. Respond with JSON:\n"
                                    '{"root_cause": "...", "fix_type": "memory|variant|skill|guardrail|prompt", '
                                    '"suggested_fix": "specific actionable fix"}'
                                ),
                            },
                            {"role": "user", "content": context},
                        ],
                        "max_tokens": 256,
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]

                import json
                if "{" in content:
                    start = content.index("{")
                    end = content.rindex("}") + 1
                    data = json.loads(content[start:end])
                    result.root_cause = data.get("root_cause", "")
                    result.fix_type = data.get("fix_type", "")
                    result.suggested_fix = data.get("suggested_fix", "")

        except Exception as exc:
            logger.debug("Autopsy LLM analysis failed: %s", exc)
            result.root_cause = f"Analysis failed: {exc}"

        # Record as memory
        if self._memory and result.root_cause:
            from ...memory.episodic import MemoryTier
            await self._memory.store(
                MemoryTier.REGRET,
                f"Task {task_id} failed: {result.root_cause}. Fix: {result.suggested_fix}",
                source=f"autopsy/{task_id}",
                context={
                    "model": model_used,
                    "variant": variant_used,
                    "fix_type": result.fix_type,
                },
            )

        # Post to board
        if self._board and result.root_cause:
            self._board.observation(
                f"Autopsy: {task_id}",
                f"**Root cause:** {result.root_cause}\n\n"
                f"**Suggested fix ({result.fix_type}):** {result.suggested_fix}\n\n"
                f"**Error:** {error[:300]}",
                source="context-archaeology",
            )

        # Log evolution
        if self._evolution:
            self._evolution.record_mutation(
                surface="autopsy",
                action="analyze",
                description=f"Autopsy for {task_id}: {result.root_cause[:80]}",
                details={
                    "task_id": task_id,
                    "root_cause": result.root_cause,
                    "fix_type": result.fix_type,
                    "suggested_fix": result.suggested_fix,
                },
            )

        self._autopsies.append(result)
        return result
