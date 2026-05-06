---
id: S-133
title: "PTY and Process Supervision — reliable interactive process lifecycle"
domain: infra
status: in_progress
priority: P1
effort: ""
created: 2026-02-15
completed: ""
owner: conductor
commits: []
---

# S-133: PTY and Process Supervision

_Promoted from `docs/experiments/plans/pty-process-supervision.md`_

## Problem

Need one reliable lifecycle for long-running command execution across exec foreground, exec background, process actions (poll, log, send-keys, kill, remove), and CLI agent runner subprocesses.

## Completed

1. Explicit PTY command contract (`SpawnInput` discriminated union; `ptyCommand` replaces generic argv)
2. Process layer type decoupling (supervisor no longer imports agent types)
3. Supervisor-driven cancellation for process kill/remove
4. Real OS-level fallback termination (process-tree semantics)
5. Unified CLI watchdog defaults (`cli-watchdog-defaults.ts`)
6. PTY contract edge-case tests added
7. Reliability gap tests added

## Remaining

- Durability/startup reconciliation: explicitly in-memory only by design. `reconcileOrphans()` is a no-op. Active runs are not recovered after process restart.

## Key files
- `src/process/supervisor/`
- `src/agents/bash-tools.exec-runtime.ts`
- `src/agents/bash-tools.process.ts`
- `src/process/kill-tree.ts`
