---
id: S-102
title: "PWA dashboard — mobile-installable"
domain: infra
status: draft
priority: P3
effort: "~200 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-102: PWA dashboard

## Problem
Dashboard not installable on mobile home screen; no push notification support from web.

## Solution
Add service worker + `manifest.json` + web push subscription to existing dashboard.

## Acceptance Criteria
- [ ] "Add to Home Screen" prompt appears on iOS/Android
- [ ] Basic offline shell loads when network is unavailable
- [ ] Web push notifications receivable from conductor
