---
id: S-138
title: "Agent Conductor — the household / personal product, sibling of Agent Stronghold"
domain: conductor
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-138: Agent Conductor

## Problem

The spec tree describes many components (S-022 Bouncer, S-141 vault, S-142 privilege separation, S-149 Conductor Seed, S-153 networking, etc.) but **never names the product they assemble into**. "Project mAIstro" is the studio / repo / umbrella; the user-facing product needs its own identity.

Without this spec:

- The setup wizard, README, install ceremony, and marketing copy have no canonical product name.
- The relationship to the larger multitenant SKU (Agent Stronghold) is implicit, not stated.
- The default deploy footprint, supported platforms, and defaults are scattered across other specs without a single "this is what you get" document.

## Solution

Name, scope, and define **Agent Conductor** as the household/personal product. Agent Stronghold is the multitenant platform built on the same runtime; the two SKUs share the hyperagent graph runtime (S-145) and the security primitives but diverge on deployment topology.

### Product lineup

```
project_mAIstro                          (the studio / repo)
  ├─ Agent Conductor                       (this spec)
  │     household / personal scale
  │     2–N users (admin + 1..N)
  │     single-machine or small cluster
  │     crypto / federation opt-in
  │
  └─ Agent Stronghold                      (separate spec set, future)
        multitenant platform
        many tenants × many users each
        clustered / cloud deploy
        Keycloak + Vaultwarden + Postgres in the substrate
```

**One runtime, two SKUs.** Both share the hyperagent graph runtime (S-145), the Bouncer (S-022), the capability envelope (S-002–S-005), the audit log (S-152), the Medley plugin model (S-037), the Conductor Seed root of trust (S-149). They diverge on default substrate, default secrets backend, and tenant-isolation surface.

### What Agent Conductor is

- An autonomous AI agent platform sized for a household, a small team, or a single power user.
- Multi-user by design (admin + 1..N users, S-142). Single-user-as-root is structurally impossible.
- Browser-first: setup wizard, ongoing dashboard, and trust-install ceremonies all live in the same web UI — the **Console** — with a CLI companion for power users and headless deploys.
- Sovereign by default: SQLite + sqlite-vec for state (S-140), age-encrypted vault unlocked by admin keypair for secrets (S-141), local CA from Conductor Seed for TLS (S-155). No external services *required* to operate.
- Pluggable on every layer the operator might want to swap: networking substrate (S-153), TLS root (S-155), secrets backend, LLM provider, plugin source.
- Crypto-optional (S-151). Lightning federation (S-156) is opt-in. The agent works fully without any crypto plugin installed.

### Default deploy footprint

| Resource | Target | Notes |
|---|---|---|
| RAM | 2 GB minimum, 4 GB recommended | Conductor process + SQLite + LDK if Lightning installed |
| Disk | 1 GB for the conductor; 60 GB if `medley install electrum-server` (S-154) | Pruned Bitcoin + electrs index for the Electrum plugin |
| CPU | 2 cores minimum | Reactor loop (S-143) is mostly I/O-bound |
| Network | Any internet connection; per-substrate requirements (S-153) | Tailscale recommended for substrate; localhost-only is the floor |

Supported platforms: Linux (systemd), macOS (launchd), Windows (Service). Each gets the hardened native install (S-147) by default, with optional Podman containerization (S-148) for operators who want filesystem isolation.

### Default configuration

These are the defaults the setup wizard (S-139) lands on if the operator clicks through with no overrides. Each is changeable; this list documents what "accepting defaults" produces.

| Layer | Default |
|---|---|
| Substrate | Tailscale (recommended), with menu of seven alternatives (S-153) |
| TLS mode | Public-CA via substrate (S-155 mode `public-ca`) |
| Vault backend | age-encrypted file unlocked by admin keypair from S-149; OS keychain holds the unlock key on desktop, passphrase fallback on headless Linux (S-141) |
| State storage | SQLite + sqlite-vec, single-writer pattern (S-140) |
| Identity | DID auto-generated: `did:key` always, `did:web:<instance>.<tailnet>.ts.net` if Tailscale chosen (S-152) |
| LLM routing | LiteLLM with OAuth-preferred free-tier providers auto-configured: Groq, Cerebras, Cloudflare Workers AI, OpenRouter (S-144) |
| Crypto | Skip (no wallet plugin installed); operators opt in via Medley afterward |
| Reactor | 1kHz event-driven loop replaces heartbeat (S-143) |
| Privilege | admin + 1..N users mandatory, wizard refuses to complete without at least one user beyond admin (S-142) |
| Native install | systemd / launchd / Windows Service hardening profile (S-147) |
| Container | Disabled by default; opt in via wizard (S-148) |
| Plugin marketplace | Medley with a configurable registry; community registry pinned by content hash by default (S-037, S-111) |

### Composition (what specs assemble into Agent Conductor)

This spec is the umbrella; every spec below is a load-bearing component.

| Layer | Spec(s) |
|---|---|
| Runtime | S-145 (Hyperagent Graph Runtime), S-002 (spawner), S-005 (factory), S-007 (intent classifier) |
| Privilege & identity | S-142 (admin/user1), S-149 (Conductor Seed), S-150 (hardware signing), S-152 (DID + VC) |
| Vault & secrets | S-141 (age-encrypted vault) |
| Storage | S-140 (SQLite singleton writer) |
| Execution model | S-143 (1kHz reactor loop) |
| Networking | S-153 (substrate abstraction; Tailscale recommended) |
| TLS | S-155 (internal trust root with sovereignty mode) |
| Defense | S-022 (Bouncer), S-026 (Red/Blue), S-030 (Phantom Execution) |
| Memory | S-032 (7-tier episodic), S-033 (git-tracked memory) |
| Audit | S-021 (Langfuse), S-016 (Console / Intel tab), S-152 (audit-log VCs) |
| LLM routing | S-144 (LiteLLM free-tier OAuth wizard) |
| Plugins | S-037 (Medley basics), S-111 (Medley full / publisher VCs) |
| Crypto (opt-in) | S-151 (wallet ops + Lightning), S-154 (Electrum server), S-156 (Lightning federation) |
| Install | S-147 (hardened native), S-148 (optional Podman), S-139 (browser-first wizard) |
| Philosophy | `specs/security/PHILOSOPHY.md` |

### Positioning vs Agent Stronghold

| Axis | Agent Conductor | Agent Stronghold |
|---|---|---|
| Tenant model | One household / team | Many tenants, each with many users |
| Default substrate | Tailscale (recommended) | Traefik + oauth2-proxy + Keycloak (S-017, S-018) |
| Default vault | age-encrypted file + admin keypair (S-141) | Vaultwarden API (S-023) |
| Default state store | SQLite + sqlite-vec | Postgres + pgvector |
| Default identity | DID auto-issued from Conductor Seed | Keycloak realm + JWT |
| Default deploy | One machine (or small cluster) | Multi-node clustered |
| Crypto | Opt-in | Opt-in (same plugins) |
| Console | Same Console UI | Same Console UI + tenant-aware admin views |

The runtime is the same. The substrate, vault, and tenant-isolation layers are the differences. An operator who outgrows Conductor migrates to Stronghold by reconfiguring substrate / vault / state, not by switching products.

### Positioning vs OpenClaw

*"OpenClaw is one agent. Agent Conductor orchestrates a self-improving graph of them — including OpenClaw as a node, if you want."*

The full comparison lives in `specs/security/ARCHITECTURE.md` §5. The TL;DR: Agent Conductor and OpenClaw share a threat surface but make different bets about where to put the defense. Conductor is built on the substrate that makes "AI agent with a wallet, secrets, and federation" sane; OpenClaw is built for a single user with a single trust boundary at the local-machine perimeter.

### What Agent Conductor is *not*

- Not a single-binary install with no configuration. The wizard is fast (~5 minutes browser-first) but produces a real cryptographic identity, real privilege separation, and real substrate configuration. It is not magic-bullet UX; it is *deliberate* UX.
- Not Bitcoin-required. The crypto plugins are opt-in. A conductor with no crypto features works fully (S-151).
- Not multitenant. Move to Agent Stronghold when you need that.
- Not a hosted SaaS. There is no `signup.maistro.com`. You run it. (Agent Stronghold may eventually have hosted offerings; Conductor will not.)
- Not a thin wrapper around a single LLM. LiteLLM's routing across multiple providers (S-144) is core to the product story.

## Acceptance Criteria

- [ ] Setup wizard (S-139) lands a working Agent Conductor with all defaults from this spec in under 5 minutes browser-first on a fresh machine
- [ ] All 18 referenced sub-specs in §"Composition" are load-bearing; removing any one breaks a documented capability
- [ ] An operator who picks all defaults gets: Tailscale substrate, public-CA TLS, age-vault, SQLite+sqlite-vec, no crypto, OAuth-configured LiteLLM free tier, hardened native install, Console accessible at the substrate URL
- [ ] An operator who wants sovereignty defaults gets: any-substrate (incl. localhost-only), local-CA TLS, age-vault, no telemetry, no public-internet DID, no LiteLLM external providers if they BYO local model
- [ ] Migration path to Agent Stronghold is documented (substrate / vault / state swap; runtime stays)
- [ ] README and `maistro --version` both name "Agent Conductor" as the product
- [ ] An imported OpenClaw skill or agent runs as a node inside Conductor with the full Bouncer / capability-envelope / audit-log treatment (verifies S-145 import contract)

## Implementation Notes

- This spec is documentation-bearing, not code-bearing. No new module is created by this spec; it names the umbrella that sub-specs assemble into.
- The Console UI is shared across setup (S-139) and runtime (S-016). One codebase, two entry points (temporary localhost server during setup; substrate-served URL after).
- The `maistro` CLI is the companion to the Console; both share the same authentication backend (admin keypair from S-149, identity attestation from S-153).
- The product version bumps when any of the sub-specs in §"Composition" lands a breaking change. Compatibility matrix maintained in `docs/COMPATIBILITY.md`.

## Verification

- Fresh install with all wizard defaults → working Console in <5 min on a Linux laptop with Tailscale already installed; <10 min on a fresh machine including Tailscale install.
- Same install, sovereignty mode (substrate=localhost, TLS=local-ca, no LiteLLM external providers, no crypto) → working conductor with zero outbound traffic verifiable via tcpdump.
- Migration test: Conductor instance → reconfigure substrate to Keycloak, vault to Vaultwarden, state to Postgres → same runtime starts, same Conductor Seed valid, same audit log preserved — now operating as the single-tenant case of Agent Stronghold.
- Import test: install an OpenClaw skill via Medley adapter → verify it runs as a node, Bouncer screens its inputs, audit log records its invocations as VCs.
