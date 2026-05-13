---
id: SPEC-008
title: "Agent-to-agent networking"
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
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# S-115: Agent-to-agent networking

## Problem
Agents can't directly delegate to or query each other. All coordination goes through the conductor orchestrator.

## Solution
Direct agent-to-agent RPC layer. Agent A can spawn Agent B and await its result without going back through the main loop.

## Open questions

- **Authority delegation (RESOLVED → S-145 §6):** privilege escalation through agent chains is prevented by the capability envelope model. Each conductor in the chain enforces the initiator's original permission envelope; adding wraps can only narrow the scope, never widen it. The Bouncer (S-022) screens every incoming edge before the target node runs; no edge bypasses it regardless of how the delegation chain was constructed.

- **Deadlock / circular delegation (RESOLVED → S-145 §6):** depth budget (default 16 hops), latency budget (default 60 s), and token-spend budget (default 1M tokens) are tracked per chain. A→B→A cycles hit the depth budget and fail with a structured error from the conductor whose budget is crossed; no explicit cycle detection algorithm is required.

- **Observability (RESOLVED → S-145 §6 + S-021 + S-152):** initiator identity and acting-via provenance propagate through all chains as required fields in every audit-log VC (S-152). Langfuse trace IDs (S-021) are threaded through all edges. Cross-agent calls are visible in the Dashboard Intel chain view with per-hop latency and token spend.

## Key files
- `conductor/orchestrator/agents/agent_spec.py` (networking extension)
