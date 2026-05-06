---
id: S-114
title: "Collective Unconscious — federated wisdom sharing"
domain: intelligence
status: research
priority: P3
effort: "~400 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-114: Collective Unconscious

## Problem
Learnings are siloed per conductor instance. Two conductors on different machines can't share discovered patterns.

## Solution
Cross-tenant T7 wisdom tier. High-confidence learnings (score > 0.9) optionally shared to a federated pool. Pulled during dream loop consolidation.

## Open questions
- Privacy: what classes of memory are safe to share?
- Trust: how to validate cross-instance learnings?
- Transport: peer-to-peer or central broker?

## Key files
- `conductor/orchestrator/agents/experimental/` (new)
