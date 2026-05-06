# Project mAIstro — Security Architecture

_A white paper / README hybrid. Read top-to-bottom for the design rationale, or jump to **Quick Reference** if you just need to wire something up._

**Status:** living document
**Last updated:** 2026-04-25 (OpenClaw comparison filled in from public sources)
**Audience:** operators deploying maistro, contributors adding tools or channels, reviewers evaluating it against alternatives.

---

## TL;DR

Project mAIstro is an autonomous orchestrator (the "conductor") that runs persistent agents, schedules background work, and manages a skill / tool ecosystem on behalf of a small set of trusted users. Because the conductor (a) holds long-lived credentials, (b) executes shell-level skills, and (c) ingests untrusted text from chat, voice, email, and the web, its security posture has to assume that **any inbound text is potentially adversarial** and **any outbound action may have real-world side effects**.

The defense is layered:

1. **Perimeter** — Keycloak SSO (RS256 JWT, OIDC) gates every human entry point; oauth2-proxy fronts the dashboard; channel allowlists gate Telegram, voice, and (planned) email.
2. **Pre-execution screen** — the **Bouncer** runs a 20+ pattern regex sweep plus an LLM negative pass on every prompt before it can reach an agent that holds tools.
3. **Capability scoping** — agents are spawned with explicit `AgentRole` + tool whitelist; conversation-only intents get zero tools; secrets are read on demand from Vaultwarden, never from disk.
4. **Skill safety** — trust tiers, gitleaks scan, and **Phantom Execution** sandbox runs gate every skill before it can touch live state.
5. **Adversarial self-hardening** — a Red/Blue agent pair continuously generates attacks against the conductor and feeds the Bouncer's pattern library.
6. **Audit** — every long-term memory write is git-committed; every inference call is Langfuse-traced; the dashboard exposes a forensic Intel tab.

Nothing here is novel cryptography. The novelty is the integration: a single, spec-tracked story for how an autonomous agent handles untrusted input end-to-end.

---

## 1. Threat Model

### 1.1 Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| User credentials & API keys | Vaultwarden (S-023) | Cloud LLM quotas, payment surface, third-party blast radius |
| Episodic memory (7 tiers) | Postgres + git-tracked changelog (S-032, S-033) | Long-term knowledge of users, schedules, secrets-by-implication |
| Skills (`~/.conductor/skills/`) | Local disk, optionally pulled from Medley (S-035, S-037) | Arbitrary code paths the conductor can execute |
| Heartbeat task queue | In-memory + Obsidian inbox | Privileged background execution context (S-001) |
| Voice / phone / Telegram channels | HA Assist, ha_notify, Telegram bot (S-041–S-043, S-131) | Authenticated side-channel into the conductor |

### 1.2 Adversaries

| Adversary | Capability | Mitigation focus |
|---|---|---|
| **Prompt-injecting peer** | Sends crafted text in chat / email / voice transcript | Bouncer (S-022), capability scoping (S-024) |
| **Web content under tool control** | Search results, fetched pages, RSS, Medley plugin READMEs | Bouncer on tool inputs, Phantom Execution on skills (S-030) |
| **Compromised cloud LLM response** | Model returns malicious tool call sequence | Tool whitelist per role, 3-round chat cap, Bouncer on tool args |
| **Malicious skill author** | Publishes a skill with a backdoor or exfil | Trust tiers, gitleaks, Phantom shadow run, Medley publisher VCs (S-111) |
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
- **JWT**: RS256 (asymmetric). Conductor validates tokens against Keycloak's JWKS endpoint; key rotation is automatic.
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
- `gitleaks` runs as a pre-commit hook and as a Bouncer step on every Medley install.
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
- 20+ patterns covering: prompt-injection idioms ("ignore previous instructions"), data-exfil patterns (suspicious URL constructions, base64 over thresholds), tool-coercion patterns ("run this command" outside a code block), and known jailbreak rituals.
- A regex hit is **non-recoverable**: the request is rejected with `TOOL_VIOLATION` or `SAFETY_VIOLATION` and logged to the dashboard Security tab.

**Stage 2 — LLM negative pass (asynchronous, ~200ms):**
- A small, fast model is asked the inverse question: _"Is there any reason this prompt should NOT be processed?"_
- Used for ambiguous cases where regex is too brittle (e.g., social-engineering attempts that don't use known phrasings).

**Self-hardening loop — S-026:**
- A **Red agent** continuously generates attack prompts against a sandboxed conductor.
- A **Blue agent** observes which attacks succeed and proposes new regex patterns.
- Promoted patterns land in the Bouncer's library after a human-review gate. Findings are surfaced in the dashboard.

### 3.4 Capability Scoping — AgentSpec

References: **S-002**, **S-005**, **S-003**, **S-004**, **S-007**, **S-010**

- An `AgentSpec` is an **immutable, typed envelope** declaring: role, model tier, tool whitelist, token budget, tool-call cap, trace ID, owning user_id.
- A `CONVERSATION` intent (S-004) gets the empty tool list. Period. No matter how the prompt phrased itself, a chat-classified turn cannot invoke a tool.
- `ARTIFACT` (S-003) gets `file_ops` write but no shell.
- Heartbeat-spawned tasks (S-105) are the only ones that get an extended tool-call cap, and only because their AgentSpec is constructed by the heartbeat runner (not by user input).
- **Per-user session isolation (S-010)**: `session_id` is scoped under `user_id`. Memory retrieval, tool grants, and context never cross user boundaries.

### 3.5 Skill Safety — Trust Tiers + Phantom Execution

References: **S-035**, **S-030**, **S-037**, **S-038**, **S-111**

A "skill" is a `SKILL.md` + executable bundle that the conductor can invoke. Trust is not binary:

| Tier | What it can do | How it gets there |
|---|---|---|
| **untrusted** | Read its own dir; no shell, no network | Default for newly forged or freshly installed skills |
| **shadow** | Run inside Phantom (sandbox; no real side effects) | After gitleaks pass; auto-promoted on Phantom success |
| **trusted** | Full skill capability (shell, network, file_ops) | After N successful Phantom runs + human review |
| **featured** | Surfaced in Medley featured recommendations | Top-of-leaderboard performance over time (S-112) |

- **Phantom Execution (S-030)** runs a candidate skill against synthetic inputs, captures all side-effect attempts (writes, network calls, env reads), and reports them to the dashboard.
- **Skill Forge (S-038)** — when the conductor writes a *new* skill on demand, it is born untrusted and *must* go through Phantom before it can be installed.
- **Medley publishing (S-111)** — published plugins ship with publisher VCs (S-152); install-time verification of the VC against the publisher's DID document gates trust promotion. Unsigned plugins require explicit `--allow-unsigned` + admin signature.

### 3.6 Channel Hardening

References: **S-131**, **S-041**, **S-103**, **S-019**

- **Telegram (S-131):** allowlist accepts `telegram:` and `tg:` prefixes case-insensitively, trims whitespace, ignores empty entries. Aligns inbound check with outbound normalization — no false-negatives from copy-paste artifacts.
- **Voice (S-041, S-042):** Alexa → HA Assist → conductor with HA-side authentication; voice intents flow through the same Bouncer + intent classifier as text.
- **Email (S-103, planned):** sender allowlist before any task creation; outbound via SMTP/API only for digests and P0 alerts.
- **OpenWebUI (S-019):** trust headers only when origin is the OpenWebUI host on a trusted network segment.

### 3.7 Audit — Langfuse + git-tracked memory

References: **S-021**, **S-033**, **S-028**, **S-016**

- **Langfuse** traces every inference call: prompt, model, tools called, tokens, latency, score. The dashboard's Intel tab is a Langfuse trace browser with annotation scoring.
- **Memory evolution history (S-033)**: every write to long-term memory is git-committed with a structured message. Diffable audit trail; you can `git blame` a stale belief.
- **Context Archaeology (S-028)**: on task failure, reconstructs the decision chain from traces, memory layers, and tool calls. Designed for forensic post-mortem rather than line-by-line debugging.
- **Dashboard surfacing (S-016)**: Security tab lists Bouncer denials, Red Team findings, and pending Phantom reports.

---

## 4. Adversarial Self-Hardening

References: **S-026**, **S-027**, **S-113** (planned)

The conductor doesn't wait to be attacked in production:

- **Red/Blue (S-026)** runs continuously. The Red agent has the prompt history of recent successful Bouncer denials and a free-form mandate to find one new bypass. The Blue agent watches for Red successes against a sandboxed twin and proposes patches.
- **Tournament Arena (S-027)** scores models on structured attack-defense tasks; ELO-style leaderboard tracks which model+prompt combinations are most resistant.
- **Stress Rehearsal (S-113, planned)** layers in chaos: timeouts, OOM, partial tool failures, malformed inputs. Verifies that degraded states fail closed (refuse) rather than open (proceed with a guess).

This loop is not a substitute for human review of patches — promoted Bouncer patterns and trust-tier promotions both go through a manual gate — but it dramatically expands the attack surface that gets explored before a human ever sees it.

---

## 5. Comparison — Project mAIstro vs. OpenClaw

OpenClaw is the most-starred open-source personal-AI-agent project of early 2026 (>150K GitHub stars within weeks of launch). Its surface looks similar to maistro's: a local gateway daemon (`ws://127.0.0.1:18789`, systemd / LaunchAgent), a skill ecosystem with thousands of community contributions, and integrations with messaging platforms. It has therefore drawn the most public security analysis of any agent framework in this class — including a CrowdStrike write-up flagging it as a potential "AI backdoor" risk when misconfigured, and a Cisco AI-security finding that a third-party OpenClaw skill performed undisclosed data exfiltration. The canonical hardening guide is `slowmist/openclaw-security-practice-guide` (v2.8 at time of writing).

The two systems share a threat surface but make different bets about *where* to put the defense. The table below maps maistro’s controls onto the same axes used in OpenClaw’s public guide; the discussion in 5.1 explains where the philosophies diverge.

| Axis | Project mAIstro | OpenClaw |
|---|---|---|
| **AuthN** | Keycloak RS256 JWT, OIDC, JWKS rotation (S-024) | No formal AuthN. Gateway daemon binds to `ws://127.0.0.1:18789` and trusts the local-machine boundary. Hardening guide relies on `chmod 600` on token files and OS-level user separation. |
| **AuthZ** | Role → tool whitelist in `AgentSpec`; per-user session scope (S-010) | "Permission narrowing & Cross-Skill Pre-flight Checks" enforced by the engine + agent self-judgment, not a typed capability envelope. `exec-approvals.json` is the runtime authorization surface. |
| **Perimeter** | oauth2-proxy + Keycloak in front of every service (S-017, S-018) | None native. Loopback-only WebSocket; remote exposure (e.g., on a VPS) is the operator's responsibility and is the headline misconfiguration vector flagged by CrowdStrike. |
| **Secrets management** | Vaultwarden API; no plaintext on disk; gitleaks pre-commit (S-023, S-109) | File-separated tokens with `chmod 600` (e.g., Telegram bot token). Optional advice: "instruct the Agent to encrypt the data before executing" git backups. No vault integration in the core guide. |
| **Prompt-injection defense** | Bouncer: 20+ regex + LLM negative pass on every prompt (S-022) | "Behavior blacklists" + agent self-policing against a red-line command list. Acknowledged limitation: "relies on the AI Agent autonomously determining whether a command hits a red line" — weaker models systematically misjudge. |
| **Capability scoping** | Typed `AgentSpec`, immutable, role-keyed tool whitelist (S-002–S-005) | In-action permission narrowing; configuration in `openclaw.json` / `exec-approvals.json`. No equivalent of an empty-tools `CONVERSATION` role. |
| **Tool / skill sandboxing** | 4-tier trust + Phantom Execution shadow run (S-030, S-035) | Skill *inspection* on install, update, abnormal behavior, or fingerprint mismatch. `chattr +i` to lock core configs (note: never `exec-approvals.json`). No shadow-execution sandbox in the public guide. |
| **Marketplace integrity** | gitleaks scan + signed publisher VCs (S-037, S-111) | Skill registry exists (>5,400 skills via VoltAgent's curated awesome-list). Cisco found a malicious skill performing data exfiltration, noting "the skill repository lacked adequate vetting." |
| **Channel allowlists** | Telegram normalized (S-131); voice/email allowlist (S-041, S-103) | Telegram bot token handling covered for audit notifications; broader channel allowlists not in the guide. |
| **Audit trail** | Langfuse traces (per-call) + git-committed memory writes (S-021, S-033) | Nightly automated audit, 13 core metrics, persistent reports in `$OC/security-reports/` with 30-day rotation. Brain-git backup for disaster recovery. |
| **Real-time vs post-hoc** | Real-time (Bouncer pre-execution) + per-call traces | Explicitly post-hoc: "Nightly audits … can only discover anomalies that have already occurred and cannot roll back damage already done." |
| **Adversarial self-test** | Continuous Red/Blue (S-026); Tournament Arena (S-027) | Validation guides for red-teaming exist (`Validation-Guide-en.md`); not described as continuous. |
| **Forensic post-mortem** | Context Archaeology (S-028); Intel dashboard tab (S-016) | Nightly audit reports + git history of the "Brain" workspace. |
| **Per-tenant isolation** | Per-user session_id scope; memory retrieval keyed on user_id (S-010) | Single-user model by design. v2.8 adds `--light-context` cron protection to keep audit sessions from being hijacked by workspace context. |
| **Failure-closed default** | Bouncer hits return non-recoverable; default tool list is empty (S-004) | "When in doubt, treat it as a red line" — fail-closed *philosophy*, but enforced by the agent's own judgment rather than a hard gate. |
| **Engine trust assumption** | Conductor binary is trusted; secrets and tools never leave the orchestrator process | Same. Guide explicitly: "all built on the assumption that 'the engine itself is trustworthy' and cannot defend against engine-level vulnerabilities." |
| **Disclosure / response** | `SECURITY.md` at repo root | GitHub Security tab; SlowMist guide is community-maintained. |

### 5.1 Where the philosophies diverge

**Pre-execution gate vs. behavioral red-lines.**
maistro's Bouncer is a hard, code-driven filter: regex hits return non-recoverable errors. OpenClaw's red-line system asks the *agent itself* whether a command crosses a line, with the operator backstopping via nightly audits. The OpenClaw guide is upfront that this depends on model strength — "weaker models may systematically misjudge." maistro pays for the harder gate with brittleness (regex misses novel attacks; the LLM negative pass catches some but not all), but the failure mode is observable in real time, not a 24-hour audit cycle later.

**Capability typing vs. runtime config.**
maistro's `AgentSpec` is constructed by code paths the operator controls (intent classifier, heartbeat runner) and is immutable for the duration of a turn. OpenClaw's permissions live in `exec-approvals.json` and are enforced at execution time by the engine. The OpenClaw guide warns to *not* `chattr +i` that file because the engine writes to it at runtime — which is exactly the surface maistro avoids by making the capability envelope a constructed Python object that never round-trips through disk.

**Skill safety: shadow-run vs. fingerprint.**
OpenClaw's skill model trusts post-install audit + fingerprint matching to detect tampering after the fact. maistro inserts Phantom Execution *before* a skill ever runs against live state: any side-effect attempt (writes, network calls, env reads) is recorded against a synthetic input set. The Cisco finding (a malicious skill performing data exfil that the registry's review missed) is exactly the failure mode Phantom is designed to catch — not by reading the skill's code, but by watching what it *does* in a sandboxed run.

**Secrets: vault vs. file permissions.**
Vaultwarden gives maistro per-secret access logs and revocation. OpenClaw's `chmod 600` model is simpler and works without external infrastructure, but every skill the agent runs inherits the agent's UID and therefore every file readable by it. maistro pays for this with operational complexity (a Vaultwarden instance must exist and be healthy) but gains the ability to scope, rotate, and audit secret reads.

**Audit cadence.**
Langfuse-per-call vs. nightly is the most striking gap. maistro's audit signal is available at debug time ("why did this agent call that tool with these args?") and at incident time ("replay the last 24 hours of denials"). OpenClaw's nightly model is cheaper to run but, by the guide's own admission, cannot prevent or roll back damage — only detect it.

**Perimeter.**
The largest delta. maistro assumes an adversarial LAN and gates every service behind Keycloak + oauth2-proxy. OpenClaw assumes a trusted local machine and pushes the perimeter responsibility entirely onto the operator. CrowdStrike's risk write-up is essentially a long way of saying "users misconfigure perimeters, and OpenClaw provides nothing native to stop them."

### 5.2 Where OpenClaw is ahead (or equivalent)

- **Filesystem immutability**: `chattr +i` on core config files is a layer maistro doesn't currently have. Adding the equivalent to conductor configs (everywhere except files the engine must write at runtime) is cheap and should be on the roadmap. _→ Action: file as a follow-up spec._
- **Operational simplicity**: OpenClaw runs without Keycloak, Vaultwarden, Postgres, oauth2-proxy. For a single-machine deploy, the maistro stack is heavier. The tradeoff is deliberate — maistro is built for multi-channel, multi-user use — but worth being honest about.
- **Public security ecosystem**: SlowMist's third-party hardening guide, VoltAgent's curated awesome-skills list, and the broader audit volume around OpenClaw represent battle-testing maistro can’t match by virtue of scale. The right response is to keep the spec tree open and the threat model explicit, so external review is tractable.

### 5.3 Where they share assumptions (and therefore share risks)

Both systems explicitly assume the engine itself is trustworthy. Neither defends against:
- A compromised inference backend returning malicious tool-call sequences (maistro mitigates partially via per-call Langfuse + Bouncer on tool args; OpenClaw via permission narrowing; neither *prevents* it).
- Supply-chain compromise of upstream LLM weights.
- Hardware-level compromise of the host.
- Any vulnerability in the orchestrator binary itself.

This is a real residual risk and should be stated plainly to operators of either system.

---

## 6. Known Gaps & Roadmap

| Gap | Spec | Status |
|---|---|---|
| Plaintext secrets remain in some legacy configs | S-109 | in progress |
| Dashboard still HTTP-only inside the LAN | S-101 | planned |
| Medley publishes are not yet signed (publisher VC verification) | S-111 | drafted |
| Skill pruning is manual; weak skills accumulate | S-112 | planned |
| Chaos coverage is informal | S-113 | planned |
| Cross-instance memory sharing has no privacy story | S-114 | research |
| Heartbeat-task tool-call cap is implicit, not spec'd as a security control | S-105 | draft |
| Confidence decay on stale learnings is not implemented | S-107 | draft |
| No filesystem-level immutability on core configs (parity with OpenClaw `chattr +i`) | _new_ | proposed (follow-up to this comparison) |

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

1. Add the tool to a role's whitelist in `agent_spec.py` — do not bypass `AgentSpec`.
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

### maistro specs

All references are stable spec IDs in `specs/`. Each spec carries its own acceptance criteria, file pointers, and verification steps.

- Auth & perimeter: [S-017](../infra/S-017-dashboard-auth.md), [S-018](../infra/S-018-keycloak-migration.md), [S-019](../infra/S-019-openwebui-jwt.md), [S-024](S-024-jwt-auth.md)
- Secrets: [S-023](S-023-secrets-manager.md), [S-109](S-109-secrets-migration.md)
- Input filter: [S-022](S-022-bouncer.md), [S-026](../intelligence/S-026-adversarial-hardening.md)
- Capability scoping: [S-002](../conductor/S-002-factory-spawner.md), [S-003](../conductor/S-003-artifact-intent.md), [S-004](../conductor/S-004-conversation-intent.md), [S-005](../conductor/S-005-agent-factory.md), [S-007](../conductor/S-007-3-phase-classifier.md), [S-010](../conductor/S-010-session-isolation.md)
- Skills + Medley: [S-030](../intelligence/S-030-phantom-execution.md), [S-035](../tools/S-035-skills-subsystem.md), [S-037](../tools/S-037-clawhub.md), [S-038](../tools/S-038-skill-forge.md), [S-111](../tools/S-111-clawhub-full.md), [S-112](../tools/S-112-skill-evolution.md)
- Channels: [S-041](../channels/S-041-voice-agent.md), [S-103](../channels/S-103-email-channel.md), [S-131](S-131-group-policy-hardening.md)
- Audit: [S-016](../infra/S-016-dashboard-ui.md), [S-021](../infra/S-021-service-integration.md), [S-028](../intelligence/S-028-context-archaeology.md), [S-033](../intelligence/S-033-memory-evolution.md)
- Self-hardening: [S-026](../intelligence/S-026-adversarial-hardening.md), [S-027](../intelligence/S-027-tournament-arena.md), [S-113](../tools/S-113-stress-rehearsal.md)

### OpenClaw sources (used for §5 comparison)

- OpenClaw repo: https://github.com/openclaw/openclaw
- OpenClaw `AGENTS.md`: https://github.com/openclaw/openclaw/blob/main/AGENTS.md
- SlowMist Security Practice Guide (v2.7 / v2.8): https://github.com/slowmist/openclaw-security-practice-guide
- VoltAgent curated skills index: https://github.com/VoltAgent/awesome-openclaw-skills
- CrowdStrike risk write-up: https://www.crowdstrike.com/en-us/blog/what-security-teams-need-to-know-about-openclaw-ai-super-agent/
- NVIDIA / Nemotron Labs commentary: https://blogs.nvidia.com/blog/what-openclaw-agents-mean-for-every-organization/
- freeCodeCamp build-and-secure walkthrough: https://www.freecodecamp.org/news/how-to-build-and-secure-a-personal-ai-agent-with-openclaw

Disclosure policy and contact: see [`SECURITY.md`](../../SECURITY.md) at the repo root.
