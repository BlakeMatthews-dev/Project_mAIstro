---
id: S-101
title: "Traefik route for dashboard (proper HTTPS)"
domain: infra
status: draft
priority: P2
effort: "15 min"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-101: Traefik route for dashboard

## Problem
Dashboard is currently HTTP-only, not behind Traefik.

## Solution
Add Traefik labels to conductor-dash container. TLS via existing Let's Encrypt resolver.

## Acceptance Criteria
- [ ] Dashboard accessible at `https://dash.emeraldfam.org` (or equivalent)
- [ ] HTTP → HTTPS redirect
- [ ] Auth (S-017) still works behind Traefik
