---
id: S-005
title: "Agent Factory (recipes, Thompson sampling, typed outputs)"
domain: conductor
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-005: Agent Factory

Named-recipe dispatch with Thompson sampling over prompt variants. Each call returns a typed `AgentOutput` with timing, trace IDs, and structured errors.

## Key files
- `conductor/orchestrator/agents/agent_factory.py`
- `conductor/orchestrator/agents/agent_spec.py`
- `conductor/orchestrator/agents/recipes/*.yaml`
