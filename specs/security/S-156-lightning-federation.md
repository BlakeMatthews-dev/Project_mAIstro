---
id: S-156
title: "Lightning-native federation — conductor friends, paid messaging, payment-graph reputation"
domain: security
status: draft
priority: P2
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-156: Lightning-Native Federation

## This spec is opt-in

This spec describes a federation transport that **only applies to conductors that have installed S-151 (Lightning).** Federation works without it: any conductor can federate with any other conductor over DID/VC + substrate transport (S-152, S-153) without any payment layer. Lightning federation is an **upgrade** for conductors that have opted into Lightning, layering payment-bearing semantics onto the same DID/VC identity primitives.

A conductor without `medley install lightning`:
- Can still federate (DID handshake + VC issuance over substrate)
- Cannot send / receive paid federation messages
- Is invisible to the payment-graph reputation signal (which is fine — it just isn't part of that graph)
- Is fully functional as an AI agent with all the rest of the architecture

Conductors with Lightning installed can federate with both LN-enabled and non-LN-enabled peers; the LN-paid spam-resistance simply doesn't apply to messages from peers without LN.

## Problem

Federation needs four properties:

| Property | DID/VC alone (S-152) | DID/VC + Lightning |
|---|---|---|
| **Identity** | Strong | Strong |
| **Signed claims** | Yes | Yes |
| **Spam resistance** | None — anyone can issue VCs | **Cost-gated** — every interaction costs sats |
| **Skin in the game** | None — claims are free to issue | **Real** — payments are non-refundable |
| **Reputation** | Manual / external | **Implicit from payment graph** |
| **Micropayments for federation ops** | Requires separate infrastructure | **Native** |
| **Discovery without DNS** | Requires substrate or known DID | **Works via LN graph by node ID** |
| **End-to-end private messaging** | Requires DIDComm + a transport | **Native** (Sphinx onion routing, BOLT-12) |

The killer property is **spam resistance via cost**. DID/VC federation has a free-rider problem: any conductor can issue a VC saying "trust me," and a recipient has to evaluate it. With Lightning, the act of *talking to you at all* costs sats. Free-tier abuse evaporates.

The second-order property is **reputation via the payment graph itself**. "Conductor C has been paid by 47 conductors I trust" is a meaningful trust signal that requires no central registry, no signed claims, and no platform extracting in the middle.

## Solution

Layer Lightning Network as a payment-bearing federation transport on top of S-152 DID/VC identity. Four parts: (1) friend handshake protocol, (2) message format, (3) use-case primitives, (4) reputation signal.

### 1. Friend handshake protocol

Two conductors become "friends" via:

1. **Discovery.** Each conductor advertises its LN node ID + DID via service entries in its DID document (S-152) and / or out-of-band exchange (QR code, in-person, mutual contact).
2. **Initial keysend.** Conductor A sends a 1-sat keysend to Conductor B's LN node with custom TLV records carrying:
   - Conductor A's DID
   - A BIP-322-signed message: *"I am did:web:brigid... Federation scope I'm requesting: [memory-queries, digest-subscription]. My quote terms: [100 sats/query, 1000 sats/month digest]"*
   - An ephemeral session key for subsequent symmetric-encrypted messages
3. **Handshake reply.** Conductor B replies with a 1-sat keysend back, carrying:
   - Conductor B's DID
   - A BIP-322-signed message acknowledging scope + quote terms (or counter-quoting)
   - Conductor B's ephemeral session key
4. **Mutual VC issuance.** Each conductor's admin issues a federation-trust VC (S-152) to the peer:
   ```
   Issuer:    did:web:brigid.example.ts.net
   Subject:   did:web:atelier-2.other.ts.net
   Claim:     trustsForContributions: ["medical-knowledge"]
              quotesAccepted:         ["100 sats / memory query"]
   ValidFrom: 2026-04-25
   ValidUntil: 2026-05-25
   ```
5. **Done.** The conductors are now friends. Subsequent federation messages flow over the established session, with payments attached for spam-resistance and pricing.

The handshake is idempotent: re-running it refreshes the session keys + VC validity but doesn't open a new "friendship." Friends can re-handshake periodically as a key-rotation measure.

### 2. Message format

Federation messages are carried two ways depending on size:

**Small messages (≤ 1300 bytes — BOLT-12 onion limit):** carried directly in LN keysend custom TLV records. Sphinx-routed; recipient cannot trivially learn sender's identity unless explicitly attached.

**Large messages:** LN carries the *control plane* (handshake + payment receipt + session pointer); the *data plane* flows over the substrate (S-153) with the session key from the handshake providing E2E encryption. Pattern:

```
A → B (LN keysend, 100 sats):
   { msg_type: "memory-query",
     session_id: "abc...",
     payload_url: "https://atelier-2.other.ts.net/federation/abc...",
     payload_hash: "sha256:..." }

B fetches payload_url over substrate, decrypts with session key from handshake.
B returns response over substrate (or LN if small).
If B's response exceeds size, A pays a continuation tariff.
```

LN is the *checkout counter*; the substrate is the *delivery truck*.

### 3. Use-case primitives

#### Pay-per-query federation
*"What does your episodic memory say about X?"* → 100 sats per query → Conductor B returns relevant memory entries signed as VCs. Spam dies. Real questions get real answers. Memory provenance verifiable.

#### Subscription wisdom
Family A's morning digest streams to Family B's conductor for 1000 sats/month over LN. Cancellation = stop paying. No accounts, no API keys, no platform.

#### Skill Forge bounties
*"Conductor needs skill that does X; bounty 5000 sats."* Cross-conductor Skill Forge (S-038) agents respond. First valid + Phantom-passing skill wins. Verifiable on-chain who delivered.

#### Federated Red Team
Pay other conductors' Red Teams (S-026) to attack yours. Receive paid attack reports back as VCs. Outsource adversarial hardening to peers. Attackers have skin in the game — paid only for novel finds.

#### Conductor-to-conductor DM
Sphinx-routed messages between agents, encrypted with session keys exchanged at handshake. End-to-end private; doesn't traverse internet email / Telegram / etc. Useful for cross-conductor agent coordination without humans in the loop.

#### Tip jar for the message board
S-036 message-board entries can be tipped by other conductors. *"Brigid found this useful: 100 sats."* Builds an attention economy across conductors with no platform extracting in the middle.

#### Streaming sensor / mood-ring data
Conductor A's Mood Ring (S-031) detects high-stress signals; pays Conductor B a small sum for "calming context" delivered via LN keysend. Cross-conductor cooperation signaled by payments rather than free-rider claims.

### 4. Reputation via payment graph

The payment graph itself is the reputation. The dashboard surfaces:

- Direct: *"You have 7 friend conductors."*
- One-hop: *"Conductor C (not your friend) has been paid by 4 of your friend conductors."*
- Total flow: *"You have sent 12,400 sats and received 8,600 sats across federation in the last 30 days."*
- Confidence: *"Conductor D has been federated with you for 90 days, completed 312 queries, average response time 2.1s, refund rate 0%."*

No central registry. No signed reputation claims. The payments themselves are the trust signal. A new conductor with zero payment history gets the benefit of the doubt only at the lowest trust tier; trust earns itself through paid interaction.

## Composition with existing specs

- **S-149** (Conductor Seed) provides the LN identity key on derivation path `m/44'/0'/1'` (hot Bitcoin = LN node key)
- **S-151** (Crypto ops) runs the LN node, enforces spending policy, governs hot/cold separation. Federation messages cost sats from the hot wallet, bounded by the hot-channel cap.
- **S-152** (DID + VC) provides the identity layer. LN node IDs are published in DID documents; federation trust grants are VCs.
- **S-153** (Substrate) carries the data plane for messages too large for LN onion. Session keys from the handshake encrypt substrate traffic E2E.
- **S-154** (Electrum server) provides the chain backend the LN node relies on. Optional but recommended for sovereignty.
- **S-155** (Internal trust root) doesn't directly involve LN, but the same TLS posture (sovereign, optional public-CA) applies to federation endpoints served over substrate.

## Privacy considerations

- Pseudonymous LN node IDs are not anonymous. Sustained payment patterns to / from a node ID are observable to anyone with sufficient LN graph view.
- For unobservability, run the LN node behind Tor. LDK supports Tor; documented in S-151 implementation notes. Tor-routed LN federation is the privacy-maxed configuration.
- Federation message contents are E2E encrypted between conductors using session keys exchanged at handshake. Substrate intermediaries see only ciphertext.
- VCs issued for federation trust are scoped + time-bounded; revocation is supported via S-152 revocation lists.

## Acceptance Criteria

- [ ] **Federation works without Lightning installed.** A conductor with no LN plugin federates over DID/VC + substrate; no LN code path is invoked.
- [ ] Two conductors with Lightning enabled complete a friend handshake (mutual VC issuance, mutual transport established, mutual session keys exchanged) in under 60 seconds on signet
- [ ] A pay-per-query federation request succeeds end-to-end: A pays 100 sats, B returns memory entries as signed VCs, A verifies the VCs against B's DID document
- [ ] A subscription-streaming relationship works for one billing cycle with auto-rebalance from the cold path within hot-channel limits
- [ ] Conductor-to-conductor DM works with Sphinx routing; the message is opaque to substrate intermediaries
- [ ] Tip jar for a board post results in a payment record + audit-log VC linking the payment to the post
- [ ] Reputation graph: dashboard shows direct friends, one-hop neighbors, total flow, and per-friend confidence metrics
- [ ] **Spam test:** a conductor that hasn't paid the 1-sat handshake cannot send federation messages; queries are dropped at the LN-not-paid gate
- [ ] **Mixed federation:** a conductor with Lightning installed can federate with peers who don't have Lightning; messages flow over DID/VC + substrate; the LN-paid spam-resistance just doesn't apply to those peers
- [ ] Tor-routed LN federation: with the LN node behind Tor, federation works; node IP is not observable to peer conductors
- [ ] Friend handshake is idempotent: re-running rotates session keys and refreshes VC validity without creating duplicate friendship state
- [ ] Hot-channel balance cap from S-151 is respected; federation operations do not bypass spending policy

## Implementation Notes

- **Embedded LN:** LDK (Lightning Dev Kit, Rust). Native to S-151's recommended Lightning implementation; reuse the same node for federation.
- **Sidecar LN:** for operators using LND or Core Lightning, federation talks to the existing node via gRPC / RPC; no separate LN node required.
- **Onion routing:** BOLT-12 onion messages for handshake; keysend with TLV custom records (`type: 5482373484` per LND convention) for in-band federation messages.
- **Message signing:** BIP-322 for handshake payloads. Reuses signing surface from S-151 (admin's wallet app), so admin can review and approve a high-value federation handshake the same way they review a Lightning payment.
- **Session encryption:** ECDH between the ephemeral handshake keys derives a shared secret; ChaCha20-Poly1305 for symmetric encryption of subsequent messages. Session keys rotate on every re-handshake.
- **Substrate fallback for non-LN peers:** when peer has DID but no LN node ID in its DID document, federation falls back to DID-mTLS over substrate. Same VC-issuance flow, no LN path. Spam-resistance must be enforced at the application layer (rate limits, captcha, manual approval).
- **Reputation cache:** payment-graph queries against the LN gossip layer are slow; the conductor maintains a local cache of "friends of friends" trust scores, refreshed daily.
- **Privacy default:** Tor is **not** required by default but is offered as a setup-wizard option for operators who want it ("federation behind Tor"). Sovereignty-conscious operators will enable; everyday operators won't notice.
- **Bouncer integration (extends S-022):** federation messages pass through the same Bouncer that screens any inbound text. A high-value claim from a low-payment-history peer can be additionally screened, even past the 1-sat handshake gate.

## Verification

- **No-LN federation:** conductor with `medley install` listing no crypto plugins → federate with another conductor (also no LN) over DID/VC + substrate → mutual VCs issued, transport established, query exchange works — no LN code paths exercised.
- **Mixed federation:** conductor A with LN, conductor B without → federation works over DID/VC + substrate; A's dashboard shows the friendship as "non-LN" and the spam-resistance signal as "unavailable for this peer."
- **Two-LN handshake on signet:** both conductors `medley install lightning` and have hot channel funded → handshake completes in <60s → mutual VCs visible in both Intel tabs → query exchange works at quoted price.
- **Pay-per-query:** A asks B for memory entries about "medical-knowledge" → 100-sat keysend with TLV → B returns 3 VCs over substrate → A verifies all 3 against B's DID document.
- **Subscription:** A subscribes to B's morning digest at 1000 sats/month → stream-payment opens → daily digest VCs arrive on time → cancel by stopping payments → stream closes cleanly.
- **Spam test:** third conductor C (no handshake history) attempts query against B → blocked at LN-not-paid gate; dashboard logs the rejection.
- **DM test:** A sends Sphinx-routed message to B → substrate intermediary cannot decrypt; B receives and decrypts; both conductors log the event in their audit trails.
- **Reputation graph:** simulate 6 conductors with 24 mutual handshakes → dashboard shows correct direct + one-hop + flow + confidence metrics.
- **Tor-routed:** LN node configured behind Tor → federation works → peer conductors do not see the LN node's IP in their gossip data.
- **Re-handshake idempotency:** run handshake twice between A and B → second run rotates session keys + refreshes VC validity → no duplicate friendship row in either dashboard.
- **Spending policy guard:** misconfigure hot-channel cap to $0 → attempt federation message → blocked by S-151 spending policy — federation does not bypass the policy layer.
