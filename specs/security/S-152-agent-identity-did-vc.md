---
id: S-152
title: "Agent Identity & Verifiable Credentials (DID + VC)"
domain: security
status: draft
priority: P1
effort: ""
created: 2026-04-25
updated: 2026-05-13
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-152: Agent Identity & Verifiable Credentials

## Problem

The conductor needs a public, verifiable identity. Without one:

- Cross-instance federation (S-114, S-115) has no trust foundation. "Conductor A trusts Conductor B's contributions" is a claim, not a verifiable fact.
- Audit log entries (S-033) are bare assertions. An external auditor cannot verify a record without trusting the conductor.
- Crypto operations (S-151) lack a counterparty identity. The agent can hold an address but can't prove *which* conductor that address belongs to.
- Medley plugin authenticity (S-037, S-111) has no cryptographic anchor for "who issued this skill."

The agent needs an identity it controls, that others can resolve, that supports rotation, and that doesn't require a centralized issuer or any specific networking substrate.

## Solution

W3C **Decentralized Identifier (DID)** + W3C **Verifiable Credentials (VC)**. The conductor's identity is a DID; assertions about its actions, peers, and plugins are VCs signed by that DID.

### DID methods

Every conductor has at minimum:

- **`did:key`** — derived deterministically from the S-149 path `m/44'/9000'/0'`. The pubkey *is* the identifier. Always available, no infrastructure required, works on a localhost-only deployment.

When the conductor has a public-or-tailnet HTTPS endpoint (via any substrate from S-153):

- **`did:web:<hostname>`** — resolves via `https://.../.well-known/did.json` served from the conductor's HTTP layer. Supports rotation and service endpoints. The hostname comes from whichever networking substrate the operator chose:
  - Tailscale: `<instance>.<tailnet>.ts.net`
  - Headscale: `<instance>.<headscale-host>`
  - Cloudflare Tunnel: `<operator-domain>`
  - Manual: whatever the operator's reverse proxy serves
  - **No HTTPS surface? Just `did:key`.** That is a fully valid identity.

Opt-in via Medley plugins:

- **`did:ethr`** — Ethereum-anchored, ENS-compatible (`brigid.eth`)
- **`did:ion`** — Bitcoin-anchored via Sidetree
- **`did:plc`** — AT Protocol / Bluesky federation
- **`did:dht`** — Mainline DHT, fully decentralized

All methods point to the *same* underlying keys (derived from S-149); they differ in resolution layer, not in identity.

### DID document structure

Served at `https://<conductor-hostname>/.well-known/did.json` whenever a substrate provides an HTTPS endpoint:

```json
{
  "@context": ["https://www.w3.org/ns/did/v1"],
  "id": "did:web:brigid.example.ts.net",
  "alsoKnownAs": ["did:key:z6Mk…"],
  "verificationMethod": [
    {
      "id": "did:web:brigid.example.ts.net#agent-spec",
      "type": "Ed25519VerificationKey2020",
      "controller": "did:web:brigid.example.ts.net",
      "publicKeyMultibase": "z6Mk…"
    },
    {
      "id": "did:web:brigid.example.ts.net#audit-log",
      "type": "Ed25519VerificationKey2020",
      "publicKeyMultibase": "z6Mk…"
    }
  ],
  "service": [
    {
      "id": "#message-board",
      "type": "MessageBoard",
      "serviceEndpoint": "https://brigid.example.ts.net/board"
    },
    {
      "id": "#lightning",
      "type": "LightningAddress",
      "serviceEndpoint": "brigid@example.ts.net"
    }
  ]
}
```

Key identities reference the S-149 derivation tree: `#agent-spec` is `m/0'`, `#audit-log` is a sub-derivation, etc. Rotation = publish a new doc.

### DID document pinning and change detection

When a peer's DID document is resolved for the first time, conductor stores a **fingerprint** (SHA-256 of the canonical JSON) keyed by the peer's DID. On all subsequent resolutions:

- **Fingerprint matches**: accept silently, update cache TTL.
- **Fingerprint changed**: pause federation with that peer, post a `DID_DOCUMENT_CHANGED` alert to the admin Dashboard, and require explicit admin confirmation before accepting the new document.

Silent acceptance of DID document changes is not permitted. Key rotation is a legitimate operation but so is a MITM swapping in an attacker's key; admin confirmation is the only way to distinguish them. Cached fingerprints are stored in the audit log table and are themselves signed, so they cannot be silently altered.

### Verifiable Credentials

Four use cases, all using the same VC primitive:

**(1) Audit log VCs.** Every privileged operation produces a signed VC:

```json
{
  "@context": ["https://www.w3.org/ns/credentials/v2"],
  "type": ["VerifiableCredential", "AuditLogEntry"],
  "issuer": "did:web:brigid.example.ts.net",
  "validFrom": "2026-04-25T14:32:01Z",
  "credentialSubject": {
    "operation": "skill.execute",
    "skill": "ha-ai",
    "requestingUser": "did:web:brigid.example.ts.net#user1",
    "args": { "target": "living_room.lights", "action": "on" },
    "result": "success"
  },
  "proof": { … }
}
```

VCs are stored in the audit log table. Dashboard Intel tab gains a "verify" button per entry that resolves the DID, fetches the doc, and validates the signature offline.

**(2) Federation trust VCs.** When two conductors meet (S-114, S-115), each can issue a scoped trust credential:

```
Issuer: did:web:brigid.example.ts.net
Subject: did:web:atelier-2.other.ts.net
Claim: trustsForContributions: ["medical-knowledge"]
ValidFrom: 2026-04-25
ValidUntil: 2026-05-02   # max 7 days
```

Trust VCs have a **maximum validity of 7 days**. Peers must re-issue on each scheduled federation sync; an expired trust VC is treated the same as no VC — contributions from that peer are paused until renewed. This gives effective revocation without a status-list infrastructure: a compromised or misbehaving peer is automatically quarantined within 7 days (sooner if admin explicitly revokes by not re-issuing).

There is no long-lived trust grant. Every federation relationship must be re-confirmed at least weekly.

**(3) Plugin publisher VCs.** Medley plugins (S-037, S-111) ship with publisher-issued VCs:

```
Issuer: did:web:lightning-labs.com
Subject: <plugin-content-hash>
Claim: "This plugin was reviewed and signed by Lightning Labs on date X"
```

Medley install verifies the VC before the plugin reaches even the `untrusted` tier; an unsigned plugin requires explicit admin override to install.

**(4) Third-party certifications.** External authorities issue VCs to the conductor:

```
Issuer: did:web:anthropic.com
Subject: did:web:brigid.example.ts.net
Claim: "Licensed for Claude API access through 2027-04-25"
```

Displayed in the dashboard as part of the conductor's identity card.

### Standards alignment

- **W3C DID Core 1.0** — the DID and DID document model
- **W3C VC Data Model 2.0** — the VC structure
- **JWT-VC** *and* **JSON-LD-VC** formats both supported
- **BIP-322** for arbitrary message signing (composes with the wallet-signing surface from S-151)
- **DIDComm v2** for conductor-to-conductor messaging when both parties have DIDs (federation transport in S-115)

## Acceptance Criteria

- [ ] Every conductor has a `did:key` derivable from S-149 `m/44'/9000'/0'` with no additional configuration; this works even on localhost-only substrates
- [ ] When the substrate (S-153) provides an HTTPS hostname, conductor publishes `did:web:<hostname>/.well-known/did.json` automatically
- [ ] DID document includes verification methods for all S-149-derived signing keys in active use
- [ ] Every privileged operation in the audit log is recorded as a signed VC
- [ ] Dashboard Intel tab can verify any audit-log VC against the conductor's published DID document
- [ ] Federation flow (S-114): two conductors exchange DIDs, admin issues a scoped trust VC, federated contributions carry verifiable provenance
- [ ] Medley install verifies plugin publisher VCs; unsigned plugins require explicit admin override
- [ ] Key rotation: conductor can publish a new DID document with new keys; old VCs remain verifiable against the historical document (kept in `did.json.history/`)
- [ ] Crypto-native opt-in: `medley install did-ethr` adds `did:ethr` to the `alsoKnownAs` list without disrupting the primary DID
- [ ] Federation trust VCs have a maximum validity of 7 days; no long-lived trust grant is possible
- [ ] Expired trust VC: contributions from that peer are paused until a new VC is issued
- [ ] First-seen DID document fingerprint (SHA-256) is stored per peer in the signed audit log table
- [ ] DID document change detected: federation with that peer paused, `DID_DOCUMENT_CHANGED` alert posted to Dashboard, admin confirmation required before accepting new document
- [ ] Cached fingerprints are signed and cannot be silently altered

## Implementation Notes

- **Library suggestions:** `didkit` (Spruce), `ssi-sdk`, or roll our own minimal implementation — W3C VC is small enough to implement directly in ~500 lines.
- **Storage:** DID document is a static file regenerated on key rotation. VCs are first-class rows in the audit log table (sqlite-vec).
- **Resolution cache:** when verifying VCs from peer conductors, cache resolved DID documents for 24h to limit substrate traffic. Cache entries include the stored fingerprint; a fresh resolution that changes the fingerprint triggers the admin alert flow regardless of cache TTL.
- **`did:web` hosting:** served by whatever substrate (S-153) is exposing the conductor's HTTP endpoint. With Tailscale that's `tailscale serve`; with Cloudflare Tunnel that's `cloudflared`; with manual mode that's the operator's reverse proxy. The conductor itself just serves `/.well-known/did.json` from its HTTP layer.
- **Privacy:** DID document publication is **off by default for tailnet-private and localhost-only deployments**. The wizard explicitly asks: *"Publish your conductor's identity? (Recommended for federation. Required for some Medley plugins. Not required for normal use.)"* For Tailscale, this means choosing whether `tailscale funnel` exposes `/.well-known/did.json` to the public internet. For other substrates, equivalent decisions.
- **Localhost-only deployments:** always have a working `did:key`. Federation and external VC verification are simply unavailable until a public-or-tailnet substrate is configured.
- **Trust VC renewal:** federation sync job (scheduled, configurable interval, default daily) re-issues trust VCs for active peers. If a peer's fingerprint has changed since last sync, renewal is blocked until admin confirms the new document.

## Verification

- On a localhost-only deploy: `did:key` is derivable and signs audit-log VCs.
- On a Tailscale deploy: `curl https://brigid.example.ts.net/.well-known/did.json` returns a valid DID document.
- Run a privileged operation; the audit log entry is a signed VC.
- Verify the VC offline using the published DID document; signature is valid.
- Pair two conductors on the same tailnet; admin issues a trust VC (7-day max) from one to the other; federated contributions from the second appear in the first's Intel tab marked "verified."
- Let the trust VC expire without renewal; verify contributions from the peer are paused and a renewal prompt appears.
- Install an unsigned Medley plugin; install is blocked pending admin override.
- Rotate the `m/0'` key; old audit-log VCs still verify against the historical DID document; new operations sign with the new key.
- Switch substrate from Tailscale to Cloudflare Tunnel: DID document re-publishes at the new hostname; old `did:web:<old-host>` reads from `did.json.history/` for backward verification of past VCs.
- Simulate a peer rotating their DID document (new key): verify `DID_DOCUMENT_CHANGED` alert appears, federation pauses, and resumes only after admin confirms the new document.
- Replay a `DID_DOCUMENT_CHANGED` event with a tampered fingerprint record: verify the signed fingerprint storage prevents silent substitution.
