---
id: S-106
title: "User profile extraction from conversations"
domain: conductor
status: draft
priority: P3
effort: "~200 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-106: User profile extraction

## Problem
Conductor re-learns user preferences (timezone, communication style) from scratch every session.

## Solution
After each session, extract and persist per-user profile signals: timezone, preferred response length, topic preferences, technical depth. Feed into context layer on session start.

## Acceptance Criteria
- [ ] Per-user profile stored in episodic memory (T5 LONG or T6 LESSON)
- [ ] Profile auto-updated after sessions with high-confidence signals
- [ ] Profile injected into context at session start
