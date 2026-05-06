---
id: S-004
title: "CONVERSATION intent handler"
domain: conductor
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-004: CONVERSATION intent handler

Routes casual conversation and non-task intents to the conversation role with no tool access, preserving slot capacity for background work.

## Key files
- `conductor/orchestrator/agents/intent_router.py`
- `conductor/orchestrator/agents/agent_spec.py` (AgentRole.CONVERSATION)
