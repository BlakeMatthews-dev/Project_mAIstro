---
id: S-013
title: "Systemd services (gateway + conductor)"
domain: infra
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-013: Systemd services

Gateway and conductor run as managed systemd units with restart-on-failure, journal logging, and dependency ordering.

## Key files
- `conductor/deploy/conductor.service`
- `conductor/deploy/gateway.service`
