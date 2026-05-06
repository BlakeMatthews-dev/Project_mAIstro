---
id: S-145
title: "Hyperagent Graph Runtime — the conductor is a self-improving graph of AgentSpec nodes"
domain: conductor
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-145: Hyperagent Graph Runtime

## Problem

The spec tree describes many individual agents (S-002 spawner, S-005 factory, S-038 Skill Forge, S-040 build agents, S-026 Red Team, etc.) and many subsystems (S-022 Bouncer, S-007 intent classifier, S-032 episodic memory). What it does not describe is **the runtime that hosts them all as a single coherent graph.**

Without this meta-spec, four problems compound:

1. **No shared mental model.** Each agent spec stands alone. Readers have to assemble the runtime contract by induction across 40+ specs.
2. **Self-improvement is implicit.** Red/Blue (S-026), Tournament Arena (S-027), Skill Forge (S-038), Skill Evolution (S-112), Phantom (S-030) all *modify the graph* over time, but no document enumerates which subsystems are allowed to mutate which graph state.
3. **Importing external agents is hand-wavy.** "OpenClaw can be a node" / "Claude SDK agent can be a node" / "LangGraph chain can be a node" needs a contract, not a claim.
4. **Observability is fragmented.** Langfuse traces (S-021), git-tracked memory (S-033), dashboard Intel (S-016), audit-log VCs (S-152) all observe pieces of the graph; nothing names the *graph itself* as the thing being observed.

The positioning frame is also at stake: *"OpenClaw is one agent. Maistro orchestrates a graph of them."* That claim only lands if the graph is a real, named runtime primitive.

## Solution

Define the conductor as a **Hyperagent Graph Runtime** with five primitives:

1. **Nodes** — each `AgentSpec` is a node
2. **Edges** — handoff contracts between nodes
3. **Graph state** — traces, memory tiers, capability envelopes, audit log
4. **Self-improvement subsystems** — the explicit set of things allowed to mutate the graph
5. **Import / adapter contract** — what an external agent must implement to be a node

No new code is required by this spec; it names what already exists and locks the contracts.

### 1. Nodes

Every agent invocation in the runtime is a node defined by its `AgentSpec` (S-002, S-005). The AgentSpec is:

- **Immutable for the duration of the turn.** Constructed by code paths the operator controls; never mutated mid-turn.
- **Typed.** Role, model tier, tool whitelist, token budget, tool-call cap, trace ID, owning user_id are all required fields.
- **Identity-bound.** Every node carries the `did:web:<conductor>` of the conductor that constructed it (S-152), and the user_id of the owning user (S-010).
- **Capability-scoped.** The tool whitelist is the *only* set of tools the node may invoke. CONVERSATION role = empty whitelist (S-004). ARTIFACT = file_ops only (S-003). Heartbeat = extended cap (S-105). Etc.

Types of nodes (the Medley plugin types from S-037 are the same types the runtime hosts):

| Type | Description | Construction path |
|---|---|---|
| **role** | Built-in roles (CONVERSATION, ARTIFACT, etc.) | Intent classifier (S-007) → spawner (S-002) |
| **recipe** | Named recipe with Thompson-sampled prompt variants (S-005) | Recipe registry → factory |
| **skill** | A `SKILL.md` plugin invocation (S-035) | Plugin loader → capability-scoped node |
| **forged** | An autonomously-generated skill (S-038) | Skill Forge → Phantom (S-030) → trust-tier promotion → node |
| **imported** | An external agent (Claude SDK, LangGraph, CrewAI, etc.) | Adapter (§5) → wrapped AgentSpec |
| **graph** | A multi-agent subgraph imported as a unit (e.g. `builders-graph` = S-040 quartet) | Adapter → each contained agent gets its own AgentSpec |

### 2. Edges

Edges are handoff contracts. They are not separate runtime objects — they are encoded in:

- **Intent classifier output** (S-007) — "this prompt routes to ARTIFACT," "this routes to a skill named X"
- **Agent-to-agent networking** (S-115) — explicit handoff between nodes
- **Bouncer pre-edge filter** (S-022) — every incoming edge passes through the Bouncer before reaching its target node; rejected edges never produce a node invocation
- **Federation handshake** (S-156) — cross-conductor edges, paid via Lightning when both sides have it, otherwise DID/VC + substrate (S-152, S-153)

Key property: **no edge bypasses the Bouncer.** All inputs to all nodes — user prompts, agent-to-agent payloads, federation messages, tool args — pass through Bouncer screening (S-022, extended in S-151 for crypto operations) before reaching the target node.

### 3. Graph state

Three kinds of state, each owned by a different subsystem:

| State | Owner | Mutability |
|---|---|---|
| **Per-turn state** (current node, tool-call ledger, in-flight prompt) | Spawner (S-002) | Mutable during the turn, frozen at end |
| **Per-session state** (session_id, user_id, working memory) | Memory layer 0–1 (S-032) | Mutable during the session |
| **Long-term state** (episodic tiers 4–7, recipe ELO scores, trust tiers, Bouncer pattern library) | Memory + Tournament + Skill Evolution + Bouncer Red/Blue (various) | Mutable only by self-improvement subsystems (§4) with audit-logged provenance (S-033, S-152) |

All long-term state mutations are git-tracked (S-033) and produce a Verifiable Credential (S-152) in the audit log. "Why did this happen?" has a structured answer that survives any one node's death.

### 4. Self-improvement subsystems (the explicit list)

These are the subsystems allowed to mutate long-term graph state. **The list is closed.** Adding a new self-improvement subsystem is a spec change, not a code change.

| Subsystem | What it mutates | Gate before merge |
|---|---|---|
| **Red/Blue** (S-026) | Bouncer pattern library | Human review on each promoted pattern |
| **Tournament Arena** (S-027) | Recipe ELO scores; node trust tier nominations | Phantom (S-030) for skills; admin signature for trust promotions |
| **Phantom Execution** (S-030) | Trust tier of skills (untrusted → shadow → trusted) | After N successful sandboxed runs + admin signature for trusted tier |
| **Skill Forge** (S-038) | Adds new skill nodes to the graph | Born untrusted; must pass Phantom; admin signature to promote |
| **Skill Evolution** (S-112) | Removes weak skills from the graph; promotes strong ones to featured | Weekly run + human review of removal candidates |
| **Memory consolidation / Dream Loop** (S-025) | Promotes working memory to long-term tiers; prunes low-confidence entries | Confidence thresholds; git-tracked; reversible |
| **Confidence decay** (S-107, draft) | Lowers confidence on stale learnings | Time-driven; reversible |
| **Federation trust VC issuance** (S-152, S-156) | Adds peer conductors as trusted nodes | Admin signature on each issued VC |

No other code path may mutate long-term graph state. A PR that adds a new mutation surface must add a new spec to this table and justify it.

### 5. Import / adapter contract

An external agent becomes a node in this runtime by implementing one of two adapter shapes.

#### Shape A: prompt-in / response-out (most agents)

```python
class ImportedAgent:
    def respond(self, prompt: str, context: AgentContext) -> AgentResponse: ...
```

Where:
- `prompt`: the user-facing input (already Bouncer-screened)
- `context`: read-only graph state the node may consume (memory snapshot, identity, available tools)
- `AgentResponse`: structured output (text + optional tool calls + optional sub-agent spawn requests)

Adapters for: Claude Agent SDK, OpenAI Assistants threads, Anthropic Messages API, OpenAI Responses API, LangGraph chains, vanilla LiteLLM-routed chat, etc. Each adapter is a Medley plugin (S-037) of type `agent`.

#### Shape B: subgraph (multi-agent)

```python
class ImportedGraph:
    def nodes(self) -> list[AgentSpec]: ...
    def edges(self) -> list[EdgeSpec]: ...
    def respond(self, prompt: str, context: AgentContext) -> AgentResponse: ...
```

Multi-agent imports (CrewAI crews, LangGraph multi-node graphs, the Maistro `builders-graph` from S-040 used as a unit) declare their internal nodes and edges. The host runtime sees the subgraph as one logical node from the outside but enforces the runtime contract (Bouncer pre-edge, capability scoping, audit logging) on every internal edge as well. Each contained agent gets its own AgentSpec.

Imported nodes are not exempt from any runtime invariant. They run inside the same Bouncer/capability-envelope/audit-log machinery as native nodes. **OpenClaw can run inside Maistro this way** — wrapped in an `ImportedAgent` adapter, with a CONVERSATION-shaped capability envelope and the Bouncer screening every input. The OpenClaw user keeps using OpenClaw; they just run it inside Maistro now.

## Acceptance Criteria

- [ ] `AgentSpec` is named in the codebase as the canonical node type; no other type fills the role
- [ ] All node invocations pass through the Bouncer at every incoming edge — verified by audit log
- [ ] All long-term graph state mutations are owned by exactly one subsystem from the §4 list, enforced in code review
- [ ] Adapter contract (§5) has at least three working implementations: Claude SDK, LiteLLM-routed plain chat, and a Medley-imported skill
- [ ] An external multi-agent system (LangGraph or CrewAI) can be imported as a Shape-B subgraph with no Maistro core code changes
- [ ] Dashboard Intel tab (S-016) renders the graph: nodes, recent edges, recent self-improvement events, with replay
- [ ] Self-improvement subsystem registry is enumerated in code (one place, not scattered) and matches the table in §4
- [ ] Test: a malicious imported agent cannot escape its capability envelope (verified by adversarial test)

## Implementation Notes

- **No new runtime, just a name.** The graph runtime is what `agent_factory.py`, `spawner.py`, `intent_router.py`, the memory layers, and the Bouncer already collectively are. This spec names them, locks their contracts, and refuses additions that don't fit.
- **Adapter implementations live in `~/.conductor/medley/agent-adapters/`.** Each adapter is a Medley plugin of type `agent`. Adapters for popular frameworks (Claude SDK, OpenAI Assistants, LangGraph, CrewAI, AutoGen) are first-party.
- **The graph visualizer in the dashboard (S-016)** uses Langfuse trace IDs to render the graph for any time window. Self-improvement events surface as annotated edges.
- **Cross-conductor edges (S-156 federation)** are first-class graph edges with the same Bouncer / VC / capability-envelope treatment as same-conductor edges.
- **No edges without a node target.** A federation message that arrives without a target node spec ("unknown intent") is rejected at the Bouncer; it cannot create a phantom invocation.

## Verification

- Run the conductor for an hour with mixed traffic (chat, voice, federation, heartbeat) → every invocation visible in the Intel-tab graph view with correct node type and edge provenance.
- Run Skill Forge → verify the new skill appears as a node, trust tier `untrusted`; verify Phantom execution promotes it to `shadow`; verify admin signature promotes to `trusted`.
- Run Red Team in sandbox → verify a confirmed bypass produces a Bouncer pattern proposal → admin reviews and merges → graph state mutation visible in the audit log as a signed VC.
- Import an OpenClaw skill via Medley adapter → verify it runs as a node with the empty tool whitelist (CONVERSATION-shaped) until explicitly scoped wider → verify the Bouncer screens its inputs and outputs.
- Adversarial test: imported agent attempts to call a tool not in its whitelist → attempt is refused at the capability envelope, not at the tool implementation.
- Long-term: enumerate every code path that mutates long-term graph state; verify each maps to exactly one subsystem in the §4 list.
