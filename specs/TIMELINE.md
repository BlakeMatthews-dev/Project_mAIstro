# Project mAIstro — Feature Timeline

**Source of truth**: Each `S-NNN` links to a spec file in `specs/`. This file is the chronological view; the spec files contain problem statements, acceptance criteria, and implementation notes.

**Status key**: ✓ done · ⟳ in progress · ◻ planned · 🔬 research · ⏸ backburner

---

## Phase 0: Foundation (Feb 25 2026)

Initial stack: inference engine benchmarked, all services communicating, conductor running end-to-end.

| Spec | Feature | Status |
|------|---------|--------|
| [S-044](infra/S-044-gpu-model-benchmarking.md) | GPU recovery + Qwen3.5-35B-A3B benchmarking | ✓ |
| [S-045](infra/S-045-langfuse-setup.md) | Langfuse prompts + wiki + WordPress setup | ✓ |
| [S-021](infra/S-021-service-integration.md) | Service integration (OpenWebUI → LiteLLM → Cloud + Langfuse) | ✓ |
| [S-013](infra/S-013-systemd-services.md) | Systemd services (gateway + conductor) | ✓ |
| [S-001](conductor/S-001-heartbeat.md) | Heartbeat wired into conductor main loop | ✓ |
| [S-002](conductor/S-002-factory-spawner.md) | Factory → Spawner (variant selector, recipes) | ✓ |
| [S-005](conductor/S-005-agent-factory.md) | Agent Factory (Thompson sampling, typed outputs) | ✓ |
| [S-006](conductor/S-006-apm.md) | APM — 7-section personality template | ✓ |
| [S-022](security/S-022-bouncer.md) | Bouncer (20+ regex + LLM screening) | ✓ |
| [S-023](security/S-023-secrets-manager.md) | Secrets Manager (Vaultwarden) | ✓ |
| [S-035](tools/S-035-skills-subsystem.md) | Skills subsystem (scanner, loader, trust tiers) | ✓ |
| [S-032](intelligence/S-032-episodic-memory.md) | 7-tier episodic memory (PG + pg_trgm) | ✓ |
| [S-033](intelligence/S-033-memory-evolution.md) | Memory evolution history (git-tracked) | ✓ |

---

## Phase 1: Intelligence Layer (Mar 23 2026)

Experimental agents, adversarial hardening, memory consolidation, and temporal reasoning.

| Spec | Feature | Status |
|------|---------|--------|
| [S-025](intelligence/S-025-dream-loop.md) | Dream Loop — idle-time memory consolidation | ✓ |
| [S-026](intelligence/S-026-adversarial-hardening.md) | Adversarial Self-Hardening (Red/Blue) | ✓ |
| [S-027](intelligence/S-027-tournament-arena.md) | Model Tournament Arena (private leaderboard) | ✓ |
| [S-028](intelligence/S-028-context-archaeology.md) | Context Archaeology — forensic failure autopsy | ✓ |
| [S-029](intelligence/S-029-temporal-patterns.md) | Temporal Pattern Recognition | ✓ |
| [S-030](intelligence/S-030-phantom-execution.md) | Phantom Execution — shadow-run skills | ✓ |
| [S-031](intelligence/S-031-mood-ring.md) | Mood Ring — adaptive behavior from system health | ✓ |
| [S-034](tools/S-034-time-capsule.md) | Time Capsule — scheduled self-reminders | ✓ |
| [S-036](tools/S-036-message-board.md) | Message board (agent → human async) | ✓ |
| [S-003](conductor/S-003-artifact-intent.md) | ARTIFACT intent handler | ✓ |
| [S-004](conductor/S-004-conversation-intent.md) | CONVERSATION intent handler | ✓ |
| [S-014](infra/S-014-http-webhook.md) | HTTP webhook delivery | ✓ |

---

## Phase 2: Medley & Forge (Mar 23 2026)

Plugin ecosystem: discovery, install, security scanning, autonomous skill creation, and Ultra Think.

| Spec | Feature | Status |
|------|---------|--------|
| [S-037](tools/S-037-clawhub.md) | Medley — community plugin marketplace | ✓ |
| [S-038](tools/S-038-skill-forge.md) | Skill Forge — agent writes its own skills | ✓ |
| [S-039](tools/S-039-ultra-think.md) | Ultra Think — multi-model, quota-aware deep reasoning | ✓ |
| [S-040](tools/S-040-project-build-agents.md) | Project build agents (Scout, Architect, Extractor, Validator) | ✓ |

---

## Phase 3: Security, Auth & Dashboard (Mar 23–24 2026)

Full authentication stack, unified SSO, and 5-page Stronghold dashboard.

| Spec | Feature | Status |
|------|---------|--------|
| [S-024](security/S-024-jwt-auth.md) | JWT auth — Keycloak RS256 + role-based tools | ✓ |
| [S-018](infra/S-018-keycloak-migration.md) | Keycloak OIDC migration (42 proxies + 6 native services) | ✓ |
| [S-017](infra/S-017-dashboard-auth.md) | Dashboard auth (oauth2-proxy + Keycloak) | ✓ |
| [S-019](infra/S-019-openwebui-jwt.md) | OpenWebUI JWT passthrough | ✓ |
| [S-015](infra/S-015-progress-dashboard-api.md) | Progress tracking + dashboard API | ✓ |
| [S-016](infra/S-016-dashboard-ui.md) | Dashboard UI — 5-page Stronghold | ✓ |

---

## Phase 4: Channels & Conversation (Mar 23 2026)

Voice integration, phone notifications, per-user isolation, and conversational intelligence.

| Spec | Feature | Status |
|------|---------|--------|
| [S-041](channels/S-041-voice-agent.md) | Voice agent (Alexa → HA Assist → Conductor) | ✓ |
| [S-042](channels/S-042-voice-model-group.md) | Voice model group (2-4s routing) | ✓ |
| [S-043](channels/S-043-phone-notifications.md) | Phone notifications (ha_notify) | ✓ |
| [S-007](conductor/S-007-3-phase-classifier.md) | 3-phase classifier (keywords + LLM fallback) | ✓ |
| [S-008](conductor/S-008-session-summarization.md) | Session summarization → episodic memories | ✓ |
| [S-009](conductor/S-009-episodic-memory-bridge.md) | Episodic memory bridge (auto-promote learnings) | ✓ |
| [S-010](conductor/S-010-session-isolation.md) | Per-user session isolation | ✓ |
| [S-011](conductor/S-011-morning-digest.md) | Morning digest (Blake 5:45 / Lilly 7:20) | ✓ |
| [S-012](conductor/S-012-positive-pattern-learning.md) | Positive pattern learning | ✓ |
| [S-020](infra/S-020-searxng.md) | SearXNG deployment (LXC 104) | ✓ |

---

## Phase 4b: Historical Plans (Jan–Feb 2026)

Smaller hardening passes (channel allowlists, cron normalization).

| Spec | Feature | Status |
|------|---------|--------|
| [S-130](infra/S-130-cron-hardening.md) | Cron Add hardening & schema alignment | ✓ |
| [S-131](security/S-131-group-policy-hardening.md) | Telegram allowlist hardening | ✓ |

---

## Phase 5: Active Sprint (Apr 2026)

Current work in progress.

| Spec | Feature | Priority | Status |
|------|---------|----------|--------|
| [S-100](infra/S-100-infrastructure-fixes.md) | Infrastructure fixes (disk + SnapRAID) | P1 | ⟳ |
| [S-109](security/S-109-secrets-migration.md) | Secrets → Vaultwarden migration | P1 | ◻ |
| [S-104](channels/S-104-alexa-devices.md) | Alexa Devices setup | P2 | ◻ |
| [S-103](channels/S-103-email-channel.md) | Email channel (conductor@emeraldfam.org) | P2 | ◻ |
| [S-105](conductor/S-105-uncapped-tool-loop.md) | Uncapped tool loop for heartbeat tasks | P3 | ◻ |
| [S-106](conductor/S-106-user-profiles.md) | User profile extraction | P3 | ◻ |
| [S-107](conductor/S-107-confidence-decay.md) | Confidence decay on learnings | P3 | ◻ |
| [S-112](tools/S-112-skill-evolution.md) | Skill Evolution (natural selection) | P2 | ◻ |
| [S-102](infra/S-102-pwa-dashboard.md) | PWA dashboard (mobile-installable) | P3 | ◻ |
| [S-108](tools/S-108-user-feedback.md) | User feedback (thumbs up/down) | P2 | ◻ |
| [S-115](intelligence/S-115-agent-networking.md) | Agent-to-agent networking | P3 | ◻ |
| [S-114](intelligence/S-114-collective-unconscious.md) | Collective Unconscious (federated) | P3 | ◻ |

---

## Phase 6: Planned

Approved backlog, not yet started.

| Spec | Feature | Priority | Effort |
|------|---------|----------|--------|
| [S-101](infra/S-101-traefik-dashboard.md) | Traefik route for dashboard (HTTPS) | P2 | 15 min |
| [S-110](tools/S-110-hooks-system.md) | General hooks system | P2 | ~250 lines |
| [S-111](tools/S-111-clawhub-full.md) | Medley full (publish, versions, signed VCs, deps) | P2 | ~300 lines |
| [S-113](tools/S-113-stress-rehearsal.md) | Stress Rehearsal — chaos testing | P2 | ~250 lines |
| [S-120](infra/S-120-obsidian-livesync.md) | CouchDB / Obsidian LiveSync | P3 | — |

---

## Phase 7: Research Horizon

Open questions and future directions.

| Spec | Feature | Priority | Notes |
|------|---------|----------|-------|
| [S-116](infra/S-116-inference-engine.md) | Better inference engine (vLLM / ExLlamaV2) | P1 | llama.cpp ik fork in use |
| [S-117](infra/S-117-speculative-decoding.md) | Speculative decoding (MTP) | P2 | Qwen3.5 native MTP support |
| [S-118](infra/S-118-rpc-distributed-inference.md) | RPC distributed inference (P40 + 3070 Ti) | P2 | Split model across GPUs |
| [S-119](infra/S-119-bf16-requantization.md) | BF16 source weight requantization | P2 | Fresh imatrix quants |

---

## Phase 8: Identity, Networking & Sovereignty (Apr 2026)

The Agent Conductor security identity layer: BIP39 seed root of trust, hardware signing, crypto operations, DID/VC identity, pluggable networking substrate, household-private chain backend, sovereign TLS, Lightning federation.

| Spec | Feature | Priority | Status |
|------|---------|----------|--------|
| [S-149](security/S-149-conductor-seed.md) | Conductor Seed (BIP39 + BIP32 HD root of trust) | P1 | draft |
| [S-150](security/S-150-hardware-signing.md) | Hardware signing devices (Ledger / Trezor / YubiKey / mobile) | P2 | draft |
| [S-151](security/S-151-agent-crypto-ops.md) | Crypto operations + Lightning + unified HITL signing | P1 | draft |
| [S-152](security/S-152-agent-identity-did-vc.md) | Agent Identity & Verifiable Credentials (DID + VC) | P1 | draft |
| [S-153](infra/S-153-tailscale-native.md) | Networking & identity substrate (Tailscale recommended, mesh substrates pluggable) | P1 | draft |
| [S-154](tools/S-154-electrum-server.md) | Electrum server Medley plugin (household-private Bitcoin backend) | P2 | draft |
| [S-155](security/S-155-internal-trust-root.md) | Internal trust root (mkcert-style local CA, sovereignty mode) | P1 | draft |
| [S-156](security/S-156-lightning-federation.md) | Lightning-native federation (paid messaging, payment-graph reputation) | P2 | draft |

---

## In-flight Implementation Plans

These specs are detailed implementation plans promoted from `docs/experiments/plans/`.

| Spec | Feature | Status |
|------|---------|--------|
| [S-132](infra/S-132-openresponses-gateway.md) | OpenResponses `/v1/responses` endpoint | draft |
| [S-133](infra/S-133-pty-supervision.md) | PTY and Process Supervision | in progress |
| [S-134](tools/S-134-browser-cdp-refactor.md) | Browser Evaluate CDP refactor | draft |
| [S-135](infra/S-135-monorepo-consolidation.md) | Monorepo consolidation (absorb maistro-engine) | draft |

---

_Last updated: 2026-04-25_
