---
id: SPEC-012
title: "Admin / user1 privilege separation — mandatory two-tier model"
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
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# S-142: Admin / user1 Privilege Separation

## Problem

The philosophy doc (`specs/security/PHILOSOPHY.md`) commits us to operating systems' lesson: "Windows doesn't run apps as Administrator. Linux requires sudo. Why does your AI agent default to root?" The dominant pattern in personal-AI-agent platforms is single-user-as-root, and Cisco found this in production — a third-party OpenClaw skill performed undisclosed data exfiltration because the agent ran with the user's full privilege.

The defense has to be structural, not behavioral. Asking the agent to be careful is asking the model to enforce its own constraints; that fails under prompt injection. The only defense that holds is making single-user-as-root *impossible to construct*.

## Solution

**Two-tier privilege model, mandatory at install time:**

- **`admin`** — holds the Conductor Seed (S-149), signs elevation approvals, edits capability whitelists, rotates secrets in the vault (S-141), promotes plugin trust tiers (S-037). Annoying for daily use; that's the point.
- **`users`** (1..N) — day-to-day interaction with the conductor. Cannot construct privileged AgentSpecs. Cannot read or modify the vault. Cannot promote skills past `untrusted`. Privileged operations route through admin via human-in-the-loop signing.

The wizard flow does not produce a working install with one user. The structural property is enforced at construction time, not at runtime.

### Setup wizard flow (the enforcement)

The wizard for S-139 does not say "refused" if the operator skips user creation — the flow simply doesn't have a path that produces a single-user install:

```
Step 1.  Name your conductor                    → "Brigid", "Atelier", "Maestro Junior"
Step 2.  Generate Conductor Seed                → BIP39 24 words (S-149); recovery card; SLIP39 optional
Step 3.  Create admin                           → password (passphrase-style, for keychain unlock fallback)
                                                  + admin keypair (from S-149 m/0')
                                                  + admin recovery card
Step 4.  Create user one                        → required, not optional; cannot click past without filling
Step 5.  "Anyone else in your household?"       → invitation, not a gate
         [+ add user] [continue]                  add 0..N additional users
Step 6+. Network, TLS, channels, LLM, etc.      → the rest of S-139
```

Step 4 is the load-bearing step. It is required to advance. There is no `--skip-user` flag, no environment variable, no headless workaround. The wizard's Step 4 form does not have a "continue with no users" button.

### Capability envelope construction

Builds on S-002–S-005:

- An `AgentSpec` is constructed with a verified identity — either `admin` *or* one of the registered users, never both, never neither.
- The spec's tool whitelist is keyed on the user's role (admin / user / specific named user). Admin-only tools cannot appear in a user-keyed envelope; the constructor refuses.
- Heartbeat / reactor-spawned tasks (S-105, S-143) run as a specific user, not as admin. Background work has the same capability ceiling as live chat from that user.
- Cross-conductor federation messages (S-156) carry the *issuing user* identity; the receiving conductor maps it to a local user via federation trust VCs (S-152).

### Elevation flow (when a user needs an admin-only operation)

```
user1 → conductor: "please delete /home/blake/Documents/old/"
  conductor: this requires file_ops.delete on a user-owned path
             user1's envelope grants file_ops.read but not file_ops.delete
             → elevation request queued
  
  Dashboard / Console (S-016) shows admin a structured prompt:
    ┌─ Elevation request ─────────────────────────────────┐
    │ user1 → file_ops.delete                              │
    │ path: /home/blake/Documents/old/                       │
    │ size: ~12GB recursive                                  │
    │ reason: "clean up old project files"                   │
    │ [ Sign in wallet → ]  [ Decline ]                       │
    └──────────────────────────────────────────────────────┘
  
  Tap → push notification to admin's wallet app (Phoenix/Mutiny/Zeus)
  Admin biometric-signs via BIP-322 (S-150 mode 3, S-151)
  Signature returns to conductor; recorded as VC (S-152)
  Operation proceeds; result logged.
```

The signing surface is the same one S-151 uses for crypto operations. Admin's mental model: *"things that need my approval show up in my wallet."* Same UX whether the request is "send 1000 sats" or "delete this directory."

Three elevation modes:

- **Inline ask (default)** — admin signs each operation individually, push notification each time.
- **Time-boxed delegation** — admin grants a scope ("file_ops.delete on /home/blake/old/*") for a duration (15 min, 1 hour). Auto-revokes at expiry. Useful for batch operations.
- **Pre-approved by policy** — admin signs a policy VC ("user1 may delete files in their own home directory under 1GB without elevation"). Conductor enforces it without further prompts. Policy VCs are signed and revocable; auditable like everything else.

### Identity attestation

Users are identified to the conductor via the substrate (S-153):

- **Tailscale / Headscale:** Tailscale ACL group membership maps to admin / user.
- **NetBird / Cloudflare Tunnel:** OIDC email maps to user identity per `~/.conductor/users.toml`.
- **ZeroTier / LAN-mDNS / localhost-only:** S-149 keypair challenge — each user has their own derived keypair under `m/44'/9000'/<user-index>'`; users authenticate by signing a challenge.
- **Manual reverse-proxy:** operator's proxy injects identity headers; conductor trusts what the proxy attests.

In every case the conductor refuses to start without at least an admin and one user provisioned in `~/.conductor/users.toml`.

### `~/.conductor/users.toml`

```toml
[admin]
pubkey = "<m/0' public key, hex>"
email  = "blake@example.com"               # for OIDC substrates
tailnet_login = "blake@github"             # for Tailscale

[[user]]
name = "lilly"
pubkey = "<m/44'/9000'/1' public key>"
email = "lilly@example.com"
tailnet_login = "lilly@github"
role = "user"

[[user]]
name = "bella"
pubkey = "<m/44'/9000'/2' public key>"
role = "user"
```

The file is admin-signed (each entry has a signature from the admin keypair). Mutations require admin signature; the conductor refuses to load a `users.toml` that doesn't validate.

## Acceptance Criteria

- [ ] Setup wizard (S-139) is structurally incapable of completing with fewer than two users (admin + at least one named user)
- [ ] No CLI flag, environment variable, or undocumented path produces a single-user install
- [ ] `users.toml` is admin-signed; conductor refuses to start with an invalid signature
- [ ] AgentSpec construction validates the user identity against `users.toml`; admin-only tools reject user-keyed envelopes
- [ ] Elevation flow: user proposes → admin signs in wallet → operation proceeds; round-trip latency under 30s on a typical mobile push
- [ ] Time-boxed delegation: admin grants a 15-min scope; user operates without prompts within scope; auto-revokes at expiry
- [ ] Policy VCs: admin signs a standing policy; auditable + revocable; user operates within policy without per-call prompts
- [ ] Audit log records every elevation (granted, declined, expired, revoked) as a signed VC (S-152)
- [ ] Heartbeat / reactor-spawned tasks (S-143) run as a specific user, not as admin; verified by trace inspection
- [ ] Federation peers (S-156) cannot impersonate admin; cross-conductor admin-only operations require local-admin signature
- [ ] Admin key rotation invalidates all active elevation grants: when the admin rotates their `m/0'` keypair (S-149), all active time-boxed delegation scopes and policy VCs are revoked atomically; subsequent requests citing a grant signed by the previous key are rejected with `GRANT_KEY_MISMATCH`; no manual per-grant revocation is required after rotation

## Implementation Notes

- **Two-tier, not RBAC.** This is deliberately not a full RBAC system with roles like "editor" / "viewer." Admin and user are the only built-in tiers. Operators who want finer-grained control use Medley plugins or define custom AgentSpec roles in code.
- **User identity derivation:** users 1..N derive their identity keypairs from `m/44'/9000'/<user-index>'` on the Conductor Seed. The seed is the operator's; admin signs each user's keypair into existence at wizard time.
- **Wallet-app signing surface:** elevation prompts and crypto operations (S-151) share the same BIP-322 signing protocol. One mental model.
- **Default-deny everywhere:** any tool not explicitly in the user's whitelist is unavailable. New tools added to the codebase don't auto-appear in user envelopes; they require explicit grant.
- **No "sudo timestamp":** time-boxed delegation is opt-in per scope, signed, and recorded. There is no implicit "admin signed in the last 5 minutes so we'll let this slide" — every elevation is structured.
- **Composition with S-141 vault:** vault mutations require admin signature; user-keyed AgentSpecs can read via `secrets.use()` only for credentials the admin has granted them via policy VC.
- **Daily-driver UX:** admin should be able to grant common time-boxed scopes from the Console with one tap ("15-min file edit window for user1") to reduce friction without compromising the structural property.
- **Grant invalidation on key rotation:** each active grant (time-boxed scope + policy VC) stores the admin public key that signed it. On startup and on key rotation, conductor validates all active grants against the current `admin.pub`; any grant signed by a different key is revoked atomically and logged. This ensures a stolen-device recovery does not leave any pre-rotation grants valid.

## Verification

- Setup-wizard install flow: attempt to skip Step 4 → form does not advance; verify with browser automation.
- Run conductor with a hand-edited `users.toml` containing only admin → conductor refuses to start with a clear error.
- AgentSpec construction test: attempt to construct a user-keyed envelope with admin-only tool whitelist → constructor raises.
- Elevation round-trip test: user requests file_ops.delete; admin's mobile wallet receives push within 5s; signs; operation proceeds; verify audit-log VC.
- Time-boxed scope test: admin grants 15-min file-ops scope to user1; user1 operates 14 min without prompts; at min 16 next operation requires a fresh elevation.
- Heartbeat test: reactor-spawned task triggers; verify trace shows user identity, not admin; verify the task cannot perform admin-only operations.
- Stolen-device drill: assume admin's wallet device is compromised; admin uses the recovery seed to rotate the m/0' key; verify all existing time-boxed scopes and policy VCs are revoked atomically; verify that presenting a previous grant signature returns `GRANT_KEY_MISMATCH`; verify new elevation requests with the new key work normally.
