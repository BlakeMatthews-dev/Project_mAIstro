---
id: S-103
title: "Email channel — conductor@emeraldfam.org"
domain: channels
status: draft
priority: P2
effort: "~300 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-103: Email channel

## Problem
No email ingestion or outbound email from conductor. Can't reach conductor via email.

## Solution
Cloudflare Email Routing → conductor inbound handler. Sender allowlist for security. Outbound: digests and alerts via SMTP/API.

## Acceptance Criteria
- [ ] Inbound: email to conductor@emeraldfam.org creates a task
- [ ] Sender allowlist enforced
- [ ] Outbound: morning digests deliverable via email (not just channel message)
- [ ] Outbound: alert emails for P0 infrastructure events
