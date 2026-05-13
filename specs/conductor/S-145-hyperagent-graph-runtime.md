---
id: SPEC-015
title: "Hyperagent Graph Runtime — the conductor is a self-improving graph of AgentSpec nodes"
repo: Project_mAIstro
kind: spec
status: Proposed
created: 2026-04-25
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

# S-145: Hyperagent Graph Runtime

## Problem

The spec tree describes many individual agents (S-002 spawner, S-005 factory, S-038 Skill Forge, S-040 build agents, S-026 Red Team, etc.) and many subsystems (S-022 Bouncer, S-007 intent classifier, S-032 episodic memory). What it does not describe is **the runtime that hosts them all as a single coherent graph.**

Without this meta-spec, four problems compound:

1. **No shared mental model.** Each agent spec stands alone. Readers have to assemble the runtime contract by induction across 40+ specs.
2. **Self-improvement is implicit.** Red/Blue (S-026), Tournament Arena (S-027), Skill Forge (S-038), Skill Evolution (S-112), Phantom (S-030) all *modify the graph* over time, but no document enumerates which subsystems are allowed to mutate which graph state.
3. **The universal calling contract is hand-wavy.** "Anything can be a node" needs a contract, not a claim. That "anything" includes other Conductors, OpenClaw, Claude Code, Anthropic ADK, AutoGen / Microsoft Agent Framework, custom agents, **and humans on a channel**.
4. **Observability is fragmented.** Langfuse traces (S-021), git-tracked memory (S-033), dashboard Intel (S-016), audit-log VCs (S-152) all observe pieces of the graph; nothing names the *graph itself* as the thing being observed.

The positioning frame is at stake: *"Conductor orchestrates your agent swarm — no matter the shape. Wraps any agent in our security and permissions boundaries, whether it's a model, a framework, another conductor, or a person."* That claim only lands if the graph is a real, named runtime primitive with a universal node contract.

## Solution

Define the conductor as a **Hyperagent Graph Runtime** with five primitives:

1. **Nodes** — each `AgentSpec` is a node
2. **Edges** — handoff contracts between nodes
3. **Graph state** — traces, memory tiers, capability envelopes, audit log
4. **Self-improvement subsystems** — the explicit set of things allowed to mutate the graph
5. **Universal import / adapter contract** — what an external responder must implement to be a node

No new code is required by this spec; it names what already exists and locks the contracts.

### 1. Nodes

Every agent invocation in the runtime is a node defined by its `AgentSpec` (S-002, S-005). The AgentSpec is:

- **Immutable for the duration of the turn.** Constructed by code paths the operator controls; never mutated mid-turn.
- **Typed.** Role, model tier, tool whitelist, token budget, tool-call cap, trace ID, owning user_id are all required fields.
- **Identity-bound.** Every node carries the `did:web:<conductor>` of the conductor that constructed it (S-152), and the **initiator identity** for the chain (§6).
- **Capability-scoped.** The tool whitelist is the *only* set of tools the node may invoke. CONVERSATION role = empty whitelist (S-004). ARTIFACT = file_ops only (S-003). Heartbeat = extended cap (S-105). Etc.

Types of nodes (the Medley plugin types from S-037 are the same types the runtime hosts):

| Type | Description | Construction path |
|---|---|---|
| **role** | Built-in roles (CONVERSATION, ARTIFACT, etc.) | Intent classifier (S-007) → spawner (S-002) |
| **recipe** | Named recipe with Thompson-sampled prompt variants (S-005) | Recipe registry → factory |
| **skill** | A `SKILL.md` plugin invocation (S-035) | Plugin loader → capability-scoped node |
| **forged** | An autonomously-generated skill (S-038) | Skill Forge → Phantom (S-030) → trust-tier promotion → node |
| **imported-agent** | An external agent (Claude SDK, AutoGen, OpenClaw, custom, etc.) | Shape A adapter (§5) |
| **imported-graph** | A multi-agent subgraph imported as a unit (CrewAI crew, LangGraph multi-node, the Maistro `builders-graph` from S-040) | Shape B adapter (§5) |
| **conductor-as-node** | Another Maistro Conductor invoked as a Shape A node (see S-157 for composition rules) | Shape A adapter; the canonical recursive-composition case |
| **human** | A person reachable on a channel (Teams / Slack / email / SMS / their own conductor / the conductor app) | Shape A via channel adapter; see S-158 for the human-delegation pattern |

### 2. Edges

Edges are handoff contracts. They are not separate runtime objects — they are encoded in:

- **Intent classifier output** (S-007) — "this prompt routes to ARTIFACT," "this routes to a skill named X"
- **Agent-to-agent networking** (S-115) — explicit handoff between nodes
- **Bouncer pre-edge filter** (S-022) — every incoming edge passes through the Bouncer before reaching its target node; rejected edges never produce a node invocation
- **Federation handshake** (S-156) — cross-conductor edges, paid via Lightning when both sides have it, otherwise DID/VC + substrate (S-152, S-153)

Key property: **no edge bypasses the Bouncer.** All inputs to all nodes — user prompts, agent-to-agent payloads, federation messages, tool args, **human responses returning from delegation** — pass through Bouncer screening (S-022, extended in S-151 for crypto operations) before reaching the target node. A human's response is *untrusted input* and must be screened just like any other input.

### 3. Graph state

Three kinds of state, each owned by a different subsystem:

| State | Owner | Mutability |
|---|---|---|
| **Per-turn state** (current node, tool-call ledger, in-flight prompt) | Spawner (S-002) | Mutable during the turn, frozen at end |
| **Per-session state** (session_id, user_id, working memory) | Memory layer 0–1 (S-032) | Mutable during the session |
| **Long-term state** (episodic tiers 4–7, recipe ELO scores, trust tiers, Bouncer pattern library, **per-human prompt-variant scores**) | Memory + Tournament + Skill Evolution + Bouncer Red/Blue + per-human optimization (various) | Mutable only by self-improvement subsystems (§4) with audit-logged provenance (S-033, S-152) |

All long-term state mutations are git-tracked (S-033) and produce a Verifiable Credential (S-152) in the audit log. "Why did this happen?" has a structured answer that survives any one node's death.

### 4. Self-improvement subsystems (the explicit list)

These are the subsystems allowed to mutate long-term graph state. **The list is closed.** Adding a new self-improvement subsystem is a spec change, not a code change.

| Subsystem | What it mutates | Gate before merge |
|---|---|---|
| **Red/Blue** (S-026) | Bouncer pattern library | Human review on each promoted pattern |
| **Tournament Arena** (S-027) | Recipe ELO scores; node trust tier nominations; **per-human prompt-variant scores (S-158)** | Phantom (S-030) for skills; admin signature for trust promotions; opt-in for human-node optimization |
| **Phantom Execution** (S-030) | Trust tier of skills (untrusted → shadow → trusted) | After N successful sandboxed runs + admin signature for trusted tier |
| **Skill Forge** (S-038) | Adds new skill nodes to the graph | Born untrusted; must pass Phantom; admin signature to promote |
| **Skill Evolution** (S-112) | Removes weak skills from the graph; promotes strong ones to featured | Weekly run + human review of removal candidates |
| **Memory consolidation / Dream Loop** (S-025) | Promotes working memory to long-term tiers; prunes low-confidence entries | Confidence thresholds; git-tracked; reversible |
| **Confidence decay** (S-107, draft) | Lowers confidence on stale learnings | Time-driven; reversible |
| **Federation trust VC issuance** (S-152, S-156) | Adds peer conductors as trusted nodes | Admin signature on each issued VC |

No other code path may mutate long-term graph state. A PR that adds a new mutation surface must add a new spec to this table and justify it.

### 5. Universal import / adapter contract

Shape A is **the universal external-responder contract.** Anything that takes a prompt and emits a response can be wrapped as a node — another Conductor, OpenClaw, Claude Code, Anthropic ADK, AutoGen / Microsoft Agent Framework, a Claude SDK project, a LangGraph chain, your custom Python agent, **a human on a channel**. Compatibility with specific frameworks is a *side effect* of the universal contract, not the design target.

#### Shape A: prompt-in / response-out (the universal contract)

```python
class ImportedNode:
    def respond(self, prompt: str, context: NodeContext) -> NodeResponse: ...
```

Where:
- `prompt`: the user-facing input (already Bouncer-screened on entry; will be Bouncer-screened again on the response coming back)
- `context`: read-only graph state the node may consume (memory snapshot, initiator identity per §6, available tools)
- `NodeResponse`: structured output (text + optional tool calls + optional sub-node spawn requests)

Adapters are Medley plugins of type `agent`. First-party adapters ship for: Claude Agent SDK, Anthropic ADK, OpenAI Assistants threads, OpenAI Responses API, LangGraph chains, AutoGen / Microsoft Agent Framework, Claude Code (subprocess + protocol), OpenClaw (gateway-protocol bridge), Maistro Conductor (recursive composition; see S-157), **human-on-channel** (see S-158).

The last one is the deepest. A human node's `respond` doesn't return synchronously — it dispatches to the channel adapter, the reactor (S-143) waits on "channel response received," Bouncer screens the response, the wrapped `respond` returns. From the orchestration layer's perspective, calling Claude and calling Jenny in HR are structurally identical; only latency and channel differ.

#### Shape B: subgraph (multi-agent)

```python
class ImportedGraph:
    def nodes(self) -> list[AgentSpec]: ...
    def edges(self) -> list[EdgeSpec]: ...
    def respond(self, prompt: str, context: NodeContext) -> NodeResponse: ...
```

Multi-agent imports (CrewAI crews, LangGraph multi-node graphs, the Maistro `builders-graph` from S-040 used as a unit) declare their internal nodes and edges. The host runtime sees the subgraph as one logical node from the outside but enforces the runtime contract (Bouncer pre-edge, capability scoping, audit logging) on every internal edge as well. Each contained agent gets its own AgentSpec.

**No node is exempt from any runtime invariant.** Imported nodes — framework agents, other conductors, humans — run inside the same Bouncer / capability-envelope / audit-log machinery as native nodes. *That's* the value the universal contract creates: any responder, with our security boundaries wrapped around it.

### 6. Initiator identity & recursion budgets

Every chain has a single **initiator** identity that propagates through the entire chain:

- **Direct invocation:** Jimmy types a prompt; initiator = `jimmy@conductor-a`.
- **Scheduled invocation:** Jimmy created a Time Capsule reminder last week; the reactor (S-143) fires it; initiator = `jimmy@conductor-a` with `initiator-context: scheduled-by=jimmy, event-id=...`.
- **Conductor-internal maintenance:** vault rebuild, WAL checkpoint; initiator = the conductor's own DID acting as a synthetic `system` identity. This is the only non-user initiator and is reserved for maintenance not acting on any human's behalf.

The chain also carries an **acting-via** provenance (the conductors / nodes the request has flowed through) for forensic replay; this is metadata, not a permission decision.

**Each conductor in the chain enforces the initiator's envelope as that conductor sees it.** If Jimmy isn't in conductor X's `users.toml`, X refuses. The intersection of envelopes across the chain applies; **adding wraps tightens security, not loosens it.**

**Recursion is allowed.** A wraps B wraps A is valid graph composition — A might delegate work to B, and B's task might legitimately need a sub-task on A. The runtime tracks per-chain budgets:

- **Depth budget** (default 16) — max wrap depth.
- **Latency budget** (default 60s) — cumulative chain wall-clock.
- **Token-spend budget** (default 1M tokens) — cumulative LLM tokens across the chain.

When a budget is exhausted, the conductor whose budget it crossed fails the operation with a structured error.

**Cross-conductor token-spend tracking:** when Conductor A calls Conductor B via federation (S-156), B's response includes a `tokens_consumed` field reporting the LLM tokens B charged for that turn (including any nested calls B made). A debits this amount from the chain's token-spend budget before the next node runs. When a peer omits `tokens_consumed` (older protocol or non-Maistro responder), A applies a conservative estimate: `ceil(len(response_text) / 4)` tokens. Per-hop spend is visible in the Dashboard Intel chain view, so operators can identify which nodes in a deep chain are burning budget.

**Recursion is an inefficiency smell, not a safety failure.** Operators get observability ("this chain went 6 deep, took 14s") rather than the runtime guessing whether their composition is "valid." Budgets are tunable per-conductor and per-skill.

Deeper treatment of recursive composition (audit-log nesting, `parentVC` references, family / specialization / privacy-partitioning patterns) lives in **S-157: Conductor-as-node composition**.

## Acceptance Criteria

- [ ] `AgentSpec` is named in the codebase as the canonical node type; no other type fills the role
- [ ] All node invocations pass through the Bouncer at every incoming edge — verified by audit log
- [ ] All long-term graph state mutations are owned by exactly one subsystem from the §4 list, enforced in code review
- [ ] Shape A has at least four working implementations: Claude SDK, LiteLLM-routed plain chat, a Medley-imported skill, **and a human-on-channel node (S-158)**
- [ ] An external multi-agent system (LangGraph or CrewAI) can be imported as a Shape-B subgraph with no Maistro core code changes
- [ ] Dashboard Intel tab (S-016) renders the graph: nodes, recent edges, recent self-improvement events, with replay
- [ ] Self-improvement subsystem registry is enumerated in code (one place, not scattered) and matches the table in §4
- [ ] Initiator identity propagates correctly through chains; verified by audit-log inspection (every VC in a chain has the same `initiator` field)
- [ ] Recursion: a deliberately recursive A→B→A composition completes within budgets; an unbounded version fails at budget exhaustion with a structured error, not at handshake
- [ ] Test: a malicious imported agent (or a malicious human response) cannot escape its capability envelope (verified by adversarial test)
- [ ] Cross-conductor token spend: B's federation response includes `tokens_consumed`; A debits the amount against the chain budget before proceeding; missing field triggers the conservative `ceil(len(response) / 4)` estimate; per-hop spend visible in the chain audit log

## Implementation Notes

- **No new runtime, just a name.** The graph runtime is what `agent_factory.py`, `spawner.py`, `intent_router.py`, the memory layers, and the Bouncer already collectively are. This spec names them, locks their contracts, and refuses additions that don't fit.
- **Adapter implementations live in `~/.conductor/medley/agent-adapters/`.** Each adapter is a Medley plugin of type `agent`.
- **The graph visualizer (S-159 Node + Graph Designer)** uses Langfuse trace IDs to render the graph for any time window. Self-improvement events surface as annotated edges. Operators design + edit graphs through the same UI.
- **Cross-conductor edges (S-156 federation)** are first-class graph edges with the same Bouncer / VC / capability-envelope treatment as same-conductor edges.
- **No edges without a node target.** A federation message that arrives without a target node spec ("unknown intent") is rejected at the Bouncer; it cannot create a phantom invocation.
- **Initiator identity is checked at every conductor boundary.** A request crossing into another conductor whose `users.toml` doesn't recognize the initiator is refused.
- **Per-chain budgets are enforced at the conductor whose resource is being consumed.** Token budget enforced at the conductor making the LLM call; latency budget at the wrapping conductor; depth budget at every layer.
- **`tokens_consumed` in federation responses** is a required field in the Maistro federation protocol (S-156). The conservative estimate (`ceil(len / 4)`) applies to any responder that does not include the field; this is an overestimate by design, incentivizing peers to report accurately.

## Verification

- Run the conductor for an hour with mixed traffic (chat, voice, federation, heartbeat, **human-delegation**) → every invocation visible in the Intel-tab graph view with correct node type and edge provenance.
- Run Skill Forge → verify the new skill appears as a node, trust tier `untrusted`; verify Phantom execution promotes it to `shadow`; verify admin signature promotes to `trusted`.
- Run Red Team in sandbox → verify a confirmed bypass produces a Bouncer pattern proposal → admin reviews and merges → graph state mutation visible in the audit log as a signed VC.
- Import an OpenClaw skill via Medley adapter → verify it runs as a node with the empty tool whitelist (CONVERSATION-shaped) until explicitly scoped wider → verify the Bouncer screens its inputs and outputs.
- Wrap an AutoGen multi-agent system as Shape B; have it call Claude Code as Shape A inside; have one of the Claude Code calls delegate to a human via S-158 — verify the chain completes, every layer's audit log records the appropriate VC with the same `initiator` (the original user), and total chain latency is within budget.
- Adversarial test: imported agent attempts to call a tool not in its whitelist → attempt is refused at the capability envelope, not at the tool implementation.
- Recursion test: deliberate A→B→C→A chain completes within depth budget 16; deliberate unbounded loop hits the budget and returns a structured error from the conductor whose budget was crossed.
- Token-spend tracking test: conductor A calls federation peer B for a task; verify B's response carries `tokens_consumed`; verify A's chain-budget ledger reflects B's cost; configure a federation peer that omits the field and verify A applies the conservative estimate.
- Long-term: enumerate every code path that mutates long-term graph state; verify each maps to exactly one subsystem in the §4 list.
