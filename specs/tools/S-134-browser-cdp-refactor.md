---
id: S-134
title: "Browser Evaluate CDP Refactor — isolate act:evaluate from Playwright queue"
domain: tools
status: draft
priority: P2
effort: ""
created: 2026-02-10
completed: ""
owner: conductor
commits: []
pr: "13498"
---

# S-134: Browser Evaluate CDP Refactor

_Promoted from `docs/experiments/plans/browser-evaluate-cdp-refactor.md`_

## Problem

`act:evaluate` runs via Playwright. Playwright serializes CDP commands per page, so a stuck or long-running evaluate can block all later browser actions on that tab.

PR #13498 added a pragmatic safety net (bounded evaluate + best-effort recovery). This spec describes the full refactor.

## Goals

- `act:evaluate` cannot permanently block later browser actions on the same tab
- Single end-to-end timeout budget (caller → route → page)
- Abort and timeout treated identically across HTTP and in-process dispatch
- Element targeting supported without replacing all Playwright actions

## Architecture

1. **Deadline propagation**: `createBudget({ timeoutMs, signal })` helper used in `client-fetch.ts`, `runner.ts`, and browser action implementations
2. **Separate CDP evaluate engine**: `src/browser/cdp-evaluate.ts` — own WebSocket + CDP session, not sharing Playwright's page command queue
3. **AX tree backendDOMNodeId mapping**: enable element-targeted evaluate without Playwright locators
4. **Role ref extensions**: `backendDOMNodeId` added to role refs for CDP path

## Acceptance Criteria

- [ ] Stuck evaluate cannot block tab operations (verified by concurrent test)
- [ ] Caller-supplied `timeoutMs` propagated end-to-end without loss
- [ ] Existing `act:evaluate` callers unaffected (backward compatible)
- [ ] `browser.evaluateEnabled` gate still enforced
