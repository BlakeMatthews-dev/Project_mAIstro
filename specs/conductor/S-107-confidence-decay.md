---
id: S-107
title: "Confidence decay on learnings"
domain: conductor
status: draft
priority: P3
effort: "~50 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-107: Confidence decay on learnings

## Problem
Learnings in episodic memory never expire. Stale facts accumulate and pollute context.

## Solution
Learnings unused for 30 days have their confidence score halved. Below threshold, they're demoted from active context (still retained in archive tier).

## Acceptance Criteria
- [ ] Decay runs on heartbeat (or nightly cron)
- [ ] Decayed learnings visible in dashboard Intel tab
- [ ] Manual override to pin a learning (confidence floor = 1.0)
