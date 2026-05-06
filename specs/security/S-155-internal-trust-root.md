---
id: S-155
title: "Internal trust root from Conductor Seed — mkcert-style local CA, DID-anchored"
domain: security
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-155: Internal Trust Root from Conductor Seed

## Problem

The conductor needs valid HTTPS for hostnames that don't have a public-CA chain yet. Specifically:

- Internal-mesh hostnames on substrates (S-153) that don't auto-issue Let's Encrypt certs — NetBird's internal `*.netbird.cloud`-style names today, ZeroTier-routed services, LAN-mDNS `*.local` hostnames, and any operator-chosen private hostname.
- Localhost-only deployments where there's no public DNS to attach a cert to.
- The window between *now* and the eventual landing of LE DNS-PERSIST-01 production GA + downstream substrate integration (currently expected Q2 2026 + unknown lag).
- **Operators who don't want to be in the public PKI in the first place.** Some users — the same population that runs their own Bitcoin node and says *"not your keys, not your coins"* — have a strong philosophical preference for sovereign control over their own TLS trust chain. For them, depending on Let's Encrypt + ICANN + CT logs is itself the problem, not the solution.

Browsers and OSes only trust certs that chain to a CA in their system trust store. The shortcuts that are tempting but wrong:

- Self-signed leaf cert on each hostname → every device shows a warning forever.
- One self-signed cert pinned via TOFU → doesn't work in any vanilla browser.
- DID-rooted TLS via a draft IETF spec → zero browser support today.

The only working path is: **be your own CA, and get devices to trust your CA root.** Done well, this composes with the rest of the architecture (the seed, the DID, VCs) to make the trust install ceremony itself an artifact of the same security model — *and* it's a permanent first-class option for operators who never want public PKI in their chain.

## Solution

The conductor mints an X.509 Certificate Authority deterministically derived from the Conductor Seed (S-149), constrained to the conductor's own hostnames, and ships a slick install ceremony that delivers the CA root to each household device exactly once.

This is **not a stopgap.** It's a permanent capability. Operators who want public-CA-chained TLS get it (today via substrate-provided LE certs; eventually via DNS-PERSIST-01 + substrate integration for internal hostnames). Operators who explicitly *don't* want public PKI in their trust path get it for the lifetime of the project.

### Key derivation

The CA private key is a P-256 (secp256r1) key derived deterministically from the Conductor Seed via HKDF:

```
ca_secret = HKDF(
  ikm  = bip39_seed_bytes,                # from S-149
  salt = "maistro-tls-ca-v1",
  info = instance_name,                   # binds the CA to this conductor's identity
  L    = 32                               # P-256 private key size
)
ca_priv = secp256r1_priv_from_secret(ca_secret)
ca_pub  = ca_priv.public_key()
```

Properties:

- **Deterministic:** restore the seed on a new machine → same CA regenerates → already-installed trust roots remain valid.
- **Compartmented:** version-bumping the salt (`maistro-tls-ca-v2`) generates a fresh CA without affecting other seed-derived keys.
- **P-256 chosen, not Ed25519:** universally supported in X.509 / TLS / OS trust stores. Ed25519 in X.509 has growing but not universal acceptance.
- **Independent of BIP32 paths:** lives in HKDF-space, not the BIP44 tree, so it doesn't collide with wallet derivations from S-149.

### CA cert structure

The self-signed CA cert has these properties:

- **Subject CN:** `<instance-name> Conductor CA`
- **Validity:** 10 years (regenerated automatically as expiry approaches)
- **Key usage:** Certificate Sign, CRL Sign
- **Basic Constraints:** `CA:TRUE, pathlen:0` (can sign leaves but not sub-CAs)
- **Name Constraints (critical):** `permittedSubtrees` restricted to the conductor's published hostnames only — e.g., `DNS:*.brigid.local, DNS:brigid.local, DNS:*.<instance>.<tailnet>.ts.net`

**Name Constraints is the load-bearing safety property.** Even if a household device has the conductor's CA root installed, that CA can ONLY issue valid certs for the conductor's own hostnames. It cannot impersonate google.com, your bank, or anything else. Browsers and OSes that honor X.509 Name Constraints (everything modern) enforce this at the validation layer.

### Leaf certs

The conductor issues short-lived leaf certs from the CA for each of its served hostnames:

- Dashboard
- `did:web` document (S-152)
- Message board (S-016)
- Lightning receive endpoint (S-151) — if not on a public-CA path
- Electrum protocol port (S-154) — if exposed via this CA

Leaf properties:

- **Validity:** 90 days, auto-rotated by the conductor with no operator action
- **Subject Alternative Names:** all hostnames the leaf serves (dashboard variants, etc.)
- **Extended Key Usage:** Server Authentication only
- Signed in seconds; no external dependency

### TLS modes (operator choice)

The conductor supports three TLS configurations, selectable by the operator and freely switchable:

```toml
# ~/.conductor/tls.toml

# Mode 1: public-ca (default for households when substrate provides it)
mode = "public-ca"
# Conductor serves substrate-provided LE / public-trusted certs.
# Local CA exists but is unused; trust install ceremony is skipped.

# Mode 2: local-ca (sovereignty mode)
mode = "local-ca"
# Conductor serves leaves from its own CA exclusively.
# Public PKI is never in the trust chain. LE / DNS-PERSIST-01 are bypassed.
# This is the "not your keys, not your TLS" mode.

# Mode 3: both (parallel chains)
mode = "both"
prefer = "public-ca"   # or "local-ca"
# Conductor serves a leaf chain from whichever is configured as preferred,
# with the other available as a fallback. Useful during migration in either
# direction, or for operators who want belt-and-suspenders.
```

The wizard surfaces this as a deliberate choice during S-139 setup, not a hidden flag:

```
? TLS for this conductor:

  > Public CA (recommended for most setups)
      → Substrate provides Let's Encrypt certs automatically (where supported).
      → Devices trust certs natively, no install required.
      → Falls back to local CA on substrates without public-cert support.

    Local CA (sovereignty mode)
      → Conductor is its own certificate authority.
      → Trust chain never leaves your seed.
      → Each household device installs the CA root once via QR ceremony.
      → Recommended if you also run your own Bitcoin node.

    Both (advanced)
      → Run public and local CAs in parallel. Useful for migration.
```

Mode is reversible. An operator can switch from `public-ca` to `local-ca` (or vice versa) at any time; existing trust grants are preserved across the switch.

### Trust install ceremony

During S-139 setup — if mode is `local-ca` or `both` — the wizard generates a one-time install URL:

```
┌─ Trust this Conductor on your devices ──────────────┐
│                                                       │
│  https://<conductor>/trust/<one-time-token>           │
│                                                       │
│   [QR CODE]                                           │
│                                                       │
│  Each household device should visit this URL once.    │
│  After install, the device trusts:                    │
│    • *.brigid.local                                    │
│    • brigid.local                                      │
│  Nothing else. The CA can't impersonate any other      │
│  site.                                                │
│                                                       │
│  This QR is valid for 24 hours.                       │
└─────────────────────────────────────────────────────────────┘
```

Visiting the URL on a device opens a tiny PWA that:

1. Fetches the CA cert in DER + PEM forms.
2. Detects the platform and presents the right install path (see matrix below).
3. Once installed, redirects the user to `https://<conductor-hostname>` to verify it works.

The install ceremony itself is wrapped in a Verifiable Credential (S-152):

```
Issuer:    did:web:brigid.example.ts.net
Subject:   <device fingerprint, generated client-side>
Claim:     authorizedToTrust: "<CA SHA-256 fingerprint>"
           validFor:          ["*.brigid.local", "brigid.local"]
           validFrom:         2026-04-25
           validUntil:        2026-10-25
```

The VC is logged in the audit trail. If a device is later compromised or sold, the VC can be revoked from the dashboard, and the CA is rotated for further safety.

### Per-platform install matrix

| Platform | Browser access | Custom-app access | UX |
|---|---|---|---|
| **macOS** | Native after CA install in System Keychain | Native | One tap, no friction |
| **Windows** | Native after CA install in Trusted Root | Native | One install dialog |
| **Linux** (most distros) | Native after `update-ca-certificates` | Native (most apps); Firefox / Java need their own bundle | Documented; PWA runs the right command |
| **iOS** | Native after install **and** explicit trust enable | Native | **Two-step**: install profile, then Settings → General → About → Certificate Trust Settings → enable. PWA shows a screencast. |
| **Android** | Works in Chrome / Firefox after CA install | **Apps must opt-in via `network_security_config.xml` since API 24 (Android 7)** | Browser surfaces work today; native Maistro app (when it exists) ships the CA pinned. |

### DID anchoring

The conductor's DID document (S-152) gains a service entry advertising the CA:

```json
{
  "id": "#tls-trust-anchor",
  "type": "X509TrustAnchor",
  "serviceEndpoint": {
    "caCertSha256": "<hash>",
    "caCertUrl": "https://<conductor>/trust/ca.pem",
    "nameConstraints": ["*.brigid.local", "brigid.local"],
    "validFrom": "2026-04-25",
    "validUntil": "2036-04-25"
  }
}
```

A verifier resolving the conductor's DID can independently fetch the CA cert and confirm: this CA was authorized by this conductor, scoped to these hostnames, by the same key that signs the rest of the conductor's identity. No additional trust hop required.

### Sequencing (versions of this spec over time)

**v1 (this spec):** QR-code install ceremony, browser-first. Works on every platform with a browser. **Ship now.**

**v2 (when a native Maistro mobile app exists):** bundle the CA root pinned in the app for app-to-conductor traffic. Resolves the Android-user-CA-app gap.

**v3 (if substrate management plane gains CA distribution):** if NetBird (per [netbirdio/netbird#5479](https://github.com/netbirdio/netbird/issues/5479)) ships management-pushed cert/CA distribution — or if Tailscale, Headscale, etc. add the equivalent — the install ceremony becomes substrate-mediated and the QR step disappears for users on that substrate. Falls back to QR if the substrate doesn't support it.

**v∞ (parallel paths, permanent):** when LE DNS-PERSIST-01 production GA + substrate integration ships, the public-CA path becomes available *alongside* the local CA. Operators choose their TLS mode (`public-ca`, `local-ca`, or `both`). **The local CA does not retire.** It remains a permanent first-class option for operators who explicitly want sovereign TLS — the same audience that runs their own Bitcoin node, holds their own seed phrase, and refuses to depend on third-party PKI as a matter of principle. Maistro is the only personal-AI-agent platform that supports this end-to-end, and that's the point.

### What this spec does NOT do

- **It is not a public CA.** It can only issue certs for the conductor's own hostnames, enforced by X.509 Name Constraints. Devices that install the root cannot be impersonated for any other site.
- **It does not force one TLS mode over another.** Operators choose. The default for a typical household is `public-ca` (least friction); the default for an explicitly sovereignty-minded operator is `local-ca` (no public PKI dependency).
- **It does not solve cert validation in arbitrary mobile apps.** App developers that don't consume the system trust store (Android API 24+ apps without `network_security_config.xml`, custom-pinned-cert apps) must be addressed by app distribution, not by this spec.

## Acceptance Criteria

- [ ] CA private key is deterministically derived from the Conductor Seed via HKDF as specified; same seed produces same CA across reinstalls
- [ ] CA cert includes X.509 Name Constraints restricting issuance to the conductor's published hostnames only
- [ ] Leaf certs are issued for each conductor-served hostname with 90-day validity, auto-rotated
- [ ] QR-code install ceremony at `/trust/<token>` works on macOS / Windows / Linux / iOS / Android browsers
- [ ] iOS install ceremony explicitly walks the user through the two-step trust-enable flow with screencast
- [ ] Android install ceremony succeeds for browser surfaces; documents the user-CA-app limitation for any future native app
- [ ] DID document publishes the CA fingerprint, URL, and name-constraints scope as a `X509TrustAnchor` service entry
- [ ] Trust install is recorded as a Verifiable Credential signed by the conductor's DID; revocable from the dashboard
- [ ] Name Constraints enforcement verified: a malicious cert signed by the CA for `google.com` is rejected by every modern browser
- [ ] CA rotation: the conductor can roll the CA (advancing the HKDF salt) and the dashboard guides operators through re-installing on each device; old VC trust grants are revoked
- [ ] **TLS mode is operator-controlled** (`public-ca`, `local-ca`, `both`); switching modes is reversible and preserves existing trust grants
- [ ] **`local-ca` mode is fully functional even when public-CA paths are available** (no forced retirement of the local CA when LE DNS-PERSIST-01 + substrate integration ships)
- [ ] **`local-ca` mode operators can verify, via inspection of network traffic, that no LE / public-PKI requests are made by the conductor** (sovereignty mode is observable)

## Implementation Notes

- **CA software:** Don't roll cryptography. Use `cryptography` (Python) / `rcgen` (Rust) / `node-forge` (TS) for cert issuance. Name Constraints support is patchy in some libraries — verify the chosen library handles them correctly before relying on the safety property.
- **Key storage:** the CA private key is held only at issuance time; reconstruct from the seed each time a leaf is signed, then zero. The CA *cert* (public) is on disk; the CA *key* (private) is reconstructed from the seed on demand.
- **PWA for the install ceremony:** small, single-purpose, served from the conductor itself. Detects platform via User-Agent and presents the right CA file format and install instructions. Can be Medley-distributed (`medley install conductor-trust-installer`) for users who want to keep the install client around for re-trust on new devices.
- **iOS specifics:** the install profile is a `.mobileconfig` file containing the CA cert. Safari handles installation; the user must manually enable trust afterward. The PWA shows a video or animated demonstration of the trust-enable step — this is the highest-friction part of the install flow and deserves polish.
- **Android specifics:** the CA installs to the user CA store, which works for Chrome / Firefox / Edge browsers. A future native Maistro Android app must include a `network_security_config.xml` declaring trust for user-installed CAs scoped to the conductor's hostnames — OR ship the CA pinned in the app, OR use Cert Pinning APIs directly.
- **Substrate-mediated install (v3):** the substrate config (S-153) gains an optional `trust_distribution` block. When set, the conductor delegates CA-root delivery to the substrate's management plane and the QR ceremony is suppressed for devices already enrolled. Today: speculative; activate when an upstream substrate ships the feature.
- **TLS mode switching:** mode is read at startup and on SIGHUP. Switch from `public-ca` to `local-ca`: conductor stops requesting/serving public certs and serves only local-CA leaves. Switch from `local-ca` to `public-ca`: conductor begins requesting public certs (via substrate or its own ACME client); local-CA leaves remain valid for grace period until public certs arrive. `both` mode serves whichever chain validates for a given client request.
- **Sovereignty-mode posture:** in `local-ca` mode, the conductor must emit zero outbound requests to Let's Encrypt, ACME directories, OCSP responders, or CT logs as a result of TLS operations. Verifiable by tcpdump. Other outbound traffic (LLM calls, channel APIs) is unaffected; this constraint is about the trust chain, not all network egress.
- **Marketing copy this enables:** *"Not your keys, not your TLS. Maistro is the only personal-AI agent platform where you can run your own certificate authority for your own agent — anchored to the seed phrase you already wrote down."*

## Verification

- Generate a CA from a fresh seed; install on macOS Safari; visit `https://brigid.local`; cert validates, no warning.
- Wipe the host; restore from BIP39 phrase; verify the regenerated CA has the same SHA-256 fingerprint.
- On a device with the CA installed, visit a malicious cert that the CA was tricked into signing for `google.com` (test setup); verify the browser rejects it because of Name Constraints.
- Install on iOS via the install profile; verify the trust-enable step is required and the PWA explains it; verify validation works after enable.
- Install on Android Chrome; verify validation works in browser; verify a test app without `network_security_config.xml` opting in to user CAs *does not* trust the cert (documented as expected behavior).
- Issue a trust-install VC for a device; verify the VC appears in the dashboard; revoke it; verify the device is added to a revocation list.
- Rotate the CA via the dashboard; verify the new CA fingerprint differs; verify devices that had the old CA installed are prompted to re-install via push or board entry.
- **Mode switch test:** start in `public-ca`; switch to `local-ca`; verify zero LE / ACME / OCSP / CT-log outbound traffic via tcpdump; verify TLS connections still serve cleanly to devices that have completed the trust install ceremony.
- **Sovereignty observability:** run the conductor in `local-ca` mode for 24h; capture all outbound network traffic; verify no public-PKI endpoint appears in the destination set.
- Once a substrate makes a public-CA chain available for the same hostname (test setup), verify the operator can choose to switch (`public-ca`), stay (`local-ca`), or run both (`both`); none of the three options is forced.
