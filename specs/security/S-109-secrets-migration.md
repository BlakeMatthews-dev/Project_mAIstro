---
id: S-109
title: "Secrets → Vaultwarden migration"
domain: security
status: draft
priority: P1
effort: "2 hours"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-109: Secrets → Vaultwarden migration

## Problem
Some secrets still stored as env vars or plaintext in config files. S-023 added Vaultwarden integration but migration of existing secrets is incomplete.

## Solution
Audit all config files and env vars for secrets. Move each to Vaultwarden. Update conductor to read from vault at startup.

## Acceptance Criteria
- [ ] Zero plaintext secrets in any config file or .env
- [ ] All API keys, passwords, tokens read from Vaultwarden
- [ ] `gitleaks` pre-commit hook passes on all tracked files
