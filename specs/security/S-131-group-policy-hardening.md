---
id: S-131
title: "Telegram Allowlist Hardening"
domain: security
status: done
priority: P2
effort: ""
created: 2026-01-05
completed: 2026-01-05
owner: conductor
commits: []
pr: "216"
---

# S-131: Telegram Allowlist Hardening

_Promoted from `docs/experiments/plans/group-policy-hardening.md`_

## Summary

Telegram allowlists now accept `telegram:` and `tg:` prefixes case-insensitively, and tolerate accidental whitespace. This aligns inbound allowlist checks with outbound send normalization.

## What changed

- Prefixes `telegram:` and `tg:` are treated the same (case-insensitive).
- Allowlist entries are trimmed; empty entries are ignored.

## Why it matters

Copy/paste from logs or chat IDs often includes prefixes and whitespace. Normalizing avoids false negatives when deciding whether to respond in DMs or groups.
