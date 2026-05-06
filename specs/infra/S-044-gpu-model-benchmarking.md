---
id: S-044
title: "GPU recovery + model benchmarking (Qwen3.5-35B-A3B)"
domain: infra
status: done
priority: P1
effort: ""
created: 2026-02-25
completed: 2026-02-25
owner: conductor
commits: [259bf0b]
---

# S-044: GPU recovery + model benchmarking

Resolved Xid 79 GPU error. Built `moe_profiler.py` with thermal circuit breaker. Benchmarked Q3_K_M / UD-Q3_K_XL / IQ3_M quants. Downloaded Qwen3.5-35B-A3B (19GB). Implemented threshold-based adaptive routing based on results.
