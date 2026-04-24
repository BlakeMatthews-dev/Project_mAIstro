---
id: S-105
title: "Uncapped tool loop for heartbeat tasks"
domain: conductor
status: draft
priority: P3
effort: "~30 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-105: Uncapped tool loop for heartbeat tasks

## Problem
Heartbeat tasks share the 3-round tool call cap used for chat. Autonomous background tasks hit the cap before completing.

## Solution
When a task is spawned from heartbeat (not live-chat lane), apply a 50-round cap + explicit token budget instead of the 3-round chat cap.

## Acceptance Criteria
- [ ] Heartbeat-spawned tasks run up to 50 tool call rounds
- [ ] Token budget enforced as a hard stop
- [ ] Live-chat tasks unaffected (still 3-round cap)
