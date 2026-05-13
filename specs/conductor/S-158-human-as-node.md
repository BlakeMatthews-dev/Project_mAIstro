---
id: SPEC-019
title: "Human-as-node delegation — channel-routed prompts, identity-attested replies, per-human prompt optimization"
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
layer: Agents
owners:
  - '@BlakeMatthews-dev'
---

# S-158: Human-as-Node Delegation

## Problem

The Hyperagent Graph Runtime (S-145) defines Shape A as the universal contract: anything that takes a prompt and emits a response can be a node. The most under-explored consequence is that **humans are nodes too**.

A conductor delegating to Jenny in HR over Teams is structurally identical to a conductor delegating to Claude Code over an HTTP API: prompt in, response out, wrapped in Bouncer + capability envelope + audit log. The differences are **latency** (Jenny is slower than an LLM) and **channel** (Jenny gets the prompt over a messaging platform, not a JSON-RPC call).

No other personal-AI-agent platform treats humans as first-class nodes with the same security primitives wrapped around them. They route to humans via Zapier/n8n-shaped workflows but lack the audit log, capability envelope, identity attestation, and per-human optimization to learn anything from the delegation. We have those primitives already. This spec wires them up.

## Solution

Define a **human-on-channel** Shape A node type. The node's `respond` dispatches to a channel adapter; the reactor (S-143) waits on the channel-response event; the Bouncer screens the response on return; the audit log records the human's contribution as a signed VC. Per-human prompt optimization runs through the same Tournament Arena (S-027) machinery that scores AI-agent recipes.

### Node definition

A human node is declared in the same way as any other node (see S-159 Node Designer):

```toml
[[nodes]]
id          = "jenny-hr"
type        = "human"
name        = "Jenny in HR"
did         = "did:web:jenny.example.com"   # optional; for higher-trust signing
intents     = ["hr-policy", "benefits-question", "timeoff-request"]
user_scope  = "jimmy@conductor-a"            # which initiators may delegate to her
optimization = { enabled = true, opt_out_message = "reply STOP-LEARN to disable" }

[nodes.delegation_limits]
max_per_hour = 5   # default set during setup wizard (S-139); stored in config; tunable via Console
max_per_day  = 20

[[nodes.channels]]
type     = "teams"
address  = "@jenny.smith"
priority = 1
hours    = "weekdays 09:00-17:00 PT"
urgency  = ["normal", "urgent"]

[[nodes.channels]]
type     = "conductor"   # her own Conductor instance, S-145 conductor-as-node case
address  = "did:web:jenny-conductor.her-tailnet.ts.net"
priority = 2
hours    = "any"
urgency  = ["any"]

[[nodes.channels]]
type     = "conductor-app"   # the Maistro mobile app (when she has it installed)
address  = "<push subscription endpoint>"
priority = 3
hours    = "any"
urgency  = ["normal", "urgent", "emergency"]

[[nodes.channels]]
type     = "email"
address  = "jenny@example.com"
priority = 4
hours    = "any"
urgency  = ["normal"]

[[nodes.channels]]
type     = "sms"
address  = "+1-555-0100"
priority = 5
hours    = "weekdays 09:00-17:00 PT"
urgency  = ["urgent", "emergency"]   # admin signature required for SMS
```

Five channels for Jenny, in priority order. The conductor picks the highest-priority channel that's currently in-hours and accepts the request's urgency. SMS requires admin signature for any cost-bearing delegation.

### Lifecycle of a human delegation

```
1. Some node in the graph decides to delegate to jenny-hr.
   Reason: intent classifier matched "hr-policy" question; Jimmy's envelope
   permits delegation to humans within his user_scope.

2. Conductor checks rate limits:
     - If this delegation would exceed jenny-hr's max_per_hour or max_per_day,
       return DELEGATION_RATE_LIMIT_EXCEEDED to the requesting node (not a silent
       drop) and abort. The requesting node is responsible for deciding whether to
       retry later, escalate, or fall back.
   Conductor selects a channel:
     - Filter by current time-of-day vs. each channel's `hours`
     - Filter by request urgency vs. each channel's `urgency`
     - Pick the highest-priority surviving channel
     - For Teams: send via Teams adapter
     - For "conductor": federate (S-156) to her conductor as Shape A
     - For "conductor-app": WebPush to her app
     - For email/SMS: send via the appropriate channel plugin
   NOTE: on the first delegation to a new human node, the message includes a
   STOP-LEARN opt-out marker ("reply STOP-LEARN to disable learning") regardless
   of channel. The human can reply STOP-LEARN at any time on any channel to
   disable per-human optimization.

3. Reactor (S-143) registers a wait-event:
     - Event source: <channel adapter>:<delegation-id>
     - Timeout: per channel-type and urgency; e.g. Teams 1 hour, email 24 hours
     - On timeout: try next channel in priority order; if all exhausted, fail
       with structured error "no human response"

4. Jenny replies via the channel.
     - Channel adapter fires the response event with her message + identity claim
     - Identity attestation: Teams-OAuth-attested email, signed Conductor reply,
       biometric-confirmed app push response, etc.

5. Bouncer screens her response. Critical: Jenny's reply is untrusted input.
     - Catches accidental or intentional prompt injection in her reply
     - Catches credential-prefix matches (final-line vault defense, S-141)
     - Rejects with SAFETY_VIOLATION if hit; chain continues with no-response
       fallback or admin escalation per policy

6. Audit log records the contribution as a VC:
     - Issuer: Jenny's DID (if she has one) or the channel-attested identity
     - Subject: the delegation-id
     - Claim: response content (or hash of, if privacy-tagged)
     - Channel: which channel + when
     - Latency: time-to-respond

7. Response feeds back to the next node in the graph.
```

The orchestration layer doesn't know or care that the responder was human. The wrapped `respond()` returned a string; the chain continues.

### Per-human prompt optimization

With opt-in (per-node `optimization.enabled = true`), Tournament Arena (S-027) treats each human node as a recipe with a variant pool:

- **Variants** are different framings of the same intent: concise vs. context-heavy, bulleted vs. prose, with-example vs. without, formal vs. casual.
- **Scoring signals**:
  - Response time (faster = better, normalized per channel)
  - Response usefulness (rated by the receiving agent based on whether the answer let it complete the calling task)
  - Human's explicit 👍/👎 (S-108 user feedback on the conductor's framing)
  - Channel-success: did the human respond at all on this channel, or did we time out
- **Convergence**: Thompson sampling over the variant pool; over weeks the conductor talks to Jenny in *her* most-effective framing.
- **Per-human, not global**: Marcus's optimal framing is independent of Jenny's. There is no global average; each human has their own.

**Privacy:**
- Variant-performance metadata is observable info about how the human communicates. Stored in the long-term graph state (§3 of S-145).
- Opt-in at first delegation: the conductor's first delegation to a new human includes a STOP-LEARN opt-out marker. Disabling optimization deletes the variant-performance state for that human.
- Federated optimization: when Conductor A delegates to Jenny via Conductor B (Jenny's conductor), each conductor learns its own framing; A's variant scores are not shared with B.

### Identity attestation per channel

| Channel | Attestation |
|---|---|
| **Teams** | Microsoft Graph OAuth identity on the message; verified via Teams API |
| **Slack** | Slack workspace OAuth identity; verified via Slack API |
| **Email** | DKIM + SPF + return-path verification; weaker than OAuth but standard |
| **SMS** | Caller-ID verification + per-conversation pairing code (S-149 challenge) |
| **Voice** | Twilio / equivalent caller ID + voiceprint match if enrolled |
| **Conductor** (her own) | Federation handshake (S-156) + DID-signed response (S-152) |
| **Conductor-app** | App-installed device with biometric-attested response signing |

For higher-trust delegations (signing approvals, financial decisions), the conductor refuses lower-trust channels and only routes via Conductor-app or her-own-Conductor. Configurable per-intent.

### Compose with elevation (S-142)

A human node delegation is *not* the same as an admin elevation request:

- **Elevation (S-142):** admin signs a privileged operation Jimmy wants to perform. Admin is the source of authority.
- **Delegation (this spec):** Jimmy asks Jenny something. Jenny's response is *information*, not authority. The chain still operates on Jimmy's permission budget; Jenny's role is to provide content.

Operators who want a human to provide *both* authority and content can chain them: delegation produces the content; admin signs to act on it. Two VCs in the audit log, two distinct roles.

### What this spec does NOT do

- It does not turn humans into permanent admins. Human nodes provide responses; they do not inherit admin authority.
- It does not store the response content unencrypted in the audit log without consent. Privacy-sensitive intents (HR, medical, financial) hash the response in the public VC and store cleartext only in the operator-encrypted side-channel.
- It does not replace S-156 federation. When Jenny has her own Conductor and we route to it, that's S-156 + S-145 conductor-as-node; this spec uses it but does not redefine it.
- It does not enable spam: a human node is a delegation target, not a destination for arbitrary outbound messages. Channel-send caps and admin-signed initial-pairing protect the human's attention.
- It does not hardcode delegation rate limits. Default caps (`max_per_hour`, `max_per_day`) are set during the setup wizard (S-139), stored per-node in config (database / `nodes.toml`), and adjustable at any time in the Console or TUI. `DELEGATION_RATE_LIMIT_EXCEEDED` is returned to the requesting node (not a silent drop) when a cap is exceeded.

## Acceptance Criteria

- [ ] A `human` node can be added via S-159 Node Designer with at least 5 channel options (Teams, email, SMS, conductor, conductor-app)
- [ ] Channel selection respects priority + hours + urgency policy; verified by browser automation
- [ ] Reactor registers wait-events on channel responses; timeout falls back to next-priority channel; exhaustion produces a structured "no human response" error
- [ ] Bouncer screens human responses on return; verified with a test that injects a known prompt-injection payload into a simulated human reply
- [ ] Audit log records every human delegation as a signed VC with channel, latency, identity attestation method, response
- [ ] Privacy-tagged delegations store hashed responses in the public VC and cleartext only in operator-encrypted side-channel
- [ ] Per-human prompt optimization (opt-in) converges on per-human variants over time; verified with simulated Jenny (varying response quality by variant) yielding stable optimal-variant after N delegations
- [ ] Opt-out: `STOP-LEARN` reply disables optimization for that human and deletes variant-performance state
- [ ] Federation case: Conductor A delegates to Jenny via Conductor B; both conductors record the delegation; A learns its own framing without B sharing its variant scores
- [ ] SMS / cost-bearing channels require admin signature before each delegation
- [ ] Higher-trust intents (signing, financial) refuse lower-trust channels (email, SMS) per intent policy
- [ ] Delegation rate limits: defaults set during setup wizard (S-139), stored per-node in config, enforced at delegation dispatch; `DELEGATION_RATE_LIMIT_EXCEEDED` returned to requesting node when a cap is hit (not a silent drop)
- [ ] First contact: the first delegation to a new human node includes a STOP-LEARN opt-out marker in the message; `STOP-LEARN` reply on any channel disables per-human optimization and deletes variant-performance state; no pre-consent gate is required before the first message

## Implementation Notes

- **Channel adapters** are Medley plugins (S-037) of type `channel`. First-party adapters: `teams`, `slack`, `email`, `sms`, `voice`, `conductor`, `conductor-app`. Third-party adapters add channels.
- **Reactor wait-event** registers a unique delegation-id on the channel adapter; the adapter calls back to the reactor when a matching response arrives.
- **Identity attestation** is channel-specific code in each adapter; the conductor consumes a normalized `attested_identity` field returned by the adapter.
- **Response Bouncer** uses the same patterns as input Bouncer (S-022), plus crypto-credential prefix matching (S-141 final-line vault defense).
- **Privacy-tagged storage** uses the encrypted side-channel pattern: VC stores `sha256(response)` in the public field, cleartext stored separately in the vault-encrypted log accessible only via `secrets.use()`.
- **Variant pool** lives in the per-human state row in SQLite (S-140). Schema: `(human_id, variant_id, prompts_sent, responses_received, avg_latency_ms, useful_score, thumbs_up, thumbs_down, last_used_at)`.
- **Optimization gate** for non-opt-in humans: a single fixed framing per intent, no learning. Admin can flip the per-human flag at any time.
- **Channel selection** is rule-based + admin-overridable: operators can pin a channel for a specific intent or a specific human via the Node Designer.
- **Rate limit enforcement** checks `(human_id, window)` counters in SQLite before dispatching. The `max_per_hour` and `max_per_day` values are stored in the node's config row; the setup wizard writes the initial defaults and the Console TUI can update them at any time.
- **Federation interaction:** when the human's primary channel is `conductor` (their own Maistro instance), the delegation is a S-156 federated handshake to their conductor's DID; the rest of the flow is identical, just with their conductor as the responder.
- **Compose with S-027:** the variant pool for human nodes is registered with Tournament Arena under a separate prefix (`human:<node-id>:<intent>`) so it's distinguishable from AI-recipe variants in the dashboard.

## Verification

- Add a Jenny node via S-159 Node Designer with 5 channels.
- Trigger a delegation — hr-policy intent during work hours — verify Teams adapter sends the prompt; simulate her response; verify Bouncer screens it; verify the chain completes with her response as the next-node input; verify audit-log VC.
- Trigger a delegation outside her work hours — verify it falls back to email or conductor-app per policy.
- Trigger a delegation flagged as `privacy-sensitive` — verify the public VC stores `sha256(response)` and cleartext is in the encrypted side-channel only.
- Bouncer drill: inject a prompt-injection payload as Jenny's simulated reply — verify rejection with SAFETY_VIOLATION.
- Optimization test: simulate 100 delegations with two variant framings where one consistently produces faster useful responses; verify Tournament Arena converges to that variant; verify the variant becomes the default after N=20 delegations.
- Opt-out test: send `STOP-LEARN` from Jenny's verified address; verify the variant-performance row is deleted and subsequent delegations use the default framing.
- Federation test: configure Jenny's primary channel as her own conductor; delegate from A; verify A talks to B's conductor over S-156; verify both conductors' audit logs reflect the delegation; verify A's optimization state is independent of B's.
- Cost-channel guard: attempt SMS delegation without admin signature — verify refusal; with admin signature, verify success.
- Higher-trust intent: configure `signing-approval` intent to refuse email/SMS; attempt routing via email — verify channel selection skips email and routes via conductor-app or her-own-conductor only.
- Rate limit test: fire delegations to jenny-hr up to `max_per_hour`; verify the next attempt returns `DELEGATION_RATE_LIMIT_EXCEEDED` (not silence); verify the counter resets after the window; update `max_per_hour` via the Console and verify the new limit takes effect immediately.
- First-contact test: add a new human node and trigger the first delegation; verify STOP-LEARN marker is present in the outbound message; verify a subsequent delegation omits the marker.
