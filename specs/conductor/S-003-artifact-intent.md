---
id: S-003
title: "ARTIFACT intent handler"
domain: conductor
status: done
priority: P2
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-003: ARTIFACT intent handler

Routes artifact-generation intents (documents, diagrams) to the artifact agent role with write access to `file_ops`.

## Key files
- `conductor/orchestrator/agents/intent_router.py`
- `conductor/orchestrator/agents/agent_spec.py` (AgentRole.ARTIFACT)
