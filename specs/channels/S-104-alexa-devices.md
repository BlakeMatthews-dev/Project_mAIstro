---
id: S-104
title: "Alexa Media Player / Alexa Devices setup"
domain: channels
status: draft
priority: P2
effort: ""
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-104: Alexa Devices setup

## Problem
Amazon auth flow failing for Alexa Media Player (HACS) — phone verification issue.

## Solution
Try "Alexa Devices" core integration (Amazon OAuth) through HA UI instead of HACS. Manual OAuth flow.

## Acceptance Criteria
- [ ] Alexa devices visible in HA entity list
- [ ] TTS announcements playable via conductor ha_notify
- [ ] Voice feedback from conductor audible on Echo devices
