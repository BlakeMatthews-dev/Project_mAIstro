---
id: S-006
title: "APM — 7-section personality template"
domain: conductor
status: done
priority: P2
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-006: Agent Personality Matrix

Persistent identity for the conductor: identity, values, communication style, standing orders, guardrails, relationship context, self-knowledge. Loaded into every agent spawn as highest-priority context. Git-tracked and editable by agent or human.

## Key files
- `conductor/orchestrator/memory/apm.py`
- `conductor/projects/<project>/apm.yaml`
