---
id: S-115
title: "Agent-to-agent networking"
domain: intelligence
status: research
priority: P3
effort: "~500 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-115: Agent-to-agent networking

## Problem
Agents can't directly delegate to or query each other. All coordination goes through the conductor orchestrator.

## Solution
Direct agent-to-agent RPC layer. Agent A can spawn Agent B and await its result without going back through the main loop.

## Open questions
- Authority delegation: how to prevent privilege escalation through agent chains?
- Deadlock detection: circular delegation cycles
- Observability: trace IDs must span agent-to-agent calls

## Key files
- `conductor/orchestrator/agents/agent_spec.py` (networking extension)
