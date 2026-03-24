"""
Skill Loader — SKILL.md parser with trust tiers.

Reads the standard SKILL.md format (YAML frontmatter + markdown
instructions), runs it through the scanner, assigns a trust tier, and
produces a sanitized SkillSpec ready for injection into the LLM context.

Trust Tiers:
  T0 — Built-in: Skills shipped with conductor (our code, full trust)
  T1 — Allowlisted: Manually reviewed community skills (full capabilities)
  T2 — Community: Scan-clean community skills (no secrets, no network, no shell)
  T3 — Untrusted: Failed scan or unreviewed (never loaded, dry-run only)

Skill loading precedence:
  1. <workspace>/skills (highest — local overrides)
  2. ~/.conductor/skills (user-level)
  3. orchestrator/skills/builtin/ (bundled T0)

A skill at a higher precedence level shadows one with the same name below it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

import yaml

from .scanner import ScanResult, SkillScanner

logger = logging.getLogger(__name__)


class TrustTier(IntEnum):
    """Trust levels for skills — lower number = more trusted."""
    BUILTIN = 0       # Our code, shipped with conductor
    ALLOWLISTED = 1   # Manually reviewed and approved
    COMMUNITY = 2     # Passed automated scan, no secrets/network/shell
    UNTRUSTED = 3     # Failed scan or unreviewed — never loaded


# Capability matrix per trust tier
TIER_CAPABILITIES: dict[TrustTier, dict] = {
    TrustTier.BUILTIN: {
        "inject_into_prompt": True,
        "sanitize_instructions": False,   # Trusted, inject as-is
        "secrets_access": True,
        "network_access": True,
        "shell_access": True,
        "file_access": "project_dir",     # Full project access
        "timeout_seconds": None,          # No timeout
        "requires_approval": False,
    },
    TrustTier.ALLOWLISTED: {
        "inject_into_prompt": True,
        "sanitize_instructions": False,   # Reviewed, inject as-is
        "secrets_access": True,           # Only declared secrets
        "network_access": True,           # Only declared hosts
        "shell_access": True,             # Only declared commands
        "file_access": "declared_paths",
        "timeout_seconds": 60,
        "requires_approval": False,
    },
    TrustTier.COMMUNITY: {
        "inject_into_prompt": True,
        "sanitize_instructions": True,    # Sanitize before injection
        "secrets_access": False,          # NO secrets
        "network_access": False,          # NO network
        "shell_access": False,            # NO shell
        "file_access": "temp_only",       # Temp directory only
        "timeout_seconds": 30,
        "requires_approval": False,
    },
    TrustTier.UNTRUSTED: {
        "inject_into_prompt": False,      # NEVER injected
        "sanitize_instructions": True,
        "secrets_access": False,
        "network_access": False,
        "shell_access": False,
        "file_access": None,              # NO file access
        "timeout_seconds": None,
        "requires_approval": True,        # Human must approve every use
    },
}


@dataclass
class SkillSpec:
    """Parsed and security-assessed skill ready for use."""

    # Identity
    name: str
    description: str
    version: str = ""
    homepage: str = ""

    # Skill metadata
    user_invocable: bool = True
    disable_model_invocation: bool = False
    command_dispatch: str | None = None
    command_tool: str | None = None

    # Requirements (from metadata.openclaw.requires)
    required_env: list[str] = field(default_factory=list)
    required_bins: list[str] = field(default_factory=list)
    required_any_bins: list[str] = field(default_factory=list)
    required_config: list[str] = field(default_factory=list)
    primary_env: str = ""
    supported_os: list[str] = field(default_factory=list)

    # Instructions (the actual skill content — markdown after frontmatter)
    raw_instructions: str = ""
    sanitized_instructions: str = ""

    # Security
    trust_tier: TrustTier = TrustTier.UNTRUSTED
    scan_result: ScanResult | None = None
    capabilities: dict = field(default_factory=dict)

    # Source
    source_path: str = ""
    source_type: str = ""  # "builtin", "workspace", "user", "clawhub"

    @property
    def is_loadable(self) -> bool:
        """Whether this skill can be loaded into the system."""
        return self.trust_tier <= TrustTier.COMMUNITY

    @property
    def effective_instructions(self) -> str:
        """The instructions that should be injected into the LLM context."""
        caps = TIER_CAPABILITIES.get(self.trust_tier, {})
        if not caps.get("inject_into_prompt"):
            return ""
        if caps.get("sanitize_instructions"):
            return self.sanitized_instructions
        return self.raw_instructions


class SkillLoader:
    """Loads, scans, and classifies community skills."""

    def __init__(
        self,
        scanner: SkillScanner | None = None,
        allowlist_path: str | Path | None = None,
        builtin_dir: str | Path | None = None,
        workspace_skills_dir: str | Path | None = None,
        user_skills_dir: str | Path | None = None,
    ) -> None:
        self._scanner = scanner or SkillScanner()
        self._allowlist = self._load_allowlist(allowlist_path)
        self._builtin_dir = Path(builtin_dir) if builtin_dir else None
        self._workspace_dir = Path(workspace_skills_dir) if workspace_skills_dir else None
        self._user_dir = Path(user_skills_dir) if user_skills_dir else Path.home() / ".conductor" / "skills"
        self._skills: dict[str, SkillSpec] = {}

    def load_all(self) -> dict[str, SkillSpec]:
        """Load skills from all sources with precedence rules.

        Precedence (highest first):
        1. Workspace skills
        2. User skills (~/.conductor/skills)
        3. Built-in skills
        """
        self._skills.clear()

        # Load in reverse precedence order (lowest first, higher overrides)
        if self._builtin_dir and self._builtin_dir.exists():
            self._load_from_dir(self._builtin_dir, source_type="builtin")

        if self._user_dir and self._user_dir.exists():
            self._load_from_dir(self._user_dir, source_type="user")

        if self._workspace_dir and self._workspace_dir.exists():
            self._load_from_dir(self._workspace_dir, source_type="workspace")

        loaded = sum(1 for s in self._skills.values() if s.is_loadable)
        blocked = sum(1 for s in self._skills.values() if not s.is_loadable)
        logger.info(
            "Skills loaded: %d loadable, %d blocked (%d total)",
            loaded, blocked, len(self._skills),
        )
        return dict(self._skills)

    def load_from_text(
        self, name: str, content: str, source_type: str = "clawhub"
    ) -> SkillSpec:
        """Load a single skill from raw SKILL.md text (e.g. from ClawHub API)."""
        spec = self._parse_skill_md(content, name, f"<{source_type}:{name}>")
        spec.source_type = source_type

        # Scan
        scan_result = self._scanner.scan_text(content, name)
        spec.scan_result = scan_result

        # Classify trust tier
        spec.trust_tier = self._classify_tier(spec, scan_result, source_type)
        spec.capabilities = dict(TIER_CAPABILITIES.get(spec.trust_tier, {}))

        # Sanitize if needed
        if spec.capabilities.get("sanitize_instructions"):
            spec.sanitized_instructions = _sanitize_instructions(
                spec.raw_instructions
            )
        else:
            spec.sanitized_instructions = spec.raw_instructions

        self._skills[name] = spec
        return spec

    def get(self, name: str) -> SkillSpec | None:
        return self._skills.get(name)

    def list_loadable(self) -> list[SkillSpec]:
        return [s for s in self._skills.values() if s.is_loadable]

    def list_blocked(self) -> list[SkillSpec]:
        return [s for s in self._skills.values() if not s.is_loadable]

    def _load_from_dir(self, directory: Path, source_type: str) -> None:
        """Load all SKILL.md files from a directory."""
        for skill_md in sorted(directory.rglob("SKILL.md")):
            try:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
                name_from_dir = skill_md.parent.name
                spec = self._parse_skill_md(content, name_from_dir, str(skill_md))
                spec.source_type = source_type

                # Scan (skip for built-in — we trust our own code)
                if source_type == "builtin":
                    spec.trust_tier = TrustTier.BUILTIN
                    spec.scan_result = None
                else:
                    scan_result = self._scanner.scan_file(skill_md)
                    spec.scan_result = scan_result
                    spec.trust_tier = self._classify_tier(
                        spec, scan_result, source_type
                    )

                spec.capabilities = dict(
                    TIER_CAPABILITIES.get(spec.trust_tier, {})
                )

                # Sanitize if needed
                if spec.capabilities.get("sanitize_instructions"):
                    spec.sanitized_instructions = _sanitize_instructions(
                        spec.raw_instructions
                    )
                else:
                    spec.sanitized_instructions = spec.raw_instructions

                # Precedence: later loads override earlier ones
                self._skills[spec.name] = spec

            except Exception as exc:
                logger.warning("Failed to load skill from %s: %s", skill_md, exc)

    def _classify_tier(
        self, spec: SkillSpec, scan: ScanResult, source_type: str
    ) -> TrustTier:
        """Assign trust tier based on scan results and allowlist."""
        # Built-in skills are always T0
        if source_type == "builtin":
            return TrustTier.BUILTIN

        # Check allowlist (manually reviewed skills)
        if spec.name in self._allowlist:
            # Even allowlisted skills fail if they have critical findings
            if scan and scan.critical_count > 0:
                logger.warning(
                    "Allowlisted skill '%s' has %d CRITICAL findings — "
                    "downgrading to UNTRUSTED",
                    spec.name, scan.critical_count,
                )
                return TrustTier.UNTRUSTED
            return TrustTier.ALLOWLISTED

        # Scan results determine tier
        if scan is None:
            return TrustTier.UNTRUSTED

        if scan.critical_count > 0:
            return TrustTier.UNTRUSTED

        if scan.high_count > 0:
            # High findings need review — quarantine as untrusted
            return TrustTier.UNTRUSTED

        # Clean scan → community tier
        return TrustTier.COMMUNITY

    def _parse_skill_md(
        self, content: str, fallback_name: str, source_path: str
    ) -> SkillSpec:
        """Parse a SKILL.md file into a SkillSpec."""
        frontmatter, instructions = _split_frontmatter(content)

        # Parse YAML frontmatter
        meta: dict = {}
        if frontmatter:
            try:
                meta = yaml.safe_load(frontmatter) or {}
            except yaml.YAMLError as exc:
                logger.debug("YAML parse error in %s: %s", source_path, exc)

        # Extract skill metadata
        oc_raw = meta.get("metadata", {})
        if isinstance(oc_raw, str):
            try:
                oc_raw = json.loads(oc_raw)
            except json.JSONDecodeError:
                oc_raw = {}
        oc_dict: dict = oc_raw if isinstance(oc_raw, dict) else {}
        openclaw: dict = oc_dict.get("openclaw", {})
        requires: dict = openclaw.get("requires", {})

        return SkillSpec(
            name=meta.get("name", fallback_name),
            description=meta.get("description", ""),
            version=meta.get("version", ""),
            homepage=meta.get("homepage", openclaw.get("homepage", "")),
            user_invocable=meta.get("user-invocable", True),
            disable_model_invocation=meta.get("disable-model-invocation", False),
            command_dispatch=meta.get("command-dispatch"),
            command_tool=meta.get("command-tool"),
            required_env=requires.get("env", []),
            required_bins=requires.get("bins", []),
            required_any_bins=requires.get("anyBins", []),
            required_config=requires.get("config", []),
            primary_env=openclaw.get("primaryEnv", ""),
            supported_os=openclaw.get("os", []),
            raw_instructions=instructions,
            source_path=source_path,
        )

    def _load_allowlist(self, path: str | Path | None) -> set[str]:
        """Load the skill allowlist (one skill name per line)."""
        if not path:
            return set()
        p = Path(path)
        if not p.exists():
            return set()
        try:
            names = set()
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    names.add(line)
            return names
        except Exception as exc:
            logger.warning("Failed to load allowlist: %s", exc)
            return set()


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body."""
    content = content.strip()
    if not content.startswith("---"):
        return "", content

    # Find the closing ---
    end = content.find("---", 3)
    if end == -1:
        return "", content

    frontmatter = content[3:end].strip()
    body = content[end + 3:].strip()
    return frontmatter, body


# Patterns to strip from skill instructions (sanitization)
_SANITIZE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Strip instruction overrides
    (re.compile(r"(?:^|\n).*?ignore\s+(all\s+)?previous\s+instructions.*?(?:\n|$)", re.IGNORECASE), "\n"),
    (re.compile(r"(?:^|\n).*?disregard\s+(all\s+)?prior.*?(?:\n|$)", re.IGNORECASE), "\n"),
    (re.compile(r"(?:^|\n).*?you\s+are\s+now\s+.*?(?:\n|$)", re.IGNORECASE), "\n"),
    # Strip secrecy instructions
    (re.compile(r"(?:^|\n).*?(?:don'?t|never)\s+(?:tell|reveal|show)\s+(?:the\s+)?user.*?(?:\n|$)", re.IGNORECASE), "\n"),
    # Strip token delimiters
    (re.compile(r"<\|.*?\|>", re.IGNORECASE), ""),
    (re.compile(r"\[\[.*?SYSTEM.*?\]\]", re.IGNORECASE), ""),
    # Strip shell execution
    (re.compile(r"(?:^|\n).*?(?:subprocess|os\.system|exec|eval)\s*\(.*?(?:\n|$)", re.IGNORECASE), "\n"),
    # Strip credential access patterns
    (re.compile(r"(?:^|\n).*?~/?\.\w+/(?:credentials|\.env|secrets?).*?(?:\n|$)", re.IGNORECASE), "\n"),
    # Strip base64 payload lines
    (re.compile(r"(?:^|\n).*?base64\s*(?:encode|decode).*?(?:\n|$)", re.IGNORECASE), "\n"),
    # Strip raw IP URLs
    (re.compile(r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:/][^\s]*", re.IGNORECASE), "[URL_STRIPPED]"),
]


def _sanitize_instructions(text: str) -> str:
    """Strip known injection patterns from skill instructions.

    This is the last line of defense — even if the scanner missed something,
    sanitization strips it before it reaches the LLM context.
    """
    result = text
    for pattern, replacement in _SANITIZE_PATTERNS:
        result = pattern.sub(replacement, result)

    # Collapse excessive blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()
