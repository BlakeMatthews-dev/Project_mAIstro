---
id: S-113
title: "Stress Rehearsal — controlled chaos testing"
domain: tools
status: draft
priority: P2
effort: "~250 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-113: Stress Rehearsal

## Problem
No way to validate conductor resilience against resource exhaustion, partial failures, or adversarial inputs without hitting production.

## Solution
Scheduled chaos runs in a sandboxed context: inject random delays, partial tool failures, memory pressure. Observe and report how conductor degrades.

## Acceptance Criteria
- [ ] At least 5 chaos scenarios (timeout, OOM, tool failure, bad input, disk full)
- [ ] Runs on demand and on weekly schedule
- [ ] Results posted to dashboard + board
- [ ] Does not affect live production services

## Key files
- `conductor/orchestrator/agents/experimental/stress_rehearsal.py`
