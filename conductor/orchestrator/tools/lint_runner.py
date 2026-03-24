"""
Lint Runner Tool — Execute lint/static checks and parse basic results.

Supports common lint workflows by convention:
  - Node: npm run lint --if-present
  - Python: python -m ruff check .
  - Make: make lint

Phase 0: Auto-detect from project files, run, parse exit code + output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .shell import Shell

logger = logging.getLogger(__name__)


@dataclass
class LintResult:
    success: bool
    framework: str
    output: str
    issues_found: int
    warnings_found: int = 0


class LintRunner:
    def __init__(self, project_dir: str, timeout: int = 120) -> None:
        self._project_dir = project_dir
        self._shell = Shell(project_dir, timeout=timeout)

    async def run(self, command: str | None = None) -> LintResult:
        """Run lint/static checks. Auto-detect framework if no command given."""
        if command:
            return await self._run_command(command, "custom")

        framework, cmd = self._detect_framework()
        if not cmd:
            return LintResult(
                success=True,
                framework="none",
                output="No lint framework detected",
                issues_found=0,
                warnings_found=0,
            )
        return await self._run_command(cmd, framework)

    async def _run_command(self, command: str, framework: str) -> LintResult:
        logger.info("Running lint: %s (%s)", command, framework)
        result = await self._shell.run(command)
        output = result.stdout + ("\n" + result.stderr if result.stderr else "")
        issues = self._parse_issue_count(output, framework, result.success)
        return LintResult(
            success=result.success,
            framework=framework,
            output=output,
            issues_found=issues,
            warnings_found=0,
        )

    def _detect_framework(self) -> tuple[str, str]:
        root = Path(self._project_dir)

        package_json = root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                if isinstance(scripts, dict) and "lint" in scripts:
                    return "node", "npm run lint --if-present"
            except Exception:
                logger.debug("Failed to inspect package.json for lint script", exc_info=True)

        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
            if "ruff" in text:
                return "ruff", "python -m ruff check ."

        if (root / "Makefile").exists():
            return "make", "make lint"

        return "", ""

    @staticmethod
    def _parse_issue_count(output: str, framework: str, success: bool) -> int:
        if success:
            return 0

        lines = [line for line in output.splitlines() if line.strip()]
        if framework == "ruff":
            return len(lines)
        return max(1, len(lines))
