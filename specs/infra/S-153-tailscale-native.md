---
id: S-153
title: "Tailscale-native networking, identity, and access control"
domain: infra
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: "S-101 (Traefik for dashboard) for Conductor lite mode; partially supersedes S-017 dashboard auth for lite mode"
---

# S-153: Tailscale-native networking

## Problem

Agent Conductor needs all of:

- HTTPS for the dashboard, the Lightning address, the DID document (S-152), the message board
- Stable, resolvable addressing across reboots and IP changes
- Mesh networking between conductors for federation (S-114, S-115)
- Identity-verified connections (who is making this request?)
- Access control distinguishing admin from user1 (S-142)

The traditional stack — Traefik + oauth2-proxy + Keycloak + DDNS + Let's Encrypt + WireGuard + ACL config — is the heavy answer. It's the right answer for **Agent Stronghold** (multitenant). It's the wrong answer for **Agent Conductor** (lite/household). We need all of those properties with one decision and zero new services.

## Solution

**Adopt Tailscale as the default networking and identity substrate for Agent Conductor.** Either embed `tsnet` (Tailscale's library) inside the conductor or install `tailscaled` as a sidecar; either way, the conductor brings its own Tailscale node and joins the operator's tailnet on first run.

### What Tailscale gives us, in one bundle

| Need | Tailscale provides |
|---|---|
| HTTPS by default | `tailscale serve` issues + auto-renews Let's Encrypt certs |
| Stable address | `<instance-name>.<tailnet>.ts.net` (MagicDNS) |
| Mesh networking | WireGuard tunnels between every device on the tailnet |
| Identity on connections | Each request carries verified Tailscale identity (`X-Tailscale-User`, etc.) |
| Access control | Tailscale ACLs in JSON; can restrict conductor to specific users/groups |
| Public exposure | `tailscale funnel` exposes specific endpoints to the open internet, opt-in |
| NAT traversal | Built-in; works behind CGNAT, double-NAT, etc. |
| Federation transport | Two conductors on connected tailnets reach each other directly |

For Conductor lite, this **replaces** Traefik (S-101 not needed), oauth2-proxy + Keycloak (S-017 not needed), DDNS, manual certificate management, and most of S-115's transport story.

### Setup wizard step

During S-139 setup, after the seed phrase (S-149) ceremony:

```
? Network this conductor:
  > Sign in with Tailscale (recommended)
      ✓ HTTPS-by-default with auto-renewing certs
      ✓ Access control via your tailnet ACLs
      ✓ Federate with other conductors via mesh
    Use Headscale (self-hosted coordination)
      → Enter HEADSCALE_URL: ____
    Skip — I'll configure networking manually
      ⚠ You'll be responsible for HTTPS, access control, and reachability.
      ⚠ Some features (federation, did:web identity, public Lightning address)
        will require manual configuration.
```

Signing in with Tailscale opens the standard auth-key flow in the user's browser; the conductor receives an auth key, joins the tailnet, and registers under a chosen instance name.

### Access control mapping

Tailscale ACLs map cleanly to S-142's admin/user1 model:

```json
{
  "groups": {
    "group:conductor-admin": ["blake@example.com"],
    "group:conductor-user":  ["lilly@example.com", "bella@example.com"]
  },
  "acls": [
    { "action": "accept",
      "src": ["group:conductor-admin"],
      "dst": ["tag:conductor:443", "tag:conductor:8080"] },
    { "action": "accept",
      "src": ["group:conductor-user"],
      "dst": ["tag:conductor:443"] }
  ]
}
```

The conductor checks the Tailscale identity on each incoming request via `tailscale whois` (or the equivalent header from `tailscale serve`). Member of `group:conductor-admin` → admin role; member of `group:conductor-user` → user1 role; not on the tailnet → connection refused at the WireGuard layer (never reaches the conductor process).

This is the one-time setup that replaces the entire JWT + Keycloak + oauth2-proxy stack for lite-mode deployments.

### Tailscale Funnel for explicit public exposure

Some things benefit from being publicly resolvable:

- The `did:web` document (S-152) so external parties can verify VCs
- A public Lightning address for tips (S-151)
- A public message board page if the operator chooses to share one

`tailscale funnel` exposes specific paths at the same URL, while everything else stays tailnet-private. Configurable per-endpoint via the dashboard:

```
[ ] /.well-known/did.json     — expose to public internet?
[ ] /lnurlp/<address>          — expose Lightning receive endpoint?
[ ] /board/public              — expose specific board posts?
```

Defaults: all unchecked. Operator opts in per endpoint.

### Headscale escape hatch

[Headscale](https://github.com/juanfont/headscale) is an open-source, self-hostable coordination server compatible with Tailscale clients. The conductor must work against either:

- Default: Tailscale Inc.'s coordination server (`controlplane.tailscale.com`)
- Self-hosted: `HEADSCALE_URL` env var or wizard input

Same UX, no Tailscale Inc. dependency. This is the answer for users who can't (corporate policy) or won't (philosophy) use the hosted service. Documented as a first-class alternative, not a hidden flag.

### Ripple effects on existing specs

| Spec | Effect |
|---|---|
| S-101 (Traefik dashboard route) | **Superseded for Conductor lite**; still applies to Stronghold |
| S-017 (Dashboard auth) | **Lite variant** uses Tailscale identity instead of oauth2-proxy + Keycloak |
| S-018, S-019, S-024 (JWT, Keycloak, OpenWebUI passthrough) | **Stronghold-only** for these as default; Conductor lite uses Tailscale identity |
| S-115 (Agent-to-agent networking) | **Default transport: tailnet**; conductor-to-conductor over WireGuard |
| S-114 (Collective Unconscious) | **Trust handshake over tailnet**, paired with VCs from S-152 |
| S-152 (DID + VC) | **`did:web` default uses Tailscale Serve** for hosting `did.json` |
| S-141 (Vault) | **Tailscale auth key** stored as a vault entry; consumed at conductor startup |
| S-139 (Setup wizard) | **Adds Tailscale step** between seed phrase and channel configuration |

None of the existing specs are deleted; the lite-mode default just changes. Stronghold-mode operators retain the full Keycloak / oauth2-proxy / Traefik stack.

### Security posture

- All conductor endpoints are tailnet-private by default. A misconfigured conductor cannot accidentally be exposed to the public internet — it's not on the public internet without an explicit `tailscale funnel` for a specific path.
- WireGuard provides end-to-end encryption between every device on the tailnet. The conductor never accepts unencrypted connections.
- Identity is verified at the WireGuard layer, before bytes reach the conductor process. A non-tailnet attacker cannot make the conductor parse their HTTP request.
- Tailscale auth keys are scoped (single-use, ephemeral, or reusable, with optional tag-locking). The wizard creates a single-use key for the install ceremony; the conductor regenerates a longer-lived key for itself after first authentication.

## Acceptance Criteria

- [ ] Setup wizard offers: Tailscale (default), Headscale (self-hosted), or manual
- [ ] On Tailscale-paired install, conductor is reachable at `https://<instance>.<tailnet>.ts.net` within 60 seconds of completing the wizard
- [ ] HTTPS certificate is valid, auto-issued by Tailscale, no operator action required
- [ ] Incoming request identity is verified before reaching the conductor process; non-tailnet sources cannot connect
- [ ] Tailscale group membership maps to admin / user1 roles per S-142
- [ ] `tailscale funnel` configurable per-endpoint via dashboard; defaults are private
- [ ] Headscale path: setting `HEADSCALE_URL` produces an identical UX with the self-hosted coordination server
- [ ] Conductor-to-conductor federation (S-115) over tailnet works without additional configuration when both conductors are on the same or peered tailnets
- [ ] Tailscale auth key is held in S-141's vault; never on disk in cleartext
- [ ] Manual fallback (no Tailscale) is documented and tested; user retains the option but loses default reachability features

## Implementation Notes

**Two viable integration patterns:**

1. **`tsnet` embedded** — Tailscale's Go library compiled into the conductor binary. Cleanest UX (one process), but requires Go in the build. If Conductor's main runtime is Python or TypeScript (per project_maistro’s polyglot tree), this means a Go sidecar.
2. **`tailscaled` sidecar** — standard Tailscale daemon installed by the wizard via the platform's package manager (`apt`, `brew`, `winget`); conductor controls it via `tailscale` CLI and the LocalAPI socket. Slightly more moving parts; familiar to anyone who has Tailscale installed.

Recommended default: **option 2** (sidecar). Lower complexity for the build, uses signed binaries from Tailscale's own distribution, and operators who already have Tailscale running will see their conductor join their existing tailnet rather than spawning a parallel node.

- Identity on incoming requests via `tailscale whois <ip>:<port>` or the headers Tailscale Serve injects (`Tailscale-User-Login`, `Tailscale-User-Profile-Pic`, etc.).
- Outbound peer connections: use the tailnet hostname directly; Tailscale's Magic DNS resolves it.
- Cert location: Tailscale Serve manages cert files in its own state dir; conductor doesn't need to handle them.
- Container deployments (S-148): the Podman variant runs `tailscaled` inside the container with `--tun=userspace-networking` for kernel-module-free operation.

## Verification

- Fresh install on a new machine, sign in with Tailscale during wizard → dashboard accessible at `https://<chosen-name>.<tailnet>.ts.net` within 60s.
- Cert is valid (no browser warning).
- An admin tailnet member can reach the dashboard; a non-tailnet device cannot connect at all.
- Admin can configure `tailscale funnel` for `/.well-known/did.json` only; verifying from a non-tailnet device shows the DID document but not the dashboard.
- Set `HEADSCALE_URL=...`; repeat the install → same UX, conductor joins the Headscale server instead.
- Pair two conductors on the same tailnet; verify federation transport (S-115) works without port-forwarding or additional configuration.
