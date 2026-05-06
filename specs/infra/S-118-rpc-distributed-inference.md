---
id: S-118
title: "RPC distributed inference (P40 + 3070 Ti)"
domain: infra
status: research
priority: P2
effort: ""
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-118: RPC distributed inference

Split model across P40 (primary) and 3070 Ti (secondary) via llama.cpp RPC. Enables larger context or bigger models than either GPU can hold alone.
