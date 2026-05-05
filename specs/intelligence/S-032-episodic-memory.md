---
id: S-032
title: "7-tier episodic memory (PG + pg_trgm)"
domain: intelligence
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-032: 7-tier episodic memory

PostgreSQL-backed memory with 7 tiers: FLASH, WORKING, SHORT, MEDIUM, LONG, LESSON, LORE. pg_trgm for fuzzy text recall. Confidence scoring and decay per tier.

## Key files
- `conductor/orchestrator/memory/episodic.py`
- `conductor/orchestrator/memory/layer0.py` / `layer1.py` / `layer2.py`
