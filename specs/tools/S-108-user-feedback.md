---
id: S-108
title: "User feedback on responses — thumbs up/down"
domain: tools
status: draft
priority: P2
effort: "~150 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-108: User feedback

## Problem
No structured feedback loop for individual responses. Conductor can't distinguish good outputs from mediocre ones in real-time.

## Solution
Add 👍/👎 reaction to any chat response (like digest ratings). Feedback persisted to Langfuse annotation + episodic memory. Feeds into recipe variant scoring.

## Acceptance Criteria
- [ ] Thumbs up/down available on all chat responses in UI
- [ ] Feedback logged to Langfuse annotation score
- [ ] Recipe variant ELO updated based on feedback
