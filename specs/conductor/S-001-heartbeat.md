---
id: S-001
title: "Heartbeat wired into conductor main loop"
domain: conductor
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-001: Heartbeat wired into conductor main loop

Autonomous 30-minute check-in loop. Reads HEARTBEAT.md, decides whether any item requires action, messages the user or returns HEARTBEAT_OK.

## Key files
- `src/infra/heartbeat-runner.ts`
- `src/infra/heartbeat-active-hours.ts`
- `src/infra/heartbeat-wake.ts`
