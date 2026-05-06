---
id: S-117
title: "Speculative decoding with MTP"
domain: infra
status: research
priority: P2
effort: ""
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-117: Speculative decoding (MTP)

## Problem
Single-token generation is bottlenecked by memory bandwidth. Speculative decoding with Multi-Token Prediction can 2-3× throughput with same quality.

## Solution
Use a small draft model to generate candidate tokens; main model verifies in parallel. Qwen3.5 supports MTP natively.

## Acceptance Criteria (if pursued)
- [ ] Baseline vs speculative tok/s comparison on P40
- [ ] No quality regression (perplexity within 5% of non-speculative)
- [ ] Latency improvement on typical conductor task prompts
