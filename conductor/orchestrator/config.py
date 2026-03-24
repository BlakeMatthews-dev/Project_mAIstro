"""Orchestrator configuration — loaded from conductor.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class OrchestratorConfig(BaseModel):
    project_id: str
    project_dir: str
    obsidian_vault: str
    gateway_url: str = "http://localhost:9090"
    inference_url: str = "http://localhost:8080"
    max_retries: int = 3
    accept_threshold: float = 7.0
    max_working_memory_tokens: int = 8000
    layer0_path: str = "./constraints.md"
    training_data_dir: str = "./data/training"
    exemplar_library_dir: str = "./data/exemplars"

    # Inference provider: "local", "anthropic", "openai", or "openrouter"
    inference_provider: str = "local"
    inference_api_key: str = ""
    inference_api_base: str = ""
    inference_model: str = ""
    inference_max_tokens: int = 4096

    # Routing: separate provider/model for intent classification.
    # Use a smarter cloud model for routing while keeping local for generation.
    # If routing_provider is empty, classification goes through the gateway.
    routing_provider: str = ""       # "anthropic", "openai", "openrouter", or "" (use gateway)
    routing_api_key: str = ""
    routing_api_base: str = ""
    routing_model: str = ""

    # Heartbeat interval in minutes (how often the autonomous loop runs)
    heartbeat_interval_minutes: int = 1

    # Vault sync: "local" (default), "git", "syncthing", or "couchdb"
    vault_sync_mode: str = "local"
    # Git sync options
    vault_sync_git_remote: str = "origin"
    vault_sync_git_branch: str = "main"
    # Syncthing sync options
    vault_sync_syncthing_api: str = "http://localhost:8384"
    vault_sync_syncthing_api_key: str = ""
    vault_sync_syncthing_folder_id: str = ""
    # CouchDB sync options (Obsidian LiveSync)
    vault_sync_couchdb_url: str = "http://localhost:5984"
    vault_sync_couchdb_database: str = "obsidian"
    vault_sync_couchdb_username: str = ""
    vault_sync_couchdb_password: str = ""
    vault_sync_couchdb_conductor_prefix: str = "conductor/"

    # Home Assistant (Abra agent)
    ha_url: str = ""                    # e.g. "http://homeassistant.local:8123"
    ha_token: str = ""                  # Long-lived access token
    ha_sync_entities: bool = True       # Pull entities from HA at startup
    # Alexa Echo device ID → HA area_id mapping
    # e.g. {"amzn1.ask.device.XXX": "living_room"}
    ha_alexa_device_map: dict[str, str] = {}

    @classmethod
    def from_yaml(cls, path: str) -> OrchestratorConfig:
        """Load config from a YAML file, with env var fallback for secrets.

        Any config field can be overridden by an env var with the same name
        (uppercase). Secrets should come from env vars (loaded by systemd
        EnvironmentFile), not from the YAML file.
        """
        import os

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

        # Env var fallback for secrets — these should NOT be in YAML
        secret_fields = [
            "ha_token", "inference_api_key", "routing_api_key",
        ]
        for field_name in secret_fields:
            env_name = field_name.upper()
            env_val = os.environ.get(env_name, "")
            if env_val and not data.get(field_name):
                data[field_name] = env_val

        return cls(**data)
