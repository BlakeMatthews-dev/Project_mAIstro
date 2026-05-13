---
id: SPEC-003
title: "Secrets migration — move plaintext secrets to the vault backend"
repo: Project_mAIstro
kind: spec
status: Proposed
created: 2026-03-23
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# S-109: Secrets Migration

## Problem

Some secrets are still stored as environment variables or plaintext in config files. The correct vault backend depends on the product SKU:

- **Agent Conductor** (household/personal) — S-141 age-encrypted file vault, unlocked by admin keypair derived from the Conductor Seed (S-149). Secrets belong in `~/.conductor/secrets.age`; accessed via `secrets.use(name, callback)`.
- **Agent Stronghold** (multitenant) — S-023 Vaultwarden API. Secrets read from Vaultwarden at startup.

This spec tracks migration of existing plaintext secrets to whichever backend is in use. The `secrets.use()` API is the same in both cases; only the backend differs.

## Solution

1. Run `gitleaks` against the full git history to enumerate all committed plaintext secrets (API keys, passwords, tokens, DB connection strings, webhook secrets).
2. For each discovered secret:
   - **Agent Conductor:** `maistro vault add <name>` — prompts for value via TTY; never via CLI argument or env var.
   - **Agent Stronghold:** add via Vaultwarden UI or Bitwarden CLI.
3. Replace every plaintext usage in code, config, and `.env` files with `secrets.use("<name>", ...)`.
4. Delete the plaintext from config files and `.env` files.
5. Verify `gitleaks` passes clean on the working tree.
6. Rotate any secret that was ever committed to git history — the old value is compromised regardless of whether the commit was later reverted or squashed.

## Acceptance Criteria

- [ ] Zero plaintext secrets in any tracked config file or `.env` file; `gitleaks` pre-commit hook passes on all tracked files with no suppressions
- [ ] All API keys, passwords, tokens, and connection strings are accessed via `secrets.use()` from the appropriate vault backend (S-141 for Agent Conductor; S-023 Vaultwarden for Agent Stronghold)
- [ ] Conductor fails closed at startup when a required secret is absent from the vault: conductor logs `SECRET_MISSING` naming the missing key and exits; it does not start in a degraded mode with the missing credential silently unavailable
- [ ] Migration is idempotent: re-running the migration process does not duplicate vault entries or produce errors on subsequent runs
- [ ] Any secret that was ever in git history has been rotated in the vault (old value is no longer valid at the upstream service)
- [ ] `gitleaks` scan covers full git history, not only the working tree

## Implementation Notes

- `gitleaks` configuration lives at `.gitleaks.toml` in the repo root. Custom rules for project-specific secret patterns (e.g., HA long-lived tokens, LiteLLM keys) should be added to the config.
- For Agent Conductor, bulk import is not supported — `maistro vault add` is interactive (TTY) to prevent shell history leaks. Each secret is added individually.
- For Agent Stronghold, Vaultwarden's bulk import API is acceptable since Vaultwarden is a dedicated secrets service with its own audit log.
- After migration, audit the conductor startup logs for any `secrets.use()` call that raises `SECRET_MISSING`. The set of required secrets at startup should be documented in a startup manifest so the error message is actionable.
- Secrets previously set as environment variables in systemd unit files or `.env` files: remove from those locations and ensure the corresponding `EnvironmentFile=` or `Environment=` directives are removed from the unit file to prevent accidental re-introduction.

## Verification

- Run `gitleaks detect --source . --log-opts="--all"` (full history scan); verify zero findings.
- Remove one vault entry that conductor requires at startup; attempt to start; verify `SECRET_MISSING` error names the missing key and conductor exits immediately.
- Re-add the missing entry; restart; verify conductor starts normally.
- Run the migration tooling twice on the same vault; verify no duplicate entries and no errors on second run.
- Confirm each rotated secret is invalid at its upstream service (test a curl with the old value; verify 401/403).
