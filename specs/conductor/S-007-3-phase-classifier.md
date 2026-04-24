---
id: S-007
title: "3-phase classifier (keywords + negative signals + LLM fallback)"
domain: conductor
status: done
priority: P1
effort: ""
created: 2026-03-23
completed: 2026-03-23
owner: conductor
commits: []
---

# S-007: 3-phase classifier

Fast intent classification: keyword trie → negative signal check → LLM fallback. Minimizes LLM calls for common patterns.

## Key files
- `conductor/orchestrator/agents/intent_router.py`
