---
id: S-024
title: "JWT auth — Keycloak RS256 validation + role-based tool access"
domain: security
status: done
priority: P1
effort: ""
created: 2026-03-23
completed: 2026-03-23
owner: conductor
commits: []
---

# S-024: JWT auth

Inbound requests validated with Keycloak RS256 JWTs. Roles extracted from token claims map to tool whitelists in `AgentSpec`.
