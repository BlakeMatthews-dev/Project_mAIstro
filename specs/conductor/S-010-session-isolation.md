---
id: S-010
title: "Per-user session isolation — session_id scoped by user_id"
domain: conductor
status: done
priority: P1
effort: ""
created: 2026-03-23
completed: 2026-03-23
owner: conductor
commits: []
---

# S-010: Per-user session isolation

Each user_id gets its own session scope. Context, memory retrieval, and tool grants are scoped per user to prevent bleed.
