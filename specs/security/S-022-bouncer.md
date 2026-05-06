---
id: S-022
title: "Bouncer — security screening (20+ regex + LLM)"
domain: security
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-022: Bouncer

Pre-execution security screen: 20+ regex patterns for injection/exfil/prompt-attack patterns, negative LLM pass for ambiguous cases. Blocks non-recoverable `TOOL_VIOLATION` and `SAFETY_VIOLATION` errors.

## Key files
- `conductor/orchestrator/agents/bouncer.py`
