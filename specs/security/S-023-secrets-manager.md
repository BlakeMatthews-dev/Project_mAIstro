---
id: S-023
title: "Secrets Manager — Vaultwarden integration"
domain: security
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-023: Secrets Manager

Conductor reads secrets from Vaultwarden via its API. No plaintext secrets in config files or environment variables.

## Key files
- `conductor/orchestrator/infra/secrets.py`
