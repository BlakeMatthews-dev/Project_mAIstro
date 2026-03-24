"""Test configuration — sets up environment for gateway auth."""
import os
from pathlib import Path


def _load_secrets():
    """Load secrets from the centralized secrets file if available."""
    secrets_file = Path("/root/.conductor-secrets/conductor.env")
    if secrets_file.exists():
        for line in secrets_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                if key.strip() not in os.environ:
                    os.environ[key.strip()] = value.strip()


_load_secrets()

# Configure the shared gateway auth module
try:
    from orchestrator import _gateway_auth
    _gateway_auth.configure("http://localhost:9090")
except Exception:
    pass
