---
id: S-112
title: "Skill Evolution — natural selection for tools"
domain: tools
status: draft
priority: P2
effort: "~300 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-112: Skill Evolution

## Problem
Skills accumulate without pruning. Weak, rarely-used skills waste scanner time and pollute recommendations.

## Solution
Track usage count and success rate per skill. Skills below threshold for 30 days are deprecated. High-performing skills get promoted to a "featured" tier.

## Acceptance Criteria
- [ ] Usage + success rate tracked per skill invocation
- [ ] Weekly pruning run identifies candidates for deprecation
- [ ] Human-review gate before actual deletion
- [ ] Top-performing skills surfaced in ClawHub recommendations
