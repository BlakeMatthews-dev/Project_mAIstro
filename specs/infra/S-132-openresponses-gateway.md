---
id: S-132
title: "OpenResponses Gateway — /v1/responses endpoint"
domain: infra
status: draft
priority: P2
effort: ""
created: 2026-01-19
completed: ""
owner: conductor
commits: []
---

# S-132: OpenResponses Gateway Integration

_Promoted from `docs/experiments/plans/openresponses-gateway.md`_

## Context

Gateway currently exposes `/v1/chat/completions` (OpenAI-compatible). OpenResponses is an open inference standard designed for agentic workflows with item-based inputs and semantic streaming events. Goal: add `/v1/responses` and deprecate chat completions cleanly.

## Goals

- Add `/v1/responses` that adheres to OpenResponses semantics
- Keep Chat Completions as a compatibility layer (opt-in via config)
- Standardize validation with isolated Zod schemas

## Non-goals

- Full OpenResponses feature parity in Phase 1 (no images, files, hosted tools)
- Changing existing `/v1/chat/completions` behavior during Phase 1

## Phase 1 Support Subset

- `input` as string or `ItemParam[]` with message roles + `function_call_output`
- Single assistant message response with `output_text` content
- Streaming: minimum viable SSE event sequence → `[DONE]`
- Reject unsupported content parts (image/file) with `invalid_request_error`

## Acceptance Criteria

- [ ] `POST /v1/responses` responds to non-stream requests with correct `ResponseResource` shape
- [ ] Streaming: correct event ordering + terminal `[DONE]`
- [ ] Auth required (same as chat completions)
- [ ] `gateway.http.endpoints.chatCompletions.enabled` independent toggle
- [ ] `openai-http.e2e.test.ts` unchanged

## Key files
- `src/gateway/open-responses.schema.ts` (new — Zod schemas only)
- `src/gateway/openresponses-http.ts` (new)
- `src/gateway/openai-http.ts` (add legacy warning on startup)
