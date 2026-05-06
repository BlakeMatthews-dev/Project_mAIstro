---
id: S-038
title: "Skill Forge — agent creates its own SKILL.md tools on demand"
domain: tools
status: done
priority: P2
effort: ""
created: 2026-03-23
completed: 2026-03-23
owner: conductor
commits: []
---

# S-038: Skill Forge

Conductor detects capability gaps, generates a new SKILL.md via the coder agent, runs it through Phantom Execution, then installs to skills library on success.

## Key files
- `conductor/orchestrator/agents/experimental/skill_forge.py`
