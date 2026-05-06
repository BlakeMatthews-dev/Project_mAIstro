# Project mAIstro

**Conductor orchestrates your agent swarm — no matter the shape.**

Wraps any agent in our security and permissions boundaries. Lets AutoGen call Claude Code. Lets Claude Code call Anthropic ADK. Lets your custom agent call Jenny in HR over Teams. Get the work done, no matter who or what needs to do it. *One node could be "send a Teams message asking a question and return the answer to the next node."* Same envelope. Same audit log. Same provenance — whether the responder is a model, a framework, another conductor, or a person.

Over time, the Conductor learns how to ask Jenny better — concise where she likes concise, with context where she needs it, in the channel and at the time she actually responds. Same hyperagent optimization that tunes prompts for models, applied to the humans in your graph.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)
[![Specs: Driven](https://img.shields.io/badge/Specs-Driven-success?style=for-the-badge)](specs/TIMELINE.md)
[![Status: in design](https://img.shields.io/badge/Status-in%20design-orange?style=for-the-badge)](specs/TIMELINE.md)

---

## Two products, one runtime

```
project_mAIstro                          (the studio / repo)
  ├─ Agent Conductor                       household / personal scale
  │     2–N users (admin + 1..N)
  │     single-machine or small cluster
  │     crypto / federation opt-in
  │     SQLite + sqlite-vec, age-encrypted vault
  │     pluggable mesh substrate (Tailscale, Headscale, NetBird, ZeroTier, ...)
  │
  └─ Agent Stronghold                      multitenant platform
        many tenants × many users each
        clustered / cloud deploy
        Keycloak + Vaultwarden + Postgres
```

One **Hyperagent Graph Runtime** ([S-145](specs/conductor/S-145-hyperagent-graph-runtime.md)) underneath both. Same Bouncer ([S-022](specs/security/S-022-bouncer.md)), same capability envelope, same audit log, same Conductor Seed root of trust ([S-149](specs/security/S-149-conductor-seed.md)).

---

## Why this exists

> **Windows doesn't run apps as Administrator. Linux requires sudo. Why does your AI agent default to root?**
>
> Agent Conductor is secure by design — human-in-the-loop for critical actions, separation of privilege by default. You don't give your handyman your banking login or the keys to your safe. So why give them to your AI?
>
> Your conductor stores credentials in a sealed vault. It can't leak what it doesn't know.

Full rationale: [`specs/security/PHILOSOPHY.md`](specs/security/PHILOSOPHY.md). Architecture white paper: [`specs/security/ARCHITECTURE.md`](specs/security/ARCHITECTURE.md).

---

## What you get

### Universal node contract (Shape A)

Anything that takes a prompt and emits a response can be wrapped as a node in the graph: another Maistro Conductor, OpenClaw, Claude Code, Anthropic ADK, AutoGen / Microsoft Agent Framework, a Claude SDK project, a LangGraph chain, your custom agent, **a human on Teams / Slack / email / SMS / their own conductor / the conductor app**. Each wrapped node runs inside our Bouncer + capability envelope + audit log.

See [S-145 §5](specs/conductor/S-145-hyperagent-graph-runtime.md) (the universal adapter contract) and [S-158](specs/conductor/S-158-human-as-node.md) (humans-as-nodes specifically).

### Compatibility today, agent-wrapping forthcoming

- **Skills (`SKILL.md`)** — work today. Skills authored for Claude Code or OpenClaw run in Maistro and vice versa.
- **Plugins** — Medley ([S-037](specs/tools/S-037-clawhub.md)) is the universal plugin marketplace covering skills, channels, agents, and subgraphs.
- **Agent wrapping** — the architecture spec ([S-145](specs/conductor/S-145-hyperagent-graph-runtime.md)) defines the contract; first-party adapters for Claude Code, ADK, AutoGen, OpenClaw, and human-on-channel are forthcoming Medley plugins.

### Privilege separation by default ([S-142](specs/security/S-142-privilege-separation.md))

Mandatory two-tier model. The setup wizard ([S-139](specs/infra/S-139-setup-wizard.md)) is structurally incapable of completing with fewer than two users (admin + at least one named user). No flag, no environment variable, no shortcut. Privileged operations route through admin via wallet-app signing.

### Sovereign by default

- BIP39/BIP32 Conductor Seed as the root of trust ([S-149](specs/security/S-149-conductor-seed.md)). The same seed phrase recovers your identity, your audit-log signing key, your TLS CA, and (optionally) your Lightning wallet.
- age-encrypted vault unlocked by your admin keypair ([S-141](specs/security/S-141-vault.md)). The agent never holds credential *values* in its variable scope — the vault is a broker, not a key/value store.
- Bring-your-own networking substrate ([S-153](specs/infra/S-153-tailscale-native.md)): Tailscale recommended; Headscale / NetBird / ZeroTier / Cloudflare Tunnel / LAN-mDNS / localhost-only / manual all first-class.
- Bring-your-own TLS root ([S-155](specs/security/S-155-internal-trust-root.md)). Run your own household CA; Let's Encrypt is optional, not required. *Not your keys, not your TLS.*

### Crypto-optional

Wallet, Lightning, federation, Bitcoin chain backend — all opt-in via Medley. A conductor with no crypto plugins runs fully and is fully secure ([S-151](specs/security/S-151-agent-crypto-ops.md)). For operators who want it: Lightning federation between conductor friends ([S-156](specs/security/S-156-lightning-federation.md)) makes spam-resistance economic, paid messaging native, and reputation a function of the payment graph itself.

### Self-improving graph

The runtime tunes itself within bounded subsystems ([S-145 §4](specs/conductor/S-145-hyperagent-graph-runtime.md)):

- Red/Blue ([S-026](specs/intelligence/S-026-adversarial-hardening.md)) grows the Bouncer's pattern library.
- Tournament Arena ([S-027](specs/intelligence/S-027-tournament-arena.md)) scores recipe variants — *and per-human prompt variants*. Over time, the conductor talks to Jenny in *her* most-effective framing, opt-in.
- Skill Forge ([S-038](specs/tools/S-038-skill-forge.md)) writes new skills; Phantom ([S-030](specs/intelligence/S-030-phantom-execution.md)) sandbox-tests them; Skill Evolution ([S-112](specs/tools/S-112-skill-evolution.md)) prunes weak ones.

All graph mutations are admin-signed and produce VCs in the audit log ([S-152](specs/security/S-152-agent-identity-did-vc.md)).

### Browser-first install

```
# Linux / macOS
curl -fsSL maistro.dev/install.sh | sh

# Windows
Double-click the signed maistro-setup.msi

→ conductor binary installs as a service
→ spawns localhost:9999 wizard
→ opens browser
→ wizard walks you through seed, admin, users, network, TLS, LLM, channels, optional crypto
→ ~5 minutes to a working conductor
```

Full flow: [S-139](specs/infra/S-139-setup-wizard.md). CLI fallback for headless deploys; signed `.msi` for Windows; signed `.pkg` for macOS users who prefer GUI install.

---

## Spec-driven

Every claim in this README is a spec in [`specs/`](specs/) with acceptance criteria, file pointers, and verification steps. The master timeline is [`specs/TIMELINE.md`](specs/TIMELINE.md).

Security comparison vs OpenClaw: [`specs/security/ARCHITECTURE.md`](specs/security/ARCHITECTURE.md) §5.

The spec tree is the single source of truth. Old `CONDUCTOR-ROADMAP.md` and `BACKLOG.md` are deprecated and kept for historical reference only.

---

## Quick links

- [**Philosophy**](specs/security/PHILOSOPHY.md) — the why
- [**Architecture white paper**](specs/security/ARCHITECTURE.md) — layer-by-layer + OpenClaw comparison
- [**Hyperagent Graph Runtime**](specs/conductor/S-145-hyperagent-graph-runtime.md) — the meta-spec
- [**Agent Conductor product definition**](specs/conductor/S-138-agent-conductor.md) — the household SKU
- [**Setup wizard**](specs/infra/S-139-setup-wizard.md) — the install ceremony
- [**Node + Graph Designer**](specs/infra/S-159-node-graph-designer.md) — the visual composer
- [**Human-as-node**](specs/conductor/S-158-human-as-node.md) — Jenny in HR is a first-class node
- [**Lightning federation**](specs/security/S-156-lightning-federation.md) — paid messaging between conductor friends (opt-in)
- [**TIMELINE**](specs/TIMELINE.md) — the master chronology

---

## Status

In design. The spec tree is the deliverable today; implementation is being staged spec-by-spec via the methodology in `CONTRIBUTING.md`: **specs → Gherkin scenarios → contracts → tests → implementation → mobile**.

No running gateway / no installable binary yet. If you're here to evaluate the architecture, start with `specs/security/ARCHITECTURE.md` and `specs/security/PHILOSOPHY.md`.

---

## License

[MIT](LICENSE)
