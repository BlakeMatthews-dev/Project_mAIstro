---
id: S-130
title: "Cron Add Hardening & Schema Alignment"
domain: infra
status: done
priority: P2
effort: ""
created: 2026-01-05
completed: 2026-01-05
owner: conductor
commits: []
pr: ""
---

# S-130: Cron Add Hardening & Schema Alignment

_Promoted from `docs/experiments/plans/cron-add-hardening.md`_

## Context

Recent gateway logs show repeated `cron.add` failures with invalid parameters (missing `sessionTarget`, `wakeMode`, `payload`, and malformed `schedule`). This indicates that at least one client (likely the agent tool call path) is sending wrapped or partially specified job payloads. Separately, there is drift between cron provider enums in TypeScript, gateway schema, CLI flags, and UI form types, plus a UI mismatch for `cron.status` (expects `jobCount` while gateway returns `jobs`).

## Goals

- Stop `cron.add` INVALID_REQUEST spam by normalizing common wrapper payloads and inferring missing `kind` fields.
- Align cron provider lists across gateway schema, cron types, CLI docs, and UI forms.
- Make agent cron tool schema explicit so the LLM produces correct job payloads.
- Fix the Control UI cron status job count display.
- Add tests to cover normalization and tool behavior.

## Non-goals

- Change cron scheduling semantics or job execution behavior.
- Add new schedule kinds or cron expression parsing.
- Overhaul the UI/UX for cron beyond the necessary field fixes.

## What changed

- `cron.add` and `cron.update` now normalize common wrapper shapes and infer missing `kind` fields.
- Agent cron tool schema matches the gateway schema, which reduces invalid payloads.
- Provider enums are aligned across gateway, CLI, UI, and macOS picker.
- Control UI uses the gateway's `jobs` count field for status.

## Verification

- Watch gateway logs for reduced `cron.add` INVALID_REQUEST errors.
- Confirm Control UI cron status shows job count after refresh.
