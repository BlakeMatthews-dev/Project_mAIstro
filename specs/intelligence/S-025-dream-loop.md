---
id: S-025
title: "Dream Loop — idle-time memory consolidation"
domain: intelligence
status: done
priority: P2
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-025: Dream Loop

During idle periods, conductor runs a consolidation cycle: promotes working memory to long-term, clusters related learnings, and prunes low-confidence entries.

## Key files
- `conductor/orchestrator/agents/experimental/dream_loop.py`
