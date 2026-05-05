---
id: S-153
title: "Networking & identity substrate — Tailscale by default, pluggable"
domain: infra
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-153: Networking & Identity Substrate

## Problem

Agent Conductor needs all of:

- HTTPS for the dashboard, the Lightning address (S-151), the DID document (S-152), the message board
- Stable, resolvable addressing across reboots and IP changes
- Mesh networking between conductors for federation (S-114, S-115)
- Identity-verified connections (who is making this request?)
- Access control distinguishing admin from user1 (S-142)

Different operators have different constraints (corporate Tailscale ban, philosophical preference for self-hosting, single-machine offline use, existing Cloudflare account, etc.). The conductor must:

1. **Work out of the box for the easy case** — a typical household operator should reach a working HTTPS dashboard in under five minutes with one decision.
2. **Not require any specific vendor** — the conductor's core must function on top of any substrate that provides reachability, TLS, and per-request identity.
3. **Make the abstraction explicit** — substrate is a swappable layer, not a hardwired dependency.

## Solution

Define the conductor's networking as a **substrate abstraction**. The conductor exposes its HTTP service on a localhost socket. Substrates connect that socket to the outside world and tell the conductor who is calling.

### The substrate contract

A networking substrate provides:

| Capability | What it means |
|---|---|
| **Reachability** | Some externally-resolvable address pointing at the conductor's local HTTP socket |
| **Transport security** | TLS termination with a valid cert (or N/A for localhost-only) |
| **Identity attestation** | A way for the conductor to learn the verified identity of the caller on each request |
| **Peer connectivity** *(optional)* | A way for two conductors to reach each other directly for federation |

The conductor consumes these via:

- Listening on a configurable local socket (default: `127.0.0.1:<port>` or a Unix socket)
- Reading caller identity from a configurable header (default: `X-Conductor-Identity`, mapped from substrate-specific headers)
- Resolving peer conductors via a substrate-specific resolver (or a configured static list)

No conductor code is substrate-aware. Substrate-specific glue lives in `~/.conductor/substrate/<name>.toml` and is loaded by the wizard.

### Supported substrates

| Substrate | Reachability | TLS | Identity | Peer |
|---|---|---|---|---|
| **Tailscale (default-recommended)** | MagicDNS: `<instance>.<tailnet>.ts.net` | Automatic via Tailscale's Let's Encrypt | Tailscale headers (`Tailscale-User-Login`, etc.) | Mesh; automatic |
| **Headscale** | Same as Tailscale, self-hosted coord server | Same | Same | Same |
| **Cloudflare Tunnel** | Operator's hostname via `cloudflared` | Auto via Cloudflare | Cloudflare Access JWT (if configured) | Manual / via DID resolution |
| **LAN-only (mDNS)** | `<instance>.local` | Self-signed or [mkcert](https://github.com/FiloSottile/mkcert) | None native; conductor falls back to S-149 keypair challenge at app layer | LAN broadcast |
| **Localhost-only** | `127.0.0.1` | Self-signed (or skipped) | Unix socket peer-cred (`SO_PEERCRED`) | N/A (single machine) |
| **Manual reverse-proxy** | Operator's domain via Caddy / nginx / Traefik | Operator's responsibility | Whatever the proxy injects (`Forwarded`, `X-Auth-Request-User`, etc.) | Manual |

**Tailscale is the *recommended default*, not a requirement.** Operators choose their substrate at install time; the choice is reversible.

### Why Tailscale is the recommended default

For a typical household / single-machine deploy, Tailscale collapses four otherwise-separate problems into one decision:

- HTTPS with auto-renewing certs (`tailscale serve`)
- Stable address (MagicDNS)
- Identity on every connection (no oauth2-proxy, no Keycloak)
- Mesh peering for federation (no port-forwarding, no DDNS)

It also fails closed by default: until the operator runs `tailscale funnel`, the conductor is *unreachable from the public internet*. That's the right failure mode for an AI agent that holds credentials.

For operators who can't or won't use Tailscale Inc.'s coordination server, **Headscale** (open-source, self-hosted) provides the identical UX. The wizard treats it as a sibling option, not an obscure flag.

### Setup wizard step

During S-139 setup, after the seed phrase ceremony:

```
? Network this conductor:
  > Tailscale  (recommended; works out of the box)
      → Sign in with Tailscale to add this conductor to your tailnet.
      → HTTPS, identity, and federation are configured automatically.
  
    Headscale  (self-hosted, same UX)
      → Enter HEADSCALE_URL: ____
  
    Cloudflare Tunnel
      → Enter your Cloudflare account / tunnel ID.
  
    LAN-only (mDNS)
      → Reachable from this network only. Self-signed cert.
  
    Localhost-only
      → No network exposure. CLI / local dashboard only.
  
    Manual / bring-your-own
      → You'll wire up reachability, TLS, and identity yourself.
         The conductor listens on 127.0.0.1:<port> and trusts a header you configure.
```

Every option produces a working conductor. The default highlight on Tailscale is a recommendation, not a gate.

### Identity mapping (substrate-agnostic)

The conductor reads caller identity from a configured header set per substrate:

```toml
# ~/.conductor/substrate/tailscale.toml
identity_headers = ["Tailscale-User-Login"]
admin_match = { type = "group", value = "group:conductor-admin" }
user_match = { type = "group", value = "group:conductor-user" }

# ~/.conductor/substrate/cloudflare.toml
identity_headers = ["Cf-Access-Authenticated-User-Email"]
admin_match = { type = "email", value = "blake@example.com" }
user_match = { type = "email-domain", value = "example.com" }
```

S-142's admin/user1 split is enforced *inside* the conductor against the substrate-attested identity. This means:

- Tailscale ACLs map cleanly (group memberships)
- Cloudflare Access policies map cleanly (email + group claims)
- LAN/manual modes require an explicit admin password / signed challenge as the fallback identity proof (still satisfying "admin is verified before being trusted")

### Tailscale Funnel for explicit public exposure

When the substrate is Tailscale, some endpoints benefit from being publicly resolvable:

- The `did:web` document (S-152) so external parties can verify VCs
- The Lightning receive endpoint (S-151) for tips
- A specific public message-board page if the operator chooses to share

Dashboard configures `tailscale funnel` per-endpoint. Defaults: all unchecked. Equivalent functionality on other substrates: Cloudflare Tunnel public hostname; manual reverse-proxy public path.

### What this changes elsewhere

None of these are deletions — they're substrate-conditional defaults:

| Spec | When the substrate is Tailscale | When the substrate is something else |
|---|---|---|
| S-101 (Traefik dashboard route) | Not needed | Used as documented (or replaced by the substrate's TLS layer) |
| S-017 (Dashboard auth) | Tailscale identity replaces oauth2-proxy + Keycloak | oauth2-proxy + Keycloak still applies (or substrate-specific equivalent) |
| S-115 (Agent-to-agent networking) | Default transport: tailnet mesh | Default transport: DID-based discovery + mTLS (S-152 keypair) |
| S-152 (DID + VC) | `did:web` hosted automatically by Tailscale Serve | `did:web` hosted by whichever substrate exposes the conductor's HTTPS endpoint, or `did:key`-only if no public surface |
| S-139 (Setup wizard) | Adds a one-click Tailscale step | Substrate menu offers all options as peers |

## Acceptance Criteria

- [ ] Conductor's networking layer is implemented as a substrate abstraction; no conductor code references Tailscale directly
- [ ] All listed substrates can be selected at setup time and reconfigured later without reinstall
- [ ] On Tailscale-paired install: dashboard reachable at `https://<instance>.<tailnet>.ts.net` within 60 seconds, with valid auto-issued cert
- [ ] On Headscale: identical UX with `HEADSCALE_URL` configured
- [ ] On Cloudflare Tunnel: dashboard reachable via operator's hostname; identity flows from Cf-Access headers
- [ ] On LAN-only mDNS: dashboard reachable at `<instance>.local`; admin authenticates via S-149 keypair challenge
- [ ] On localhost-only: dashboard reachable on `127.0.0.1`; admin authenticated via Unix socket peer credentials
- [ ] On manual mode: documented configuration produces a working deployment with operator-supplied reverse-proxy and identity headers
- [ ] Substrate switch is recoverable: an operator can move from Tailscale to Cloudflare Tunnel (or vice versa) by editing the substrate config; the conductor picks up the change on restart
- [ ] No substrate is required for the conductor to start; localhost-only is always a valid configuration

## Implementation Notes

- **Tailscale integration:** prefer `tailscaled` as a sidecar (installed via the platform's package manager), controlled via the `tailscale` CLI and LocalAPI socket. Avoids embedding a Go runtime in a polyglot tree. `tsnet` (embedded library) remains an option for single-binary distributions.
- **Cloudflare Tunnel integration:** ship a Medley plugin `medley install cloudflare-tunnel` that wraps `cloudflared` with our config conventions. Optional for users who already have a Cloudflare account.
- **Identity header parsing:** the conductor's HTTP middleware reads identity from the configured header list and maps to admin / user1 per the substrate config file. Header trust requires the upstream substrate to actually set them — for manual mode, the operator must lock down the proxy so untrusted clients cannot spoof headers (documented warning in setup).
- **Peer discovery for federation:** in absence of a mesh substrate (Tailscale / ZeroTier), peer conductors are reached by resolving their `did:web` DID (S-152) which gives a service endpoint URL. The DID's signing key authenticates the channel via mTLS or in-band signed handshake.
- **Localhost-only is the floor.** Even with no substrate configured, the conductor must run, be usable by the local user via CLI / browser to `127.0.0.1`, and refuse all remote connections. Network exposure is opt-in.

## Verification

- Fresh install with substrate = Tailscale: dashboard accessible from any tailnet device in under 60s; non-tailnet devices cannot connect at all.
- Fresh install with substrate = Headscale: same, against a self-hosted coordination server.
- Fresh install with substrate = Cloudflare Tunnel: dashboard accessible via configured hostname; CF Access JWT validated; operator without CF Access bypassed (with explicit admin warning).
- Fresh install with substrate = LAN-only: `<instance>.local` reachable from same LAN; admin proves identity by signing a challenge with the S-149 `m/0'` key.
- Fresh install with substrate = localhost-only: dashboard at `127.0.0.1`; remote browsers refused at the socket layer.
- Substrate switch: change config from Tailscale to Cloudflare Tunnel; restart conductor; dashboard now reachable via the new path; old tailnet path no longer responds.
