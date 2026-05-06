---
id: S-119
title: "BF16 source weights for proper requantization"
domain: infra
status: draft
priority: P2
effort: ""
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-119: BF16 source weight requantization

## Problem
Current GGUF quants derived from already-quantized weights lose quality. BF16 source → fresh imatrix quant produces better results at same file size.

## Solution
Download BF16 source weights (Qwen3.5-35B). Run imatrix calibration dataset. Produce Q4_K_M and Q3_K_XL from source.

## Acceptance Criteria
- [ ] BF16 weights downloaded to `/vmpool/conductor-models/`
- [ ] Perplexity of fresh quant ≤ original quant at same quantization level
- [ ] Old GGUF files replaced after validation
