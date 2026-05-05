---
id: S-019
title: "OpenWebUI JWT passthrough — X-OpenWebUI-* header auth"
domain: infra
status: done
priority: P2
effort: ""
created: 2026-03-23
completed: 2026-03-23
owner: conductor
commits: []
---

# S-019: OpenWebUI JWT passthrough

Enabled `ENABLE_FORWARD_USER_INFO_HEADERS`. Conductor authenticates via `X-OpenWebUI-*` headers forwarded from OpenWebUI sessions.
