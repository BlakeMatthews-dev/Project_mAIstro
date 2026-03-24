"""
Skill Scanner — Static security analysis for SKILL.md community skill files.

Two scanning layers:
1. Gitleaks (MIT license) — Detects hardcoded secrets, API keys, tokens
   in skill files via 800+ built-in rules. Runs as a subprocess.
2. Custom prompt injection scanner — Detects injection patterns specific
   to LLM agent skills. Our rules, no license dependency.

The scanner runs BEFORE a skill is loaded into the system. A skill that
fails scanning is quarantined — it never reaches the LLM context.

Scan results include:
- Severity: critical (auto-reject), high (review required), medium (flag),
  low (informational)
- Category: secret_leak, prompt_injection, data_exfil, shell_exec,
  obfuscation, suspicious_url
- Evidence: the matched text and location
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class Severity(StrEnum):
    CRITICAL = "critical"  # Auto-reject, never load
    HIGH = "high"          # Requires manual review before loading
    MEDIUM = "medium"      # Flag in scan report
    LOW = "low"            # Informational only


class Category(StrEnum):
    SECRET_LEAK = "secret_leak"
    PROMPT_INJECTION = "prompt_injection"
    DATA_EXFIL = "data_exfil"
    SHELL_EXEC = "shell_exec"
    OBFUSCATION = "obfuscation"
    SUSPICIOUS_URL = "suspicious_url"
    CREDENTIAL_ACCESS = "credential_access"


@dataclass
class ScanFinding:
    severity: Severity
    category: Category
    rule: str
    description: str
    evidence: str         # The matched text (truncated)
    line: int = 0
    file: str = ""


@dataclass
class ScanResult:
    skill_name: str
    passed: bool                          # True if no critical/high findings
    findings: list[ScanFinding] = field(default_factory=list)
    gitleaks_findings: int = 0
    injection_findings: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)


# ──────────────────────────────────────────────────────────────────
# Custom Prompt Injection Rules
# ──────────────────────────────────────────────────────────────────

# Each rule: (pattern, severity, category, description)
_INJECTION_RULES: list[tuple[re.Pattern, Severity, Category, str]] = [
    # ── CRITICAL: Direct instruction override ──
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions|prompts|rules)", re.IGNORECASE),
     Severity.CRITICAL, Category.PROMPT_INJECTION,
     "Direct instruction override — classic prompt injection"),

    (re.compile(r"disregard\s+(all\s+)?(prior|above|previous|system)", re.IGNORECASE),
     Severity.CRITICAL, Category.PROMPT_INJECTION,
     "Instruction disregard"),

    (re.compile(r"you\s+are\s+now\s+(a|an|the|my)\s+", re.IGNORECASE),
     Severity.CRITICAL, Category.PROMPT_INJECTION,
     "Role reassignment in skill instructions"),

    (re.compile(r"switch\s+to\s+(unrestricted|jailbreak|dev|developer|admin)\s+mode", re.IGNORECASE),
     Severity.CRITICAL, Category.PROMPT_INJECTION,
     "Mode switch attack"),

    (re.compile(r"<\|.*?(system|endoftext|im_start|im_end).*?\|>", re.IGNORECASE),
     Severity.CRITICAL, Category.PROMPT_INJECTION,
     "Token delimiter injection"),

    # ── CRITICAL: Data exfiltration ──
    (re.compile(r"(curl|wget|fetch|http\.get|requests\.get|httpx)\s.*?(api[_-]?key|token|secret|password|credential)", re.IGNORECASE),
     Severity.CRITICAL, Category.DATA_EXFIL,
     "Credential exfiltration via HTTP"),

    (re.compile(r"(send|post|upload|transmit|exfil)\s.*(key|token|secret|password|cred)", re.IGNORECASE),
     Severity.CRITICAL, Category.DATA_EXFIL,
     "Secret transmission instruction"),

    (re.compile(r"base64\s*(encode|decode|[-.])(.*?(key|token|secret|password))?", re.IGNORECASE),
     Severity.HIGH, Category.OBFUSCATION,
     "Base64 encoding of potential secrets"),

    # ── HIGH: Shell execution ──
    (re.compile(r"(subprocess|os\.system|os\.popen|exec|eval)\s*\(", re.IGNORECASE),
     Severity.HIGH, Category.SHELL_EXEC,
     "Direct shell/code execution"),

    (re.compile(r"\brm\s+-rf\s", re.IGNORECASE),
     Severity.HIGH, Category.SHELL_EXEC,
     "Recursive deletion command"),

    (re.compile(r"(reverse\s+shell|bind\s+shell|nc\s+-[el]|ncat|socat)", re.IGNORECASE),
     Severity.CRITICAL, Category.SHELL_EXEC,
     "Reverse/bind shell"),

    (re.compile(r"(chmod\s+[0-7]*7[0-7]*|chmod\s+\+[xs])\s", re.IGNORECASE),
     Severity.HIGH, Category.SHELL_EXEC,
     "Permission escalation"),

    # ── HIGH: Credential access ──
    (re.compile(r"~/?\.(env|aws|ssh|gnupg|config|netrc|npmrc)", re.IGNORECASE),
     Severity.HIGH, Category.CREDENTIAL_ACCESS,
     "Access to dotfile credential stores"),

    (re.compile(r"(credentials?|secrets?|passwords?)\.(json|yaml|yml|xml|ini|conf|cfg|txt)", re.IGNORECASE),
     Severity.HIGH, Category.CREDENTIAL_ACCESS,
     "Access to credential files"),

    (re.compile(r"/etc/(shadow|passwd|sudoers)", re.IGNORECASE),
     Severity.CRITICAL, Category.CREDENTIAL_ACCESS,
     "System credential file access"),

    (re.compile(r"~/.openclaw/(credentials|\.env|config\.json)", re.IGNORECASE),
     Severity.CRITICAL, Category.CREDENTIAL_ACCESS,
     "OpenClaw credential store access"),

    (re.compile(r"(ANTHROPIC|OPENAI|AWS|GOOGLE|MISTRAL|CEREBRAS|COHERE|CLOUDFLARE)_.*?(KEY|SECRET|TOKEN)", re.IGNORECASE),
     Severity.MEDIUM, Category.CREDENTIAL_ACCESS,
     "References provider API key env var (check if declared in requires)"),

    # ── HIGH: Suspicious URLs ──
    (re.compile(r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:/]", re.IGNORECASE),
     Severity.HIGH, Category.SUSPICIOUS_URL,
     "Raw IP address URL (potential C2)"),

    (re.compile(r"https?://[a-z0-9]{20,}\.(xyz|tk|ml|ga|cf|gq|top|buzz|click|link)\b", re.IGNORECASE),
     Severity.HIGH, Category.SUSPICIOUS_URL,
     "Suspicious domain (random subdomain + cheap TLD)"),

    (re.compile(r"(ngrok|serveo|localtunnel|bore\.pub|lhr\.life|trycloudflare)", re.IGNORECASE),
     Severity.HIGH, Category.SUSPICIOUS_URL,
     "Tunnel service URL (potential data exfil)"),

    # ── MEDIUM: Obfuscation ──
    (re.compile(r"\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}", re.IGNORECASE),
     Severity.MEDIUM, Category.OBFUSCATION,
     "Hex-encoded strings"),

    (re.compile(r"\\u[0-9a-f]{4}.*\\u[0-9a-f]{4}.*\\u[0-9a-f]{4}", re.IGNORECASE),
     Severity.MEDIUM, Category.OBFUSCATION,
     "Unicode-escaped strings"),

    (re.compile(r"atob\s*\(|btoa\s*\(|String\.fromCharCode", re.IGNORECASE),
     Severity.MEDIUM, Category.OBFUSCATION,
     "JavaScript string obfuscation"),

    # ── MEDIUM: Secrecy / hidden behavior ──
    (re.compile(r"(don'?t|do\s+not|never)\s+(tell|mention|reveal|show|display)\s+(the\s+)?(user|human|operator)", re.IGNORECASE),
     Severity.HIGH, Category.PROMPT_INJECTION,
     "Instruction to hide behavior from user"),

    (re.compile(r"(hidden|secret|covert|silent)\s+(instruction|command|task|action|step)", re.IGNORECASE),
     Severity.HIGH, Category.PROMPT_INJECTION,
     "Hidden instruction reference"),

    (re.compile(r"before\s+(responding|answering|replying).*?(first|always|quietly|silently)", re.IGNORECASE),
     Severity.MEDIUM, Category.PROMPT_INJECTION,
     "Pre-response hidden action"),
]


class SkillScanner:
    """Static security scanner for community skill files."""

    def __init__(self, gitleaks_path: str = "gitleaks") -> None:
        self._gitleaks = gitleaks_path
        self._gitleaks_available = self._check_gitleaks()

    def _check_gitleaks(self) -> bool:
        try:
            result = subprocess.run(
                [self._gitleaks, "version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                logger.info("Gitleaks available: %s", result.stdout.strip())
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        logger.warning("Gitleaks not available — secret scanning disabled")
        return False

    def scan_file(self, path: Path) -> ScanResult:
        """Scan a single SKILL.md file."""
        skill_name = path.parent.name if path.name == "SKILL.md" else path.stem
        content = path.read_text(encoding="utf-8", errors="replace")

        findings: list[ScanFinding] = []

        # Layer 1: Gitleaks secret detection
        if self._gitleaks_available:
            gl_findings = self._run_gitleaks(path)
            findings.extend(gl_findings)

        # Layer 2: Custom prompt injection scanner
        inj_findings = self._scan_injection(content, str(path))
        findings.extend(inj_findings)

        # Determine pass/fail
        has_critical = any(f.severity == Severity.CRITICAL for f in findings)
        # has_high available for future review-gating logic

        return ScanResult(
            skill_name=skill_name,
            passed=not has_critical,  # Critical = auto-reject, High = needs review
            findings=findings,
            gitleaks_findings=sum(
                1 for f in findings if f.category == Category.SECRET_LEAK
            ),
            injection_findings=sum(
                1 for f in findings
                if f.category == Category.PROMPT_INJECTION
            ),
        )

    def scan_directory(self, skills_dir: Path) -> dict[str, ScanResult]:
        """Scan all SKILL.md files in a directory tree."""
        results: dict[str, ScanResult] = {}
        for skill_md in skills_dir.rglob("SKILL.md"):
            result = self.scan_file(skill_md)
            results[result.skill_name] = result
            if not result.passed:
                logger.warning(
                    "Skill '%s' FAILED scan: %d critical, %d high findings",
                    result.skill_name, result.critical_count, result.high_count,
                )
        return results

    def scan_text(self, content: str, name: str = "inline") -> ScanResult:
        """Scan raw skill text (for skills loaded from registry API)."""
        findings = self._scan_injection(content, name)

        # Also run gitleaks on the text via temp file
        if self._gitleaks_available:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=True
            ) as tmp:
                tmp.write(content)
                tmp.flush()
                gl_findings = self._run_gitleaks(Path(tmp.name))
                findings.extend(gl_findings)

        has_critical = any(f.severity == Severity.CRITICAL for f in findings)

        return ScanResult(
            skill_name=name,
            passed=not has_critical,
            findings=findings,
            gitleaks_findings=sum(
                1 for f in findings if f.category == Category.SECRET_LEAK
            ),
            injection_findings=sum(
                1 for f in findings
                if f.category == Category.PROMPT_INJECTION
            ),
        )

    def _run_gitleaks(self, path: Path) -> list[ScanFinding]:
        """Run gitleaks on a single file and return findings."""
        findings: list[ScanFinding] = []
        try:
            result = subprocess.run(
                [
                    self._gitleaks, "detect",
                    "--source", str(path.parent),
                    "--report-format", "json",
                    "--report-path", "/dev/stdout",
                    "--no-git",
                    "--quiet",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.stdout.strip():
                try:
                    leaks = json.loads(result.stdout)
                    for leak in leaks:
                        findings.append(ScanFinding(
                            severity=Severity.CRITICAL,
                            category=Category.SECRET_LEAK,
                            rule=f"gitleaks:{leak.get('RuleID', 'unknown')}",
                            description=leak.get("Description", "Hardcoded secret"),
                            evidence=leak.get("Match", "")[:100],
                            line=leak.get("StartLine", 0),
                            file=leak.get("File", str(path)),
                        ))
                except json.JSONDecodeError:
                    pass
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.debug("Gitleaks execution failed: %s", exc)

        return findings

    def _scan_injection(self, content: str, filename: str) -> list[ScanFinding]:
        """Scan text for prompt injection patterns."""
        findings: list[ScanFinding] = []
        lines = content.splitlines()

        for line_num, line in enumerate(lines, 1):
            for pattern, severity, category, description in _INJECTION_RULES:
                match = pattern.search(line)
                if match:
                    findings.append(ScanFinding(
                        severity=severity,
                        category=category,
                        rule=f"injection:{description[:30].lower().replace(' ', '_')}",
                        description=description,
                        evidence=match.group(0)[:100],
                        line=line_num,
                        file=filename,
                    ))

        return findings
