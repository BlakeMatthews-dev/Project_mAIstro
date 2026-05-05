---
id: S-036
title: "Message board — agent → human async messaging"
domain: tools
status: done
priority: P2
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-036: Message board

Background agents post observations, warnings, and suggestions to a board. Human reviews on next heartbeat or dashboard visit. Non-blocking alternative to interrupting the user.

## Key files
- `conductor/orchestrator/memory/board.py`
