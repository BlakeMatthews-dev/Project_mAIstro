---
id: SPEC-020
title: "Node Designer + Graph Designer UI — visual composition of the hyperagent graph"
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
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
---

# S-159: Node Designer + Graph Designer UI

## Problem

The Hyperagent Graph Runtime (S-145) defines nodes and edges as the runtime's primary primitives. Today, an operator who wants to add a node — a new skill, an imported agent, another conductor, a human delegation target like Jenny in HR — has to edit `~/.conductor/users.toml`, `~/.conductor/medley/`, and conductor source. That's the *power-user* path; we keep it. We also need a **visual designer** in the Console (S-016) so non-engineering operators can compose graphs without touching code.

The two coupled UIs:

- **Node Designer** — add / edit a single node: id, type, tools, permissions, channel options, optimization settings.
- **Graph Designer** — visual canvas of nodes + edges; drag-drop; routing rules; real-time traffic view.

Without these, the graph runtime is real but invisible. The Designer turns *"Conductor orchestrates your agent swarm"* from a backend claim into something the operator can actually see and shape.

## Solution

Two coupled views in the Console (S-016 + S-139), sharing the same web UI codebase. Every change is admin-signed (S-142) and produces a VC in the audit log (S-152).

### Node Designer

A form view for one node, reachable from the Graph Designer canvas (click any node → opens the editor) or from a `/nodes/new` route.

#### Required fields (every node type)

| Field | Type | Notes |
|---|---|---|
| **id** | string | Unique within the graph; used as a stable identifier in audit logs and edges. Suggestion-generated from `type + name + suffix`. |
| **type** | enum | `role` / `recipe` / `skill` / `forged` / `imported-agent` / `imported-graph` / `conductor-as-node` / `human` (S-145 §1 taxonomy) |
| **name** | string | Display name ("Jenny in HR", "Build Agents", "Research Specialist") |
| **description** | string | Operator-facing context |
| **intents** | string[] | Which classified intents may route here (S-007 intent classifier) |
| **user_scope** | string[] | Which initiator identities may delegate to this node (default: all users in `users.toml`) |
| **trust_tier** | enum | `untrusted` / `shadow` / `trusted` / `featured` (S-035 trust tiers) |

#### Type-specific fields

**Tools available + permissions** (capability envelope, S-002–S-005):

```
Tool whitelist:
  [✓] file_ops.read         (any tool below trust threshold N)
  [✓] file_ops.write
  [ ] file_ops.delete         (admin-elevation required, S-142)
  [✓] http.get
  [ ] http.post               (admin-signed policy required)
  [ ] shell                   (admin-only)
  [ ] crypto.sign             (admin-only, S-151)
```

The form refuses combinations that would violate invariants: a `human` node with `shell` permission is rejected (humans don't run shell commands); a `CONVERSATION`-shaped role with any tool other than empty is rejected (S-004 invariant).

**Communication channels** (for `human` nodes per S-158, also for `conductor-as-node` for routing preference):

```
Channels (priority order, drag to reorder):
  1. [Teams]      @jenny.smith            hours: weekdays 09–17 PT   urgency: normal, urgent
  2. [Conductor]  did:web:jenny-conductor.her-tailnet.ts.net
                                          hours: any                  urgency: any
  3. [App]        <push subscription>     hours: any                  urgency: any
  4. [Email]      jenny@example.com       hours: any                  urgency: normal
  5. [SMS]        +1-555-0100            hours: weekdays 09–17 PT   urgency: urgent (admin-signed)
  [+ Add channel]
```

Per-channel:
- **Type** dropdown: Teams / Slack / Discord / Telegram / WhatsApp / Signal / Matrix / Email / SMS / Voice / Conductor / Conductor-app / IRC / custom
- **Address** field (channel-specific format)
- **Hours** (cron-style or human-readable)
- **Urgency** allowed
- **Identity attestation** (auto-detected per channel type; S-158 §"Identity attestation per channel")
- **Cost-bearing flag** (SMS, voice; requires admin signature per delegation by default)

**Optimization** (for `human` nodes):

```
[✓] Enable per-human prompt optimization (S-027 + S-158)
    Variant pool seed: [Concise] [Context-heavy] [With-example] [+ Add variant]
    Opt-out keyword: "STOP-LEARN"
    Privacy: [✓] Hash response in public VC for these intents:
             [hr-policy] [benefits] [medical] [+ Add intent]
```

**Resource budgets** (per S-145 §6):

```
Depth budget (max wrap depth):       16
Latency budget (s):                  60
Token budget per chain:               1,000,000
```

**For `imported-agent` / `imported-graph` nodes:**

```
Adapter:    [Claude Code] [Anthropic ADK] [AutoGen] [LangGraph]
            [OpenClaw] [Custom — paste manifest]
Endpoint:   <how to reach the adapter — binary path, HTTP URL, etc.>
Verify:     [Run adapter handshake test]   → ✓ responds correctly
```

#### Validation

Form validates client-side AND server-side. Submission is blocked unless:
- ID is unique (server checks against `users.toml` + node registry).
- Tool whitelist passes invariant checks (no admin-only tools on user-keyed nodes; no shell on human nodes; etc.).
- At least one channel for human nodes.
- Adapter handshake succeeds for imported nodes (forces the operator to verify the bridge works before saving).

#### Submission

Save is admin-signed (S-142). The Console produces a wallet-app push notification (S-150 mode 3) with the structured node-definition diff:

```
┌─ Add node: jenny-hr (human) ──────────────────────────┐
│ Channels:                                            │
│   1. Teams @jenny.smith                              │
│   2. Conductor did:web:jenny-conductor.her-tailnet... │
│   3. App ...                                          │
│   4. Email jenny@example.com                          │
│   5. SMS +1-555-0100 (admin-signed only)              │
│ Tools: (none — human nodes provide responses,         │
│        not actions)                                   │
│ Optimization: enabled, opt-out="STOP-LEARN"           │
│ [ Sign in wallet → ]                                  │
└──────────────────────────────────────────────┘
```

On admin signature, the node is added to the runtime registry, a VC is recorded in the audit log, and the change is reflected on the Graph Designer canvas immediately.

### Graph Designer

A visual canvas showing nodes and edges. React Flow (or equivalent) for the rendering.

#### Layout

```
┌─ Graph: Household Conductor ──────────────────────────────────────┐
│                                                                       │
│    [user input]                                                       │
│         │                                                              │
│         ▼                                                              │
│    ┌───────────┐                                                  │
│    │ Bouncer  │ ───────▶ [reject → SAFETY_VIOLATION]                  │
│    └────┴──────┘                                                  │
│         │                                                              │
│         ▼                                                              │
│    ┌───────────────┐    ┌───────────┐                              │
│    │ Intent       │ ───▶ │ ARTIFACT  │    → file_ops.write          │
│    │ Classifier   │    └───────────┘                              │
│    └────┴──────────┘    ┌─────────────────┐                       │
│         │ hr-policy ──▶ │ jenny-hr (human) │ ─→ [returns answer]    │
│         │             └─────────────────┘                       │
│         │             ┌─────────────────┐                       │
│         └─ code ──────▶ │ builders-graph  │ ─→ [code output]      │
│                       └─────────────────┘                       │
│                                                                       │
│  Live traffic: ●●●●○○○ (last 10 min)                                  │
│  Self-improvement events: 3 in last hour (Bouncer pattern + ELO + ...) │
│                                                                       │
│  [+ Add node]  [Save graph]  [Export]  [Replay last 1h]               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Capabilities

- **Add node:** `+ Add node` button → opens Node Designer in a slide-over.
- **Edit node:** click any node → Node Designer.
- **Add edge:** drag from one node's output port to another's input port; opens an edge-config dialog (intent match? unconditional? fallback?).
- **Delete node / edge:** select + delete; admin-signed; cascade warning if other nodes route to the deleted target.
- **Live traffic:** edges light up as messages flow through them; node borders pulse when invoked. Color-coded by latency (green / yellow / red).
- **Self-improvement annotations:** edges that the Tournament Arena recently optimized show a small "⤴️ variant updated" badge for 24 hours after the change.
- **Replay:** select a time window; the canvas plays back the actual graph traffic at 10× / 100× / 1000× speed using Langfuse trace IDs.
- **Export / import:** YAML serialization of the graph; operators can version-control + share.

#### Trust-tier visualization

Nodes are color-coded by trust tier:

- **Featured** — gold border
- **Trusted** — green border
- **Shadow** — yellow border
- **Untrusted** — red border (always shown; never hidden)
- **Human** — blue border with channel-icon overlay
- **Conductor-as-node** — purple border with the wrapped conductor's instance name

Operator sees at a glance which parts of their graph are doing what kind of work, with what kind of trust.

#### Read-only mode for non-admins

Users (not admin) see the Graph Designer in read-only mode: they can browse, replay traffic from chains they initiated, but cannot edit. Edits require admin signature — same primitive as elsewhere.

### Sharing the Console codebase

Node Designer and Graph Designer are routes in the same Console PWA used by Setup (S-139) and the runtime dashboard (S-016). Three modes:

- **Setup mode** — only the wizard routes are reachable; Designer routes are gated until Step 12 completes.
- **Authenticated runtime mode** — full Designer access for admins, read-only for users (per S-142).
- **Audit mode** — a researcher / auditor with a scoped read-only credential can view the Designer (and replay traffic) without ability to edit.

The components are reusable: the same node-card component renders in the Designer canvas, the Intel tab (S-016), and the audit-log replay viewer.

## Acceptance Criteria

- [ ] Adding a node via Node Designer produces a node visible on the Graph Designer canvas within 1s of admin signature
- [ ] Editing a node via Node Designer updates the canvas live; existing in-flight chains use the prior version (no mid-chain config swap)
- [ ] Channel-priority drag-reorder works on Teams/Slack/email/SMS/Conductor/Conductor-app channel types
- [ ] Form validation refuses invalid combos (admin-only tools on user-keyed nodes; shell on human nodes; CONVERSATION with non-empty whitelist; etc.)
- [ ] Adapter handshake test runs for imported-agent nodes; failure blocks save
- [ ] All Designer changes are admin-signed via wallet-app push (S-150 mode 3) and recorded as VCs in the audit log
- [ ] Graph Designer renders nodes + edges + live traffic for a graph of at least 50 nodes without performance degradation
- [ ] Replay mode plays back actual traffic for an operator-selected time window using Langfuse trace data
- [ ] Trust-tier color coding is consistent: gold (featured) / green (trusted) / yellow (shadow) / red (untrusted) / blue (human) / purple (conductor-as-node)
- [ ] Users in read-only mode can view + replay traffic from their own chains; cannot edit; cannot view chains they didn't initiate
- [ ] Export / import: a graph YAML round-trips through export → import without loss; reproduces an equivalent graph on a fresh conductor
- [ ] Graph import security: an imported graph YAML is validated with the same per-node checks as Node Designer form submission; a YAML specifying admin-only tools (e.g. `shell`) on a user-level node is **rejected** with a validation error naming the violating field; a YAML that sets `trust_tier` to anything other than `untrusted` for a new node is **silently overridden** to `untrusted` (all imported nodes start at `untrusted` regardless of the YAML value); the import flow cannot bypass tool-whitelist invariants enforced by the form
- [ ] CLI parity: every Designer action has a `maistro graph ...` CLI command for headless / scripted use

## Implementation Notes

- **Frontend:** React Flow (or `@xyflow/react`) for the canvas; reuses existing Console components (button, form, modal, slide-over). Same TS codebase as Setup wizard (S-139).
- **Backend:** node + edge state lives in SQLite (S-140) under tables `nodes`, `edges`, and a `graph_history` audit table that tracks every change.
- **Live traffic:** WebSocket subscription to a per-Console event stream sourced from Langfuse traces (S-021). Reactor (S-143) pushes invocation events to subscribed Consoles in <100ms.
- **Replay:** Langfuse traces persisted long enough to support replay (default: 30 days, configurable). Replay reconstructs the canvas animation by stepping through trace events in sequence.
- **Validation library:** Zod schemas shared client + server; same as elsewhere in the Console. Graph import runs the same Zod schema as the Node Designer form — there is no separate import-only validation path.
- **Import trust override:** the import parser strips any `trust_tier` value other than `untrusted` from incoming nodes before validation; the override is logged to the audit trail so operators can see which nodes had their tier downgraded.
- **Adapter handshake:** the adapter's `respond()` is called with a known-safe ping prompt; expected response shape verified. Failures surface a clear error in the form.
- **Concurrency:** two admins editing the same node simultaneously — the second to save sees a structured conflict error with a diff view; standard optimistic-concurrency pattern.
- **Accessibility:** canvas uses standard ARIA + keyboard navigation; node selection / edit available via keyboard for screen-reader users.
- **Internationalization:** UI strings localized; channel-type names + intent names remain in canonical English under the hood (used as identifiers in audit logs).
- **Composes with S-145:** the Designer is the *operator-facing* view of the same graph the runtime executes. Node and edge definitions are authoritative; the Designer is never out-of-sync with the runtime.

## Verification

- Add Jenny via Node Designer with all 5 channels; verify she appears on the canvas; trigger a hr-policy intent; watch the canvas light up the edge to her; simulate her response; verify the chain completes.
- Drag-reorder her channels (Teams → Conductor → App → Email → SMS); verify the saved priority order is reflected in subsequent delegations.
- Attempt to add a `human` node with `shell` permission; verify form rejects with a clear error.
- Add an `imported-agent` node pointing to a fake adapter; verify handshake test fails; verify save is blocked.
- Add 50 nodes and 100 edges; verify canvas renders without lag; verify zoom + pan + select work cleanly.
- Trigger 100 mixed invocations; verify live traffic updates within 100ms p95.
- Select a 1-hour replay window; verify the canvas plays back invocations in correct order at 10× speed.
- Log in as a non-admin user; verify Designer is read-only; verify they can replay only their own chains.
- Export the graph YAML; spin up a fresh conductor; import; verify the reproduced graph is structurally identical (modulo node IDs that include conductor instance name).
- Import security — rejection: craft a YAML with a `role` node claiming `shell` permission; verify import is rejected with a validation error that names the violating field (`tools.shell` on a non-admin node).
- Import security — trust downgrade: craft a YAML with `trust_tier: trusted` on a new node; verify the node imports successfully but its recorded trust tier is `untrusted`; verify the audit log entry notes the override.
- Concurrent edit test: two admin sessions edit the same node; verify the second save shows a conflict diff and requires manual merge.
