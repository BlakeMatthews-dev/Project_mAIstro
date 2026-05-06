---
id: S-153
title: "Networking & identity substrate — Tailscale recommended, mesh substrates pluggable"
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

Different operators have different constraints (corporate Tailscale ban, philosophical preference for self-hosting, single-machine offline use, existing Cloudflare account, existing ZeroTier network, etc.). The conductor must:

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
| **Public exposure** *(optional)* | A way to selectively expose specific endpoints to the public internet |

The conductor consumes these via:

- Listening on a configurable local socket (default: `127.0.0.1:<port>` or a Unix socket)
- Reading caller identity from a configurable header (default: `X-Conductor-Identity`, mapped from substrate-specific headers)
- Resolving peer conductors via a substrate-specific resolver (or a configured static list)

No conductor code is substrate-aware. Substrate-specific glue lives in `~/.conductor/substrate/<name>.toml` and is loaded by the wizard.

### Supported substrates

Four categories, eight implementations.

#### Mesh substrates (recommended class)

Mesh substrates collapse reachability + TLS + identity + peer connectivity into one decision. They're the right answer for a typical Conductor deployment.

| Substrate | Mesh | Internal TLS | Public Exposure | Identity | License | Hosting |
|---|---|---|---|---|---|---|
| **Tailscale** *(default-recommended)* | Yes (WireGuard) | `tailscale serve` (auto-LE for `*.ts.net`) | `tailscale funnel` | Tailscale headers (`Tailscale-User-Login`, etc.) | Client BSD; coord proprietary | Tailscale Inc. coordination |
| **Headscale** | Yes (Tailscale-protocol) | Same as Tailscale | Funnel-equivalent (or operator reverse-proxy) | Same as Tailscale | BSD-3 (full stack) | Self-hosted coordination |
| **NetBird** | Yes (WireGuard) | Self-signed or operator CA today; **auto-LE for internal mesh hostnames pending LE DNS-PERSIST-01 production GA** (announced 2026-02-18; staging live since late Q1 2026; production GA targeted Q2 2026 — i.e. by end of June 2026) **plus NetBird's downstream integration** | **Built-in Reverse Proxy (v0.65+, Feb 2026)** — auto-LE for *custom domains*, OIDC auth at the edge, path-based routing | OIDC headers (Keycloak / Auth0 / Authelia / Google / GitHub / etc.) | Apache-2 (full stack) | Self-hosted or NetBird Cloud |
| **ZeroTier** | Yes (Layer-2) | Self-managed (TLS terminates at conductor or sidecar) | Operator's reverse proxy on a ZT-connected gateway | **No native identity** — operator layers their own (S-149 challenge or app-layer auth) | BSL (client + controller) | Self-hosted controller or ZeroTier Central |

**A note on NetBird's Reverse Proxy:** since v0.65 (Feb 2026), NetBird's built-in reverse proxy combines the functions of Tailscale Serve (HTTPS termination), Tailscale Funnel (public exposure), and Cloudflare Access (auth at the edge) into one feature. This makes NetBird more capable than Tailscale for *public-facing* deployments — it can host a custom-domain HTTPS endpoint with OIDC auth out of the box. The remaining gap (auto-certs for internal peer hostnames, equivalent to `*.ts.net`) is gated on:

1. **Let's Encrypt DNS-PERSIST-01 production GA** — announced 2026-02-18 ([letsencrypt.org/2026/02/18/dns-persist-01](https://letsencrypt.org/2026/02/18/dns-persist-01)); staging environment live since late Q1 2026; production rollout targeted Q2 2026 (between now and end of June 2026). Currently testable via Pebble.
2. **NetBird's downstream adoption** — once LE production-GAs the challenge type, NetBird needs to ship integration. No public NetBird timeline yet.
3. **cert-manager support** — tracked in [cert-manager#8373](https://github.com/cert-manager/cert-manager/issues/8373), planned for late Q1 2026; relevant if NetBird's integration uses cert-manager under the hood.

Until that pipeline completes, NetBird operators wanting valid certs on internal mesh hostnames have three workarounds: (a) self-signed certs with operator-distributed root, (b) [mkcert](https://github.com/FiloSottile/mkcert) for a local-only CA, or (c) point internal hostnames at the public Reverse Proxy domain (which already works today).

The four mesh substrates differ on hosting (managed vs self-hosted), identity story (Tailscale account vs OIDC vs none), and license. Operators pick the one that fits their constraints; conductor code doesn't care.

#### Tunnel substrates

| Substrate | Reachability | TLS | Identity | Peer | Notes |
|---|---|---|---|---|---|
| **Cloudflare Tunnel** | Operator's hostname via `cloudflared` | Auto via Cloudflare | Cloudflare Access JWT (if configured) | Manual / via DID resolution | Easy public exposure; CF sees metadata. *Note:* operators using NetBird already have an equivalent Reverse Proxy and may not need a separate Cloudflare Tunnel substrate. |

#### Local-only substrates

| Substrate | Reachability | TLS | Identity | Peer | Notes |
|---|---|---|---|---|---|
| **LAN-only (mDNS)** | `<instance>.local` | Self-signed or [mkcert](https://github.com/FiloSottile/mkcert) | None native; S-149 keypair challenge at app layer | LAN broadcast | Same-network only |
| **Localhost-only** | `127.0.0.1` | Self-signed (or skipped) | Unix socket peer-cred (`SO_PEERCRED`) | N/A (single machine) | Always-available floor |

#### Manual

| Substrate | Notes |
|---|---|
| **Manual reverse-proxy** | Operator wires up Caddy / nginx / Traefik / something else; conductor accepts cleartext on `127.0.0.1` and trusts a configured identity header. |

### Why Tailscale is the recommended default

For a typical household / single-machine deploy with no prior infrastructure, Tailscale collapses four problems into one decision:

- HTTPS with auto-renewing certs
- Stable address (MagicDNS)
- Identity on every connection
- Mesh peering for federation

It also fails closed: until the operator runs `tailscale funnel`, the conductor is *unreachable from the public internet*. That's the right failure mode for an AI agent that holds credentials.

The wizard recommends it for first-time operators. Operators with constraints (corporate policy, self-hosting preference, existing ZT/NetBird network, want fully-OSS stack with public Reverse Proxy) see the alternatives in the same menu, with honest UX about what each provides.

**For operators who explicitly want a fully-OSS stack with public-facing Reverse Proxy capability:** NetBird is the strongest match — it provides everything Tailscale does *plus* a built-in equivalent of Cloudflare Tunnel, all under Apache-2. Internal-hostname auto-cert parity arrives once LE DNS-PERSIST-01 GA + NetBird integration ship; the spec should be revisited then.

### Setup wizard step

During S-139 setup, after the seed phrase ceremony:

```
? Network this conductor:

  Mesh substrates  (recommended; reachability + HTTPS + identity + peering)
  > Tailscale          managed coordination, simplest setup
    Headscale          self-hosted Tailscale-compatible coordination
    NetBird            open-source mesh + built-in public Reverse Proxy + OIDC
    ZeroTier           Layer-2 mesh; bring your own identity layer

  Tunnel substrates
    Cloudflare Tunnel  operator's domain via cloudflared

  Local-only
    LAN-mDNS           same-network reachable, self-signed cert
    Localhost-only     no network exposure (CLI / local dashboard only)

  Manual
    Bring-your-own     wire up reachability, TLS, and identity yourself
```

Every option produces a working conductor. The default highlight on Tailscale is a recommendation, not a gate. Selecting any of the four mesh substrates triggers the substrate-specific auth flow:

- **Tailscale / Headscale:** browser-based auth-key flow; Headscale prompts for `HEADSCALE_URL` first.
- **NetBird:** browser-based OIDC sign-in against the configured NetBird management URL (NetBird Cloud or self-hosted). If the operator wants public-facing endpoints, NetBird's Reverse Proxy is configured in the same flow with custom domain + auto-LE.
- **ZeroTier:** prompt for network ID + auth (operator authorizes the conductor in ZT Central or self-hosted controller); follow-up prompt for the identity layer the operator wants stacked on top (S-149 challenge, basic auth, or external IdP).

### Identity mapping (substrate-agnostic)

The conductor reads caller identity from a configured header set per substrate:

```toml
# ~/.conductor/substrate/tailscale.toml
identity_headers = ["Tailscale-User-Login"]
admin_match = { type = "group", value = "group:conductor-admin" }
user_match = { type = "group", value = "group:conductor-user" }

# ~/.conductor/substrate/netbird.toml
identity_headers = ["X-NetBird-User-Email", "X-Auth-Request-Email"]
admin_match = { type = "email", value = "blake@example.com" }
user_match = { type = "email-domain", value = "example.com" }
reverse_proxy = { enabled = true, public_domain = "brigid.example.com", oidc_provider = "keycloak" }

# ~/.conductor/substrate/zerotier.toml
# ZT has no native identity — conductor falls back to S-149 challenge
identity_mode = "keypair-challenge"
admin_pubkeys = ["<m/0' pubkey for admin>"]
user_pubkeys  = ["<derived child pubkey for user1>"]

# ~/.conductor/substrate/cloudflare.toml
identity_headers = ["Cf-Access-Authenticated-User-Email"]
admin_match = { type = "email", value = "blake@example.com" }
user_match = { type = "email-domain", value = "example.com" }
```

S-142's admin/user1 split is enforced *inside* the conductor against the substrate-attested identity. Tailscale and Headscale map cleanly to group ACLs; NetBird and Cloudflare to OIDC email/group claims; ZeroTier to S-149 keypair challenges since ZT itself is identity-blind.

### Public exposure (per substrate)

Some endpoints benefit from being publicly resolvable: the `did:web` document (S-152), the Lightning receive endpoint (S-151), an opt-in public message-board page.

| Substrate | Public-exposure mechanism |
|---|---|
| Tailscale | `tailscale funnel` per path |
| Headscale | Funnel-equivalent (or operator-fronted reverse proxy) |
| **NetBird** | **Built-in Reverse Proxy (v0.65+) per path — auto-LE for custom domain, OIDC at the edge** |
| ZeroTier | Operator's public reverse proxy on a ZT-connected gateway host |
| Cloudflare Tunnel | Native (the substrate IS public exposure); per-path Cloudflare Access policies |
| LAN-mDNS / Localhost-only | Not applicable; operator must add a substrate for public exposure |
| Manual | Operator's reverse proxy |

Dashboard configures public exposure per-endpoint. **Defaults: nothing is public.** Operator opts in.

### Ripple effects on existing specs

None of these are deletions — they're substrate-conditional defaults:

| Spec | When the substrate is a mesh option (TS / Headscale / NetBird / ZeroTier) | When the substrate is a tunnel / local-only / manual option |
|---|---|---|
| S-101 (Traefik dashboard route) | Not needed | Used as documented (or replaced by the substrate's TLS layer) |
| S-017 (Dashboard auth) | Substrate identity replaces oauth2-proxy + Keycloak | oauth2-proxy + Keycloak still applies (or substrate-specific equivalent) |
| S-018, S-019, S-024 | Replaced by substrate identity; not invoked | Required when substrate is identity-blind; **Agent Stronghold** uses the full Keycloak stack, **Agent Conductor** uses S-149 keypair challenge |
| S-115 (Agent-to-agent networking) | Default transport: substrate mesh | Default transport: DID-based discovery + mTLS (S-152 keypair) |
| S-114 (Collective Unconscious) | Trust handshake over mesh, paired with VCs from S-152 | Same handshake, transport over the configured tunnel/manual substrate |
| S-152 (DID + VC) | `did:web` hosted automatically by the substrate's HTTPS layer | `did:web` hosted by tunnel / operator's proxy, or `did:key`-only if no public surface |
| S-141 (Vault) | Substrate auth keys (Tailscale auth key, NetBird OIDC token, ZT API key) stored as vault entries | Same |
| S-139 (Setup wizard) | Adds substrate-specific auth step | Substrate menu offers all options |

### Security posture

- All conductor endpoints are non-public by default. A misconfigured conductor cannot accidentally be exposed to the public internet — it's not on the public internet without an explicit per-path opt-in.
- Mesh substrates provide end-to-end encryption between every member of the mesh. The conductor never accepts unencrypted connections.
- Identity is verified at the substrate layer, before bytes reach the conductor process — *except* for ZeroTier, where the conductor must enforce S-149 challenge at the application layer because ZT itself is identity-blind. The wizard surfaces this distinction in plain language.
- Substrate auth keys are scoped (single-use, ephemeral, or reusable, depending on the substrate). The wizard creates a single-use key for the install ceremony where possible; the conductor regenerates a longer-lived key for itself after first authentication.

## Acceptance Criteria

- [ ] Conductor's networking layer is implemented as a substrate abstraction; no conductor code references any specific substrate directly
- [ ] All eight substrates (Tailscale, Headscale, NetBird, ZeroTier, Cloudflare Tunnel, LAN-mDNS, localhost-only, manual) can be selected at setup time and reconfigured later without reinstall
- [ ] On Tailscale-paired install: dashboard reachable at `https://<instance>.<tailnet>.ts.net` within 60 seconds, with valid auto-issued cert
- [ ] On Headscale: identical UX with `HEADSCALE_URL` configured
- [ ] On NetBird with mesh-only access: dashboard reachable via NetBird MagicDNS within 60s of OIDC sign-in; admin/user1 mapping works against the configured IdP
- [ ] On NetBird with public Reverse Proxy: custom domain serves the dashboard with auto-issued LE cert and OIDC auth at the edge; non-OIDC-authenticated requests refused before reaching the conductor
- [ ] On ZeroTier: dashboard reachable on ZT IP; admin authenticates via S-149 keypair challenge; non-ZT-member machines cannot connect
- [ ] On Cloudflare Tunnel: dashboard reachable via operator's hostname; identity flows from CF Access headers when configured
- [ ] On LAN-mDNS: dashboard reachable at `<instance>.local`; admin authenticates via S-149 keypair challenge
- [ ] On localhost-only: dashboard reachable on `127.0.0.1`; admin authenticated via Unix socket peer credentials
- [ ] On manual mode: documented configuration produces a working deployment with operator-supplied reverse-proxy and identity headers
- [ ] Substrate switch is recoverable: an operator can move between any pair of substrates by editing the config and restarting; conductor picks up the change
- [ ] No substrate is required for the conductor to start; localhost-only is always a valid configuration

## Implementation Notes

- **Tailscale integration:** prefer `tailscaled` as a sidecar (installed via the platform's package manager), controlled via the `tailscale` CLI and LocalAPI socket. Avoids embedding a Go runtime in a polyglot tree. `tsnet` (embedded library) remains an option for single-binary distributions.
- **Headscale integration:** same as Tailscale; the only difference is the coordination URL. Documented as a one-line config change, not a separate code path.
- **NetBird integration:** install via NetBird's distribution channels (Debian/RPM packages, Homebrew, MSI). Conductor consumes NetBird's gateway-injected OIDC headers; identity mapping uses standard email/group claims. Self-hosted NetBird Management Service is the open-source path; NetBird Cloud is the managed-service equivalent. **The Reverse Proxy is configured via NetBird's API** — conductor wizard offers to set it up automatically when the operator selects a public-facing deployment. **Internal-mesh-hostname auto-LE certs are blocked on the LE DNS-PERSIST-01 → NetBird integration pipeline** described above; revisit this spec when production GA ships (target end of Q2 2026). Until then, internal mesh access uses self-signed, mkcert, or operator-CA certs.
- **ZeroTier integration:** install ZT One via official packages. ZT is identity-blind — the conductor adds S-149 challenge as the identity layer at the app level. Documented warning: operators using ZT must understand they're getting transport + reachability + peering, not identity.
- **Cloudflare Tunnel integration:** ship a Medley plugin `medley install cloudflare-tunnel` that wraps `cloudflared` with our config conventions. *Note for NetBird operators:* the Reverse Proxy already covers this functionality; CF Tunnel is redundant.
- **Identity header parsing:** the conductor's HTTP middleware reads identity from the configured header list and maps to admin / user1 per the substrate config file. Header trust requires the upstream substrate to actually set them; for manual and ZeroTier modes, operators must lock down the proxy / wrap with a challenge so untrusted clients cannot spoof headers (documented warning in setup).
- **Peer discovery for federation:** in absence of a mesh substrate, peer conductors are reached by resolving their `did:web` DID (S-152) which gives a service endpoint URL. The DID's signing key authenticates the channel via mTLS or in-band signed handshake.
- **Localhost-only is the floor.** Even with no substrate configured, the conductor must run, be usable by the local user via CLI / browser to `127.0.0.1`, and refuse all remote connections. Network exposure is opt-in.

## Verification

- Fresh install with substrate = Tailscale: dashboard accessible from any tailnet device in under 60s; non-tailnet devices cannot connect at all.
- Fresh install with substrate = Headscale: same, against a self-hosted coordination server.
- Fresh install with substrate = NetBird, mesh-only: dashboard accessible after OIDC sign-in; admin/user1 mapping resolves against the configured IdP's group claims.
- Fresh install with substrate = NetBird, with Reverse Proxy: custom-domain dashboard reachable from public internet; OIDC auth gate enforced before the conductor sees the request; auto-LE cert valid.
- Fresh install with substrate = ZeroTier: dashboard accessible at the conductor's ZT IP from another ZT member; admin proves identity by signing a challenge with the S-149 `m/0'` key; non-ZT-member machine cannot reach the conductor.
- Fresh install with substrate = Cloudflare Tunnel: dashboard accessible via configured hostname; CF Access JWT validated; operator without CF Access bypassed (with explicit admin warning).
- Fresh install with substrate = LAN-only: `<instance>.local` reachable from same LAN; admin proves identity by signing a challenge with the S-149 `m/0'` key.
- Fresh install with substrate = localhost-only: dashboard at `127.0.0.1`; remote browsers refused at the socket layer.
- Substrate switch: change config from Tailscale to NetBird; restart conductor; dashboard now reachable via the new path; old tailnet path no longer responds.
- Pair two conductors on different mesh substrates (one Tailscale, one NetBird): federation works via S-152 DID-based peer discovery + mTLS, since they're not on the same mesh.

## References

- Let's Encrypt DNS-PERSIST-01 announcement (2026-02-18): [letsencrypt.org/2026/02/18/dns-persist-01](https://letsencrypt.org/2026/02/18/dns-persist-01)
- cert-manager DNS-PERSIST-01 issue (planned late Q1 2026): [cert-manager#8373](https://github.com/cert-manager/cert-manager/issues/8373)
- NetBird public endpoint / LetsEncrypt request: [netbirdio/netbird#2375](https://github.com/netbirdio/netbird/issues/2375)
- NetBird internal HTTPS certs proposal: [netbirdio/netbird#5479](https://github.com/netbirdio/netbird/issues/5479)
