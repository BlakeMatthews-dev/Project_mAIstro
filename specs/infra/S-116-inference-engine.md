---
id: S-116
title: "Better inference engine — llama.cpp / vLLM / ExLlamaV2"
domain: infra
status: research
priority: P1
effort: ""
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-116: Better inference engine than Ollama

## Problem
Current Ollama backend: limited throughput control, no KV cache sharing, poor multi-slot management. CONDUCTOR-BUILD.md already specifies ik_llama.cpp as Phase 0 replacement.

## Options
- **ik_llama.cpp** (currently in use): imatrix quants, MoE support, llama-server API
- **mainline llama.cpp**: qwen35moe support (PR #19468), wider community
- **vLLM**: continuous batching, paged attention, production-grade
- **ExLlamaV2**: fastest pure-Python option for single-GPU

## Decision criteria
- tok/s on P40 (Tesla, sm_61)
- qwen35moe support
- KV cache hit rate
- API compatibility with LiteLLM router

## Key files
- `conductor/gateway/` (slot manager would need updating)
- `CONDUCTOR-BUILD.md` (Phase 0 spec)
