---
id: SPEC-007
title: "Collective Unconscious — federated wisdom sharing"
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
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# S-114: Collective Unconscious

## Problem
Learnings are siloed per conductor instance. Two conductors on different machines can't share discovered patterns.

## Solution
Cross-tenant T7 wisdom tier. High-confidence learnings (score > 0.9) optionally shared to a federated pool. Pulled during dream loop consolidation.

## Open questions

- **Privacy (OPEN):** which memory tiers and content classes are safe to share? Working assumption: only T7 LORE entries (high-abstraction, non-user-identifying) with explicit per-entry opt-in. No user names, locations, financial data, or personally identifying patterns. Content-hash deduplication to prevent re-identification via shared content. Needs a dedicated policy spec before implementation.

- **Trust (PARTIALLY RESOLVED → S-152, S-156):** cross-instance learnings would arrive as Verifiable Credentials signed by the peer conductor's DID (S-152). The existing federation trust VC model (S-156) already handles peer identity validation. The open question is whether a federation trust VC covers wisdom-tier sharing, or whether a new VC type is needed specifically for memory sharing with narrower content-class constraints.

- **Transport (PARTIALLY RESOLVED → S-156):** S-156 Lightning federation provides p2p transport between conductors without a central broker. Wisdom-tier sharing would piggyback on the existing federation channel, with learnings as VC payloads over DID + substrate (S-153). Central broker is not required. The remaining open question is whether wisdom sharing warrants its own federation message type or can reuse the existing forwarded-message type.

## Key files
- `conductor/orchestrator/agents/experimental/` (new)
