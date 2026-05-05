# Project mAIstro — Security Architecture

_A white paper / README hybrid. Read top-to-bottom for the design rationale, or jump to **Quick Reference** if you just need to wire something up._

**Status:** living document
**Last updated:** 2026-04-25
**Audience:** operators deploying maistro, contributors adding tools or channels, reviewers evaluating it against alternatives (OpenClaw, etc.)

---

## TL;DR

Project mAIstro is an autonomous orchestrator (the "conductor") that runs persistent agents, schedules background work, and manages a skill / tool ecosystem on behalf of a small set of trusted users. Because the conductor (a) holds long-lived credentials, (b) executes shell-level skills, and (c) ingests untrusted text from chat, voice, email, and the web, its security posture has to assume that **any inbound text is potentially adversarial** and **any outbound action may have real-world side effects**.

The defense is layered:

1. **Perimeter** — Keycloak SSO (RS256 JWT, OIDC) gates every human entry point; oauth2-proxy fronts the dashboard; channel allowlists gate Telegram, voice, and (planned) email.
2. **Pre-execution screen** — the **Bouncer** runs a 20+ pattern regex sweep plus an LLM negative pass on every prompt before it can reach an agent that holds tools.
3. **Capability scoping** — agents are spawned with explicit `AgentRole` + tool whitelist; conversation-only intents get zero tools; secrets are read on demand from Vaultwarden, never from disk.
4. **Skill safety** — trust tiers, gitleaks scan, and **Phantom Execution** sandbox runs gate every skill before it can touch live state.
5. **Adversarial self-hardening** — a Red/Blue agent pair continuously generates attacks against the conductor and feeds the Bouncer’s pattern library.
6. **Audit** — every long-term memory write is git-committed; every inference call is Langfuse-traced; the dashboard exposes a forensic Intel tab.

Nothing here is novel cryptography. The novelty is the integration: a single, spec-tracked story for how an autonomous agent handles untrusted input end-to-end.

---

## 1. Threat Model

### 1.1 Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| User credentials & API keys | Vaultwarden (S-023) | Cloud LLM quotas, payment surface, third-party blast radius |
| Episodic memory (7 tiers) | Postgres + git-tracked changelog (S-032, S-033) | Long-term knowledge of users, schedules, secrets-by-implication |
| Skills (`~/.conductor/skills/`) | Local disk, optionally pulled from ClawHub (S-035, S-037) | Arbitrary code paths the conductor can execute |
| Heartbeat task queue | In-memory + Obsidian inbox | Privileged background execution context (S-001) |
| Voice / phone / Telegram channels | HA Assist, ha_notify, Telegram bot (S-041–S-043, S-131) | Authenticated side-channel into the conductor |

### 1.2 Adversaries

| Adversary | Capability | Mitigation focus |
|---|---|---|
| **Prompt-injecting peer** | Sends crafted text in chat / email / voice transcript | Bouncer (S-022), capability scoping (S-024) |
| **Web content under tool control** | Search results, fetched pages, RSS, ClawHub skill READMEs | Bouncer on tool inputs, Phantom Execution on skills (S-030) |
| **Compromised cloud LLM response** | Model returns malicious tool call sequence | Tool whitelist per role, 3-round chat cap, Bouncer on tool args |
| **Malicious skill author** | Publishes a skill with a backdoor or exfil | Trust tiers, gitleaks, Phantom shadow run, ClawHub signing (S-111) |
| **Local network attacker** | LAN-side traffic to internal services | Keycloak SSO + oauth2-proxy in front of every service (S-017, S-018) |
| **Stolen device** | Has Telegram / mobile app session | Channel allowlist re-validation per request (S-131); JWT refresh + revocation |

### 1.3 Out of scope (today)

- Hardware compromise of the conductor host
- Supply-chain compromise of upstream LLM weights
- Side-channel timing attacks against the inference engine
- Multi-tenant isolation beyond per-user session scoping (S-010)

---

## 2. Architecture Overview

```
   inbound (untrusted)                       outbound (privileged)
   ──────────────────                       ────────────────────
        chat / voice                          shell / file / API
        email / web                                  ↑
              ↓                                      │
      [oauth2-proxy] ← SSO → [Keycloak]              │
              ↓                                      │
      [channel allowlist] ←────────────────────────────────│
              ↓                                      │
         [Bouncer] ─ regex + LLM screen ───────────│
              ↓                                      │
     [Intent Classifier] → ARTIFACT / CONVERSATION   │
              ↓                                      │
      [Agent Spawner] → AgentRole + tool whitelist   │
              ↓                                      │
         [Agent Loop] ─ Vaultwarden ─ Skills tier ───┘
              ↓                                      
     [Langfuse trace] + [git-tracked memory write]
```

Everything south of the Bouncer is treated as in-scope of the same trust boundary. The Bouncer + intent classifier + agent spawner is the canonical narrowing point: untrusted input becomes a typed `AgentSpec` with a finite tool list before it can do anything irreversible.

---

## 3. Layer-by-Layer

### 3.1 Identity & Access — Keycloak + oauth2-proxy

References: **S-017**, **S-018**, **S-019**, **S-024**

- **Single SSO**: 42 reverse-proxied services + 6 native OIDC services authenticate against one Keycloak realm. No service-local password store.
- **JWT**: RS256 (asymmetric). Conductor validates tokens against Keycloak’s JWKS endpoint; key rotation is automatic.
- **Role → tool mapping**: roles in JWT claims map to tool whitelists in `AgentSpec`. A role missing the `file_ops` claim cannot be granted file-write tools, ever, regardless of intent classification.
- **Dashboard**: `oauth2-proxy` sits in front of conductor-dash. No request reaches the dashboard backend without a valid Keycloak session.
- **OpenWebUI passthrough**: when chat originates from OpenWebUI, the upstream session is forwarded as `X-OpenWebUI-*` headers and re-validated rather than trusted blindly.

**Quick reference:**
```bash
# Verify a token before opening a PR that touches auth
curl -H "Authorization: Bearer $TOKEN" https://conductor/api/whoami
# Expected: { "sub": "...", "roles": ["conductor.tool.file_ops", ...] }
```

### 3.2 Secrets — Vaultwarden

References: **S-023**, **S-109**

- All API keys, channel tokens, DB passwords pulled from Vaultwarden at startup via its API.
- No plaintext in `.env`, no plaintext in config files, no plaintext in skills.
- `gitleaks` runs as a pre-commit hook and as a Bouncer step on every ClawHub install.
- **S-109** tracks the in-progress migration of legacy env-var secrets; the acceptance criterion is _zero plaintext secrets in any tracked config file_.

**Quick reference — adding a new secret:**
```bash
# 1. Store in Vaultwarden under collection `conductor/`
# 2. Reference by name in code, never by value:
secret = secrets.get("openai_api_key")  # raises if not present
# 3. Verify gitleaks is clean:
gitleaks detect --no-banner --redact
```

### 3.3 Input Filter — Bouncer

References: **S-022**, **S-026**

The Bouncer is a two-stage gate that every prompt and every tool argument passes through before reaching an agent that holds tools.

**Stage 1 — Regex sweep (synchronous, ~1ms):**
- 20+ patterns covering: prompt-injection idioms (“ignore previous instructions”), data-exfil patterns (suspicious URL constructions, base64 over thresholds), tool-coercion patterns (“run this command” outside a code block), and known jailbreak rituals.
- A regex hit is **non-recoverable**: the request is rejected with `TOOL_VIOLATION` or `SAFETY_VIOLATION` and logged to the dashboard Security tab.

**Stage 2 — LLM negative pass (asynchronous, ~200ms):**
- A small, fast model is asked the inverse question: _“Is there any reason this prompt should NOT be processed?”_
- Used for ambiguous cases where regex is too brittle (e.g., social-engineering attempts that don’t use known phrasings).

**Self-hardening loop — S-026:**
- A **Red agent** continuously generates attack prompts against a sandboxed conductor.
- A **Blue agent** observes which attacks succeed and proposes new regex patterns.
- Promoted patterns land in the Bouncer’s library after a human-review gate. Findings are surfaced in the dashboard.

### 3.4 Capability Scoping — AgentSpec

References: **S-002**, **S-005**, **S-003**, **S-004**, **S-007**, **S-010**

- An `AgentSpec` is an **immutable, typed envelope** declaring: role, model tier, tool whitelist, token budget, tool-call cap, trace ID, owning user_id.
- A `CONVERSATION` intent (S-004) gets the empty tool list. Period. No matter how the prompt phrased itself, a chat-classified turn cannot invoke a tool.
- `ARTIFACT` (S-003) gets `file_ops` write but no shell.
- Heartbeat-spawned tasks (S-105) are the only ones that get an extended tool-call cap, and only because their AgentSpec is constructed by the heartbeat runner (not by user input).
- **Per-user session isolation (S-010)**: `session_id` is scoped under `user_id`. Memory retrieval, tool grants, and context never cross user boundaries.

### 3.5 Skill Safety — Trust Tiers + Phantom Execution

References: **S-035**, **S-030**, **S-037**, **S-038**, **S-111**

A “skill” is a `SKILL.md` + executable bundle that the conductor can invoke. Trust is not binary:

| Tier | What it can do | How it gets there |
|---|---|---|
| **untrusted** | Read its own dir; no shell, no network | Default for newly forged or freshly installed skills |
| **shadow** | Run inside Phantom (sandbox; no real side effects) | After gitleaks pass; auto-promoted on Phantom success |
| **trusted** | Full skill capability (shell, network, file_ops) | After N successful Phantom runs + human review |
| **featured** | Surfaced in ClawHub recommendations | Top-of-leaderboard performance over time (S-112) |

- **Phantom Execution (S-030)** runs a candidate skill against synthetic inputs, captures all side-effect attempts (writes, network calls, env reads), and reports them to the dashboard.
- **Skill Forge (S-038)** — when the conductor writes a *new* skill on demand, it is born untrusted and *must* go through Phantom before it can be installed.
- **ClawHub publishing (S-111, planned)** — published skills will be signed; install-time signature verification before trust promotion.

### 3.6 Channel Hardening

References: **S-131**, **S-041**, **S-103**, **S-019**

- **Telegram (S-131):** allowlist accepts `telegram:` and `tg:` prefixes case-insensitively, trims whitespace, ignores empty entries. Aligns inbound check with outbound normalization — no false-negatives from copy-paste artifacts.
- **Voice (S-041, S-042):** Alexa → HA Assist → conductor with HA-side authentication; voice intents flow through the same Bouncer + intent classifier as text.
- **Email (S-103, planned):** sender allowlist before any task creation; outbound via SMTP/API only for digests and P0 alerts.
- **OpenWebUI (S-019):** trust headers only when origin is the OpenWebUI host on a trusted network segment.

### 3.7 Audit — Langfuse + git-tracked memory

References: **S-021**, **S-033**, **S-028**, **S-016**

- **Langfuse** traces every inference call: prompt, model, tools called, tokens, latency, score. The dashboard’s Intel tab is a Langfuse trace browser with annotation scoring.
- **Memory evolution history (S-033)**: every write to long-term memory is git-committed with a structured message. Diffable audit trail; you can `git blame` a stale belief.
- **Context Archaeology (S-028)**: on task failure, reconstructs the decision chain from traces, memory layers, and tool calls. Designed for forensic post-mortem rather than line-by-line debugging.
- **Dashboard surfacing (S-016)**: Security tab lists Bouncer denials, Red Team findings, and pending Phantom reports.

---

## 4. Adversarial Self-Hardening

References: **S-026**, **S-027**, **S-113** (planned)

The conductor doesn’t wait to be attacked in production:

- **Red/Blue (S-026)** runs continuously. The Red agent has the prompt history of recent successful Bouncer denials and a free-form mandate to find one new bypass. The Blue agent watches for Red successes against a sandboxed twin and proposes patches.
- **Tournament Arena (S-027)** scores models on structured attack-defense tasks; ELO-style leaderboard tracks which model+prompt combinations are most resistant.
- **Stress Rehearsal (S-113, planned)** layers in chaos: timeouts, OOM, partial tool failures, malformed inputs. Verifies that degraded states fail closed (refuse) rather than open (proceed with a guess).

This loop is not a substitute for human review of patches — promoted Bouncer patterns and trust-tier promotions both go through a manual gate — but it dramatically expands the attack surface that gets explored before a human ever sees it.

---

## 5. Comparison Framework (vs. OpenClaw)

This table is the comparison axis we’d run against any peer system. The maistro column is filled in below; the OpenClaw column is intentionally blank pending access to that codebase.

| Axis | Project mAIstro | OpenClaw |
|---|---|---|
| **AuthN** | Keycloak RS256 JWT, OIDC, JWKS rotation (S-024) | _TBD_ |
| **AuthZ** | Role → tool whitelist in `AgentSpec`; per-user session scope (S-010) | _TBD_ |
| **Perimeter** | oauth2-proxy + Keycloak in front of every service (S-017, S-018) | _TBD_ |
| **Secrets management** | Vaultwarden API; no plaintext on disk; gitleaks pre-commit (S-023, S-109) | _TBD_ |
| **Prompt-injection defense** | Bouncer: 20+ regex + LLM negative pass (S-022) | _TBD_ |
| **Capability scoping** | Typed `AgentSpec`, immutable, role-keyed tool whitelist (S-002–S-005) | _TBD_ |
| **Tool / skill sandboxing** | 4-tier trust + Phantom Execution shadow run (S-030, S-035) | _TBD_ |
| **Marketplace integrity** | gitleaks scan + (planned) signed publishes (S-037, S-111) | _TBD_ |
| **Channel allowlists** | Telegram normalized (S-131); voice/email allowlist (S-041, S-103) | _TBD_ |
| **Audit trail** | Langfuse traces + git-committed memory writes (S-021, S-033) | _TBD_ |
| **Adversarial self-test** | Continuous Red/Blue (S-026); Tournament Arena (S-027) | _TBD_ |
| **Forensic post-mortem** | Context Archaeology (S-028); Intel dashboard tab (S-016) | _TBD_ |
| **Per-tenant isolation** | Per-user session_id scope; memory retrieval keyed on user_id (S-010) | _TBD_ |
| **Failure-closed default** | Bouncer hits return non-recoverable; default tool list is empty (S-004) | _TBD_ |
| **Disclosure / response** | `SECURITY.md` at repo root | _TBD_ |

Fill the right column once OpenClaw is in scope. The rows are ordered roughly by blast radius if a layer fails.

---

## 6. Known Gaps & Roadmap

| Gap | Spec | Status |
|---|---|---|
| Plaintext secrets remain in some legacy configs | S-109 | in progress |
| Dashboard still HTTP-only inside the LAN | S-101 | planned |
| ClawHub publishes are not yet signed | S-111 | planned |
| Skill pruning is manual; weak skills accumulate | S-112 | planned |
| Chaos coverage is informal | S-113 | planned |
| Cross-instance memory sharing has no privacy story | S-114 | research |
| Heartbeat-task tool-call cap is implicit, not spec’d as a security control | S-105 | draft |
| Confidence decay on stale learnings is not implemented | S-107 | draft |

Nothing in this list represents a known exploitable hole; they are places where a defense-in-depth layer is incomplete or where a control is enforced in code but not yet codified in a spec.

---

## 7. Quick Reference

**For an operator deploying a fresh node:**

1. Stand up Keycloak + Vaultwarden first. Seed the realm and the secrets vault.
2. Bring up oauth2-proxy in front of conductor-dash.
3. Configure `LITELLM_*` and `LANGFUSE_*` from Vaultwarden, never from `.env`.
4. Add your channel allowlist (`TELEGRAM_ALLOWLIST`, `VOICE_ALLOWLIST`).
5. Run `gitleaks detect` on any config you wrote during setup.
6. Smoke-test the Bouncer with a known prompt-injection payload — it should be rejected with `SAFETY_VIOLATION`.

**For a contributor adding a tool:**

1. Add the tool to a role’s whitelist in `agent_spec.py` — do not bypass `AgentSpec`.
2. Decide which intent classifier branches can route to roles that hold the tool. Only those branches.
3. Write a SKILL.md, run it through Phantom locally, and submit with the trace.
4. If the tool reads a secret, use `secrets.get("name")`, never `os.environ`.

**For a reviewer evaluating a PR:**

1. Did anything bypass the Bouncer? (Search for `bouncer.skip` or equivalent.)
2. Did anything add a tool to `CONVERSATION` role? (Should be empty, always.)
3. Did any new file land in `~/.conductor/skills/` without going through Phantom? (Check the trace.)
4. Did the diff add any `os.environ` reads of secret-shaped names? (Use Vaultwarden.)
5. Does any new channel ingress re-validate against an allowlist on every request, not just at session start?

---

## 8. References

All references are stable spec IDs in `specs/`. Each spec carries its own acceptance criteria, file pointers, and verification steps.

- Auth & perimeter: [S-017](S-017-dashboard-auth.md placeholder — actual: `../infra/S-017-dashboard-auth.md`), [S-018](../infra/S-018-keycloak-migration.md), [S-019](../infra/S-019-openwebui-jwt.md), [S-024](S-024-jwt-auth.md)
- Secrets: [S-023](S-023-secrets-manager.md), [S-109](S-109-secrets-migration.md)
- Input filter: [S-022](S-022-bouncer.md), [S-026](../intelligence/S-026-adversarial-hardening.md)
- Capability scoping: [S-002](../conductor/S-002-factory-spawner.md), [S-003](../conductor/S-003-artifact-intent.md), [S-004](../conductor/S-004-conversation-intent.md), [S-005](../conductor/S-005-agent-factory.md), [S-007](../conductor/S-007-3-phase-classifier.md), [S-010](../conductor/S-010-session-isolation.md)
- Skills: [S-030](../intelligence/S-030-phantom-execution.md), [S-035](../tools/S-035-skills-subsystem.md), [S-037](../tools/S-037-clawhub.md), [S-038](../tools/S-038-skill-forge.md), [S-111](../tools/S-111-clawhub-full.md), [S-112](../tools/S-112-skill-evolution.md)
- Channels: [S-041](../channels/S-041-voice-agent.md), [S-103](../channels/S-103-email-channel.md), [S-131](S-131-group-policy-hardening.md)
- Audit: [S-016](../infra/S-016-dashboard-ui.md), [S-021](../infra/S-021-service-integration.md), [S-028](../intelligence/S-028-context-archaeology.md), [S-033](../intelligence/S-033-memory-evolution.md)
- Self-hardening: [S-026](../intelligence/S-026-adversarial-hardening.md), [S-027](../intelligence/S-027-tournament-arena.md), [S-113](../tools/S-113-stress-rehearsal.md)

Disclosure policy and contact: see [`SECURITY.md`](../../SECURITY.md) at the repo root.
