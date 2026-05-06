---
id: S-031
title: "Mood Ring — adaptive behavior from system health"
domain: intelligence
status: done
priority: P2
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-031: Mood Ring

Conductor monitors system health metrics (disk, GPU temp, memory pressure) and adjusts its behavior (verbosity, retry aggressiveness, proactive alerts) accordingly.

## Key files
- `conductor/orchestrator/agents/experimental/mood_ring.py`
