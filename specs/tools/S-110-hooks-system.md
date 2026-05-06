---
id: S-110
title: "General hooks system — event-driven shell commands"
domain: tools
status: draft
priority: P2
effort: "~250 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-110: General hooks system

## Problem
No way to trigger custom shell commands on conductor events (task complete, memory update, heartbeat, etc.) without modifying conductor code.

## Solution
`~/.conductor/hooks/<event>/` directory. Each file is an executable script. Conductor invokes matching scripts on event fire with event context as env vars.

## Acceptance Criteria
- [ ] At least: `on-task-complete`, `on-heartbeat`, `on-memory-update`, `on-error` events
- [ ] Hook scripts receive event payload as env vars
- [ ] Failed hooks log to board (don't crash conductor)
- [ ] Security: hooks must be owned by the conductor user (no world-writable)
