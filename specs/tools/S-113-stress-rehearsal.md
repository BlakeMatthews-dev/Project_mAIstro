---
id: SPEC-006
title: "Stress Rehearsal — controlled chaos testing"
repo: Project_mAIstro
kind: spec
status: Proposed
created: 2026-03-23
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# S-113: Stress Rehearsal

## Problem
No way to validate conductor resilience against resource exhaustion, partial failures, or adversarial inputs without hitting production.

## Solution
Scheduled chaos runs in a sandboxed context: inject random delays, partial tool failures, memory pressure. Observe and report how conductor degrades.

## Acceptance Criteria
- [ ] At least 5 chaos scenarios (timeout, OOM, tool failure, bad input, disk full)
- [ ] Runs on demand (`maistro stress run`) and on weekly schedule via the reactor (S-143)
- [ ] Results posted to dashboard + board with per-scenario pass/fail and degradation metrics
- [ ] Sandbox isolation: chaos runs execute in a subprocess that has no access to the production SQLite database (`~/.conductor/state.db`), the production vault (`~/.conductor/secrets.age`), or external production API endpoints; a chaos run cannot write outside `~/.conductor/stress-rehearsal/`; isolation enforced at the process level (restricted file-descriptor inheritance, not only by convention)
- [ ] The chaos framework halts immediately on `maistro stress stop`; all active chaos subprocesses are signaled and confirmed dead within 5 seconds; the main conductor reactor (S-143) is unaffected by the halt
- [ ] A chaos run that escapes its sandbox (attempts a write outside the rehearsal directory or an outbound call to a production endpoint) is detected and logged as `STRESS_SANDBOX_VIOLATION`; the run is aborted

## Key files
- `conductor/orchestrator/agents/experimental/stress_rehearsal.py`

## Verification

- Run all 5 scenarios; verify the conductor degradation report appears on the dashboard and board within 5 minutes.
- With a stress run in progress, inspect `lsof` / `strace` output on the stress subprocess; verify no file descriptors to `state.db` or `secrets.age` are open.
- Attempt a write to `~/.conductor/state.db` from inside a chaos scenario (unit test); verify `STRESS_SANDBOX_VIOLATION` is logged and the run aborts.
- Run `maistro stress stop` with an active 60-second chaos scenario; verify all chaos subprocesses exit within 5 seconds and the conductor reactor continues serving requests normally.
- Schedule weekly stress run; verify it runs without disrupting live agent tasks or the reactor loop.
