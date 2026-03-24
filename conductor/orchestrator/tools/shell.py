"""
Shell Tool — Execute shell commands in the project directory.

Safety constraints:
  - Commands run in a subprocess with timeout
  - Working directory is locked to project root
  - Output is captured and truncated if too large
  - Dangerous commands are blocked by default

Architecture note: The Conductor uses this via structured tool calls,
not raw shell access. All invocations are logged.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Allowed command prefixes — allowlist, not blocklist.
# Only commands starting with these prefixes can execute.
# The model picks from this list; anything else is rejected.
ALLOWED_PREFIXES = [
    # Build & test
    "python", "pip", "pytest", "mypy", "ruff", "bandit",
    "npm", "node", "npx", "yarn",
    "make", "cargo", "go ",
    # Version control
    "git ",
    # File inspection (read-only)
    "cat ", "head ", "tail ", "wc ", "diff ", "find ", "ls ",
    "grep ", "rg ", "ag ",
    # System inspection (read-only)
    "df ", "du ", "free ", "ps ", "top -bn1", "uptime",
    "docker ps", "docker logs", "docker inspect",
    "systemctl status", "journalctl",
    "nvidia-smi", "lsblk", "uname",
    "curl -s", "wget -q",  # read-only HTTP
    # NOTE: bash/sh deliberately excluded — use specific commands above
]

# Patterns that indicate shell injection or dangerous operations
BLOCKED_PATTERNS = [
    "rm -rf /", "rm -rf ~", "rm -rf .",
    "mkfs", "dd if=", "> /dev/sd",
    "chmod 777", "chmod -R 777",
    "| sh", "| bash", "| python",
    "sudo ", "; sudo",
    "eval ", "exec ",
    "--no-verify", "--force",
    "`",        # backtick command substitution
    "$(",       # subshell
    "&&",       # command chaining
    "||",       # command chaining
    ";",        # command separator
    ">/",       # redirect to absolute path
    ">>",       # append redirect
]

MAX_OUTPUT_BYTES = 64 * 1024  # 64KB


@dataclass
class ShellResult:
    success: bool
    command: str
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool = False


class Shell:
    def __init__(self, project_dir: str, timeout: int = 60) -> None:
        self._cwd = project_dir
        self._timeout = timeout

    async def run(
        self,
        command: str,
        timeout: int | None = None,
    ) -> ShellResult:
        """Execute a shell command in the project directory."""
        # Safety: allowlist check first
        cmd_lower = command.lower().strip()
        allowed = any(cmd_lower.startswith(prefix) for prefix in ALLOWED_PREFIXES)
        if not allowed:
            logger.warning("Shell BLOCKED (not in allowlist): %s", command[:80])
            return ShellResult(
                success=False,
                command=command,
                stdout="",
                stderr=f"Blocked: command not in allowlist. Allowed prefixes: {', '.join(ALLOWED_PREFIXES[:10])}...",
                return_code=-1,
            )

        # Safety: blocklist check second (catches dangerous patterns within allowed commands)
        for pattern in BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                logger.warning("Shell BLOCKED (dangerous pattern): %s", command[:80])
                return ShellResult(
                    success=False,
                    command=command,
                    stdout="",
                    stderr=f"Blocked: command matches dangerous pattern '{pattern}'",
                    return_code=-1,
                )

        effective_timeout = timeout or self._timeout
        logger.info("Shell: %s (timeout=%ds)", command, effective_timeout)

        try:
            # Use create_subprocess_exec (argv) not create_subprocess_shell
            # to prevent shell injection. Split command into argv safely.
            import shlex
            argv = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=effective_timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ShellResult(
                    success=False,
                    command=command,
                    stdout="",
                    stderr=f"Command timed out after {effective_timeout}s",
                    return_code=-1,
                    timed_out=True,
                )

            stdout = stdout_bytes[:MAX_OUTPUT_BYTES].decode(errors="replace")
            stderr = stderr_bytes[:MAX_OUTPUT_BYTES].decode(errors="replace")

            return ShellResult(
                success=proc.returncode == 0,
                command=command,
                stdout=stdout,
                stderr=stderr,
                return_code=proc.returncode or 0,
            )
        except Exception as exc:
            return ShellResult(
                success=False,
                command=command,
                stdout="",
                stderr=str(exc),
                return_code=-1,
            )
