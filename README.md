# Project mAIstro

> **Windows doesn't run apps as Administrator. Linux requires sudo. Why does your AI agent default to root?**
>
> Agent Conductor is secure by design — human-in-the-loop for critical actions, separation of privilege by default. You don't give your handyman your banking login or the keys to your safe. So why give them to your AI?
>
> Your conductor stores credentials in a sealed vault. It can't leak what it doesn't know.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)
[![Specs](https://img.shields.io/badge/Spec--driven-yes-7c3aed?style=for-the-badge)](specs/TIMELINE.md)
[![Philosophy](https://img.shields.io/badge/Philosophy-PHILOSOPHY.md-2563eb?style=for-the-badge)](specs/security/PHILOSOPHY.md)
[![Threat Model](https://img.shields.io/badge/Threat%20Model-ARCHITECTURE.md-dc2626?style=for-the-badge)](specs/security/ARCHITECTURE.md)

---

## Two products, one studio

```
project_mAIstro                          (the studio / repo)
  ├─ Agent Conductor                       household / personal scale
  │     2–N users (admin + 1..N)           single-machine or small cluster
  │     crypto / federation opt-in          spec: S-138
  │
  └─ Agent Stronghold                      multitenant platform
        many tenants × many users           clustered / cloud deploy
```

**Agent Conductor** is the headline product — a household-scale AI agent platform with privilege separation, sealed credentials, and self-hosted everything. **Agent Stronghold** is the multitenant SKU that runs the same runtime at scale.

This README focuses on Agent Conductor. The complete spec tree is in [`specs/`](specs/); the master timeline is [`specs/TIMELINE.md`](specs/TIMELINE.md); the threat model and security architecture is [`specs/security/ARCHITECTURE.md`](specs/security/ARCHITECTURE.md).

---

## What Agent Conductor is

A self-improving hyperagent graph runtime that orchestrates a swarm of importable, modifiable agents. Your conductor:

- Routes prompts through a typed capability envelope — conversation-only intents get zero tools, ever ([S-145](specs/conductor/S-145-hyperagent-graph-runtime.md))
- Stores credentials in an age-encrypted vault unlocked by your seed phrase — the agent never sees secret values, only requests their use ([S-141](specs/security/S-141-vault.md))
- Requires admin + at least one user, mandatory at install time. Single-user-as-root is structurally impossible ([S-142](specs/security/S-142-privilege-separation.md))
- Runs everything through a Bouncer (regex + LLM negative pass) before any tool invocation ([S-022](specs/security/S-022-bouncer.md))
- Has continuous Red/Blue self-hardening; new attack patterns feed back into the Bouncer ([S-026](specs/intelligence/S-026-adversarial-hardening.md))
- Records every privileged action as a Verifiable Credential signed by your DID ([S-152](specs/security/S-152-agent-identity-did-vc.md))
- Federates with other conductors over Tailscale / NetBird / Cloudflare Tunnel / your-own-substrate, optionally with Lightning-paid spam resistance ([S-153](specs/infra/S-153-tailscale-native.md), [S-156](specs/security/S-156-lightning-federation.md))

The positioning frame: **OpenClaw is one agent. Agent Conductor orchestrates a graph of them — including OpenClaw as a node, if you want.** Full comparison with citations: [`specs/security/ARCHITECTURE.md`](specs/security/ARCHITECTURE.md) §5.

---

## Five-minute install

### Linux / macOS

```bash
curl -fsSL maistro.dev/install.sh | sh
```

Verifies signature, installs the conductor as a `systemd` unit (Linux) or `launchd` plist (macOS), opens the browser at `http://127.0.0.1:9999/setup`, and runs the wizard.

macOS users who prefer a GUI install: download the signed `.pkg` from `maistro.dev/download`. Same outcome.

### Windows

Download `maistro-setup.msi` from `maistro.dev/download`. Authenticode-signed; SmartScreen recognizes it. Double-click to install; conductor runs as a low-privilege Windows Service; default browser opens to the wizard.

### Wizard flow (12 steps in your browser)

1. Name your conductor.
2. Generate Conductor Seed (BIP39 24 words, with optional SLIP39 Shamir or hardware wallet).
3. Create admin (keypair derived from seed; recovery card printed).
4. **Create user one (required — wizard does not advance without this).**
5. Anyone else in your household? (add 0..N more users).
6. Network substrate: Tailscale (recommended) / Headscale / NetBird / ZeroTier / Cloudflare Tunnel / LAN / localhost / manual.
7. TLS mode: Public CA / Local CA (sovereignty mode) / both.
8. LLM providers: OAuth-first sign-in to Groq + OpenRouter, paste-API for Cerebras + Cloudflare AI; or BYO local model.
9. Channels: Telegram / voice / email / Obsidian (optional).
10. Crypto features: skip (default) / Lightning / Bitcoin+Lightning / BYO node.
11. Live smoke tests confirm Bouncer rejects injection, vault is brokered, capability envelope works, audit log signs the install ceremony itself.
12. Open the Console.

Details: [`specs/infra/S-139-setup-wizard.md`](specs/infra/S-139-setup-wizard.md).

Headless install? `curl install.sh | sh -s -- --cli` runs the same wizard in your terminal.

---

## Architecture overview

```
   inbound (untrusted)                       outbound (privileged)
   ──────────────────                       ────────────────────
        chat / voice                          shell / file / API
        email / web                                  ↑
              ↓                                      │
      [substrate identity] (S-153)                   │
              ↓                                      │
         [Bouncer] (S-022) — regex + LLM screen ────│
              ↓                                      │
     [Intent Classifier] (S-007) → typed AgentSpec   │
              ↓                                      │
      [Spawner] (S-002) — capability whitelist       │
              ↓                                      │
         [Agent Loop] ─ vault.use ─ medley plugin ───┘
              ↓                                      
     [Langfuse trace] + [audit-log VC] + [git-tracked memory write]
```

Full architecture, threat model, and OpenClaw comparison: [`specs/security/ARCHITECTURE.md`](specs/security/ARCHITECTURE.md).

---

## Sovereignty mode

The whole stack is opt-out. Pick localhost-only substrate, local-CA TLS, BYO local LLM, no crypto, no channels — the wizard supports it; the smoke tests still pass; the conductor runs with **zero outbound traffic** verifiable via `tcpdump`.

For crypto-native users:

- Your Conductor Seed *is* a BIP39 phrase. Same words back up the agent's identity, your wallets, and (optionally) your federation keys ([S-149](specs/security/S-149-conductor-seed.md)).
- Bring your own Lightning node, or run `medley install lightning` to get one bundled with LDK.
- Optional: `medley install electrum-server` makes your conductor your household's private Bitcoin backend ([S-154](specs/tools/S-154-electrum-server.md)).
- Federate with other conductors over Lightning with payment-graph reputation ([S-156](specs/security/S-156-lightning-federation.md)).
- Run your own CA from the same seed; nothing in the trust chain leaves your control ([S-155](specs/security/S-155-internal-trust-root.md)).

---

## Medley — the plugin marketplace

```
medley install ha-ai telegram gmail builders-graph
```

Medley is the unified plugin format for skills, channels, agents, and multi-agent subgraphs. Plugins ship with publisher Verifiable Credentials signed by the publisher's DID; install-time verification gates trust promotion.

- Skills (single executable capabilities) — [S-035](specs/tools/S-035-skills-subsystem.md)
- Channels (input/output adapters: Telegram, Slack, Discord, Matrix, Signal, etc.)
- Agents (importable agent nodes; Claude SDK / LangGraph / OpenClaw / etc.)
- Graphs (multi-agent subgraphs imported as a unit)

Spec: [S-037 Medley basics](specs/tools/S-037-clawhub.md), [S-111 Medley full (publish, versions, signed VCs)](specs/tools/S-111-clawhub-full.md).

Every plugin runs inside the same Bouncer / capability envelope / Phantom-Execution-sandbox machinery as native agents. **OpenClaw runs as a node inside Maistro this way** — wrapped in an `ImportedAgent` adapter, with the same security gates as everything else.

---

## Quick links to the spec tree

| Topic | Spec |
|---|---|
| **Why this design** | [`specs/security/PHILOSOPHY.md`](specs/security/PHILOSOPHY.md) |
| Threat model + OpenClaw comparison | [`specs/security/ARCHITECTURE.md`](specs/security/ARCHITECTURE.md) |
| Master timeline | [`specs/TIMELINE.md`](specs/TIMELINE.md) |
| Hyperagent graph runtime | [S-145](specs/conductor/S-145-hyperagent-graph-runtime.md) |
| Agent Conductor product | [S-138](specs/conductor/S-138-agent-conductor.md) |
| Setup wizard | [S-139](specs/infra/S-139-setup-wizard.md) |
| Vault (sealed credentials) | [S-141](specs/security/S-141-vault.md) |
| Privilege separation | [S-142](specs/security/S-142-privilege-separation.md) |
| 1kHz reactor loop | [S-143](specs/conductor/S-143-1khz-reactor.md) |
| LLM provider auto-config | [S-144](specs/infra/S-144-litellm-freetier.md) |
| Native install (.msi / launchd / systemd) | [S-147](specs/infra/S-147-native-install.md) |
| Optional Podman containerization | [S-148](specs/infra/S-148-podman-container.md) |
| Conductor Seed (BIP39 + BIP32 HD) | [S-149](specs/security/S-149-conductor-seed.md) |
| Hardware signing devices | [S-150](specs/security/S-150-hardware-signing.md) |
| Crypto operations + Lightning | [S-151](specs/security/S-151-agent-crypto-ops.md) |
| DID + Verifiable Credentials | [S-152](specs/security/S-152-agent-identity-did-vc.md) |
| Networking substrate (Tailscale / NetBird / etc.) | [S-153](specs/infra/S-153-tailscale-native.md) |
| Electrum server plugin | [S-154](specs/tools/S-154-electrum-server.md) |
| Internal CA + sovereignty mode | [S-155](specs/security/S-155-internal-trust-root.md) |
| Lightning-native federation | [S-156](specs/security/S-156-lightning-federation.md) |

---

## CLI companion

```bash
maistro setup                       # Re-run / reconfigure the wizard (admin-signed for reset)
maistro vault add <name>            # Add a credential to the sealed vault
maistro identity show               # Show this conductor's DID
maistro federate <peer-did>         # Open a friend handshake with another conductor
medley install <name>...            # Install plugins
medley info <name>                  # Inspect a plugin's publisher + trust tier
maistro update                      # Atomic signed update
```

---

## Stronghold (the multitenant SKU)

Agent Stronghold runs the same hyperagent runtime with multitenant primitives swapped in: Postgres for state, Vaultwarden for secrets, Keycloak + oauth2-proxy for the perimeter, Traefik for routing. An operator who outgrows Conductor migrates by reconfiguring the substrate, vault, and state layers — the runtime, the audit log, and the Conductor Seed all transfer.

Documentation for Agent Stronghold lives in a separate spec set (forthcoming).

---

## Project structure

```
project_maistro/
├── specs/                    # Source of truth: every claim has a spec
│   ├── TIMELINE.md           # Master timeline of all specs
│   ├── SPEC-TEMPLATE.md      # Template for new specs
│   ├── conductor/            # Orchestrator-side specs
│   ├── infra/                # Substrate, networking, install, storage
│   ├── security/             # Identity, vault, philosophy, threat model
│   ├── intelligence/         # Memory, dreams, red team, tournament
│   ├── tools/                # Medley, skills, plugins
│   └── channels/             # Telegram / voice / email / etc.
├── src/                      # TypeScript gateway + dashboard
├── conductor/                # Python orchestrator
├── packages/                 # Workspace packages
├── extensions/               # First-party Medley plugins
├── skills/                   # First-party SKILL.md bundles
├── Dockerfile                # Container image
└── docker-compose.yml        # Reference compose for development
```

---

## Contributing

Every feature has a spec. Workflow: spec → Gherkin scenarios → contracts → tests → implementation. See [`specs/SPEC-TEMPLATE.md`](specs/SPEC-TEMPLATE.md) for the spec format. New features without a spec will be asked to add one before review.

Security disclosure: see [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE)
