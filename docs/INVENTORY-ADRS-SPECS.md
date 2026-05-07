# ADR & Spec Inventory — Cross-Repo

Generated 2026-05-07. Branch: `claude/inventory-adrs-specs-IWHK5`.

This document inventories all Architecture Decision Records (ADRs) and
specification documents across the four sibling repositories
(`maistro-engine`, `AgentTuring`, `stronghold`, `Project_mAIstro`) and maps
them to the layers of the agentic-AI reference architecture
(User/Client → Orchestration → Agents → Tools → Memory → Monitoring →
Reliability → Governance → Foundation).

`AgentTuring` and `Agent-StrongHold/stronghold` are sibling forks with
near-identical trees at the time of this snapshot — most ADR/spec blobs
share SHAs across the two repos. Where contents diverge it is called out
explicitly.

## Counts at a glance

| Repo | ADRs | Top-level specs | Nested specs | Notes |
|---|---:|---:|---:|---|
| `maistro-engine` | 20 (ADR-000…019) | 0 | 0 | Engine-level decisions only; no `specs/` tree |
| `AgentTuring` | 31 (ADR-K8S-001…031) | 22 (`specs/*.yaml`) | ~70 (`docs/specs/epic-01…14/`) | Spec workflow lives under `docs/specs/` |
| `stronghold` | 31 (mirror of AgentTuring) | 22 (mirror) | ~70 (mirror) | Sibling fork; expect drift over time |
| `Project_mAIstro` | 0 | 2 (`SPEC-TEMPLATE`, `TIMELINE`) | 91 (`specs/<area>/S-NNN-*.md`) | `S-NNN` numbered backlog, no ADRs |

Total visible ADR/spec artifacts across the four repos: ~270 (with
significant duplication between AgentTuring and stronghold).

---

## 1. `BlakeMatthews-dev/maistro-engine`

### ADRs (`docs/adr/`, 20 files)

Engine-internal architectural decisions. Numbering is sequential
(`ADR-NNN`) and scoped to the workflow engine.

| ID | Title | Architecture layer |
|---|---|---|
| ADR-000 | template | — |
| ADR-001 | branching-strategy | Foundation / Process |
| ADR-002 | porting-workflow | Foundation / Process |
| ADR-003 | openclaw-gap-resolution | Orchestration |
| ADR-004 | agent-spec | Agent Layer |
| ADR-005 | schemas | Orchestration / State |
| ADR-006 | recipe-registry | Orchestration / Plan |
| ADR-007 | variant-selector | Orchestration / Router |
| ADR-008 | structured-output-parser | Agent Layer |
| ADR-009 | spawner | Orchestration / Scheduler |
| ADR-010 | lane-scheduling | Orchestration / Scheduler |
| ADR-011 | memory-engine | Memory & Knowledge |
| ADR-012 | alembic-migration | Foundation / Data Storage |
| ADR-013 | memory-types | Memory & Knowledge |
| ADR-014 | memory-protocols | Memory & Knowledge |
| ADR-015 | learning-store | Memory & Knowledge |
| ADR-016 | episodic-store | Memory & Knowledge |
| ADR-017 | outcome-store | Memory & Knowledge |
| ADR-018 | task-record-persistence | State & Context Manager |
| ADR-019 | canonical-source-split | Foundation / Process |

### Specs

No `specs/` tree exists in this repo. Closest analogues:

- `AUDIT.md`, `CONSOLIDATION-PLAN.md` (root)
- `docs/anthropic-agent-framework.md`
- `docs/claude-quality-enforcement.md`
- `docs/quality-standards.md`
- `docs/testing-audit.md`
- `docs/analysis/` (directory; not enumerated)

---

## 2. `BlakeMatthews-dev/AgentTuring` (and `Agent-StrongHold/stronghold` mirror)

### ADRs (`docs/adr/`, 31 files + README)

All prefixed `ADR-K8S-` — focused on Kubernetes/runtime topology, identity,
and the catalog/builder ecosystem.

| ID | Title | Architecture layer |
|---|---|---|
| K8S-001 | namespace-topology | Foundation / Infrastructure |
| K8S-002 | rbac-boundary | Governance & Security |
| K8S-003 | secrets-approach | Governance / Secrets |
| K8S-004 | networkpolicy-posture | Governance & Security |
| K8S-005 | warden-topology | Governance & Security |
| K8S-006 | runtime-okd | Foundation / Infrastructure |
| K8S-007 | distro-compatibility-matrix | Foundation / Infrastructure |
| K8S-008 | prod-dev-isolation | Foundation / Infrastructure |
| K8S-009 | migration-sequence | Foundation / Process |
| K8S-010 | storage-pluggability | Foundation / Data Storage |
| K8S-011 | secrets-provider-pluggability | Governance / Secrets |
| K8S-012 | crc-sandbox | Foundation / Infrastructure |
| K8S-013 | hybrid-execution-model | Orchestration |
| K8S-014 | six-tier-priority-system | Orchestration / Scheduler |
| K8S-015 | priority-tier-eviction-order | Orchestration / Scheduler |
| K8S-016 | gitops-controller | Foundation / CI-CD |
| K8S-017 | architecture-diagram-pipeline | Foundation / Process |
| K8S-018 | per-user-credential-vault | Governance / Secrets |
| K8S-019 | tool-policy-layer | Governance / Policy |
| K8S-020 | mcp-server-gateway-orchestrator | Tools & Integrations |
| K8S-021 | tool-catalog | Tools & Integrations |
| K8S-022 | skill-catalog | Agent Layer |
| K8S-023 | resource-catalog | Tools & Integrations |
| K8S-024 | mcp-transport-auth-discovery | Tools & Integrations |
| K8S-025 | sandboxed-primitive-mcp-guests | Tools & Integrations |
| K8S-026 | sandbox-pod-catalog | Tools & Integrations |
| K8S-027 | agent-catalog | Agent Layer |
| K8S-028 | stronghold-as-a2a-peer | Agent Layer / A2A |
| K8S-029 | a2a-guest-peers | Agent Layer / A2A |
| K8S-030 | task-acceptance-policy | Orchestration / Policy |
| K8S-031 | builder-capabilities | Agent Layer |

### Top-level specs (`specs/`, 22 files)

Pipeline/feature YAML specs driving the Turing console and pipeline phases.

| Spec | Architecture layer |
|---|---|
| `TURING-CONSOLE-README.md` | User/Client (console UI) |
| `archie-property-gen.yaml` | Agent Layer (architect agent) |
| `complexity-triage.yaml` | Orchestration / Task Decomposition |
| `phase1-pipeline-wiring.yaml` | Orchestration |
| `phase2-verifier.yaml` | Reliability / Verification |
| `phase3-plan-caching.yaml` | Foundation / Cache |
| `phase4-agent-configs.yaml` | Agent Layer |
| `prompt-caching.yaml` | Foundation / Cache |
| `quartermaster-spec-emission.yaml` | Orchestration / Spec emission |
| `rca-structured-output.yaml` | Agent Layer (RCA agent) |
| `spec-enriched-prompts.yaml` | Agent Layer / Prompting |
| `turing-blog-authoring.yaml` | Agent Layer (authoring) |
| `turing-chat-streaming.yaml` | User/Client (chat) |
| `turing-dossier.yaml` | Memory & Knowledge |
| `turing-frontend-port.yaml` | User/Client |
| `turing-memory-consolidator.yaml` | Memory & Knowledge |
| `turing-notebook-live-vault.yaml` | Memory & Knowledge |
| `turing-obsidian-store.yaml` | Memory & Knowledge |
| `turing-self-talk-loop.yaml` | Agent Layer / Reasoning |
| `turing-skills-lab.yaml` | Agent Layer / Skills |
| `turing-synapse-crud-endpoints.yaml` | Tools & Integrations |
| `turing-wordpress-publishing.yaml` | Tools & Integrations |

### Nested specs (`docs/specs/`, ~70 files)

Structured Markdown spec corpus organised by epic. Top-level meta files:

- `README.md`, `CONVENTIONS.md`, `GLOSSARY.md`, `SEQUENCING.md`,
  `OPEN-QUESTIONS.md`, `EVIDENCE-INDEX.md`, `REMEDIATION_INDEX.md`
- `backlog_security_spec.md`, `container_hardening_spec.md`,
  `vault_client_spec.md`

Epic directories (each contains a `README.md`, `tests-manifest.md`, and
varying numbers of `story-NN-*.md` files; some are stubs):

| Epic | Architecture layer |
|---|---|
| epic-01-eval-substrate (5 stories) | Reliability / Verification |
| epic-02-capability-profile | Agent Layer |
| epic-03-agent-call-acls | Governance / Policy |
| epic-04-substrate-tool-agent-taxonomy | Tools & Integrations / Agent Layer |
| epic-05-agents-as-tools | Agent Layer |
| epic-06-conduit-reasoning-agent | Agent Layer / Reasoning |
| epic-07-dspy-task-signatures | Orchestration / Task Decomposition |
| epic-08-prompt-versioning-rollback | Foundation / Process |
| epic-09-canary-ab-tournament | Reliability |
| epic-10-midsession-model-switching | Foundation / Model Gateway |
| epic-11-group-chat-patterns | Agent Layer / A2A |
| epic-12-memory-v2 (stub) | Memory & Knowledge |
| epic-13-hyperagents-meta-level | Agent Layer / Meta |
| epic-14-artificer-v2-rethink | Agent Layer / Artificer |

`stronghold` mirrors all of the above at the snapshot SHA; treat as
duplicate unless drift is confirmed.

---

## 3. `BlakeMatthews-dev/Project_mAIstro`

No ADRs. Specs are organised under `specs/<area>/S-NNN-*.md` with a global
numbering scheme (`S-001`…`S-159`).

### Meta

- `specs/SPEC-TEMPLATE.md`
- `specs/TIMELINE.md`

### `specs/conductor/` (19) — Orchestration layer

S-001 heartbeat · S-002 factory-spawner · S-003 artifact-intent ·
S-004 conversation-intent · S-005 agent-factory · S-006 apm ·
S-007 3-phase-classifier · S-008 session-summarization ·
S-009 episodic-memory-bridge · S-010 session-isolation ·
S-011 morning-digest · S-012 positive-pattern-learning ·
S-105 uncapped-tool-loop · S-106 user-profiles · S-107 confidence-decay ·
S-138 agent-conductor · S-143 1khz-reactor ·
S-145 hyperagent-graph-runtime · S-158 human-as-node

### `specs/channels/` (5) — User/Client layer

S-041 voice-agent · S-042 voice-model-group · S-043 phone-notifications ·
S-103 email-channel · S-104 alexa-devices

### `specs/infra/` (30) — Foundation / Infrastructure

S-013 systemd-services · S-014 http-webhook ·
S-015 progress-dashboard-api · S-016 dashboard-ui · S-017 dashboard-auth ·
S-018 keycloak-migration · S-019 openwebui-jwt · S-020 searxng ·
S-021 service-integration · S-044 gpu-model-benchmarking ·
S-045 langfuse-setup · S-100 infrastructure-fixes ·
S-101 traefik-dashboard · S-102 pwa-dashboard · S-116 inference-engine ·
S-117 speculative-decoding · S-118 rpc-distributed-inference ·
S-119 bf16-requantization · S-120 obsidian-livesync ·
S-130 cron-hardening · S-132 openresponses-gateway · S-133 pty-supervision ·
S-135 monorepo-consolidation · S-139 setup-wizard · S-140 sqlite-singleton ·
S-144 litellm-freetier · S-147 native-install · S-148 podman-container ·
S-153 tailscale-native · S-159 node-graph-designer

### `specs/intelligence/` (11) — Agent Layer / Memory & Knowledge

S-025 dream-loop · S-026 adversarial-hardening · S-027 tournament-arena ·
S-028 context-archaeology · S-029 temporal-patterns ·
S-030 phantom-execution · S-031 mood-ring · S-032 episodic-memory ·
S-033 memory-evolution · S-114 collective-unconscious ·
S-115 agent-networking

### `specs/security/` (14 + 2 meta) — Governance & Security

`ARCHITECTURE.md`, `PHILOSOPHY.md`,
S-022 bouncer · S-023 secrets-manager · S-024 jwt-auth ·
S-109 secrets-migration · S-131 group-policy-hardening · S-141 vault ·
S-142 privilege-separation · S-149 conductor-seed ·
S-150 hardware-signing · S-151 agent-crypto-ops ·
S-152 agent-identity-did-vc · S-155 internal-trust-root ·
S-156 lightning-federation

### `specs/tools/` (14) — Tools & Integrations

S-034 time-capsule · S-035 skills-subsystem · S-036 message-board ·
S-037 clawhub · S-038 skill-forge · S-039 ultra-think ·
S-040 project-build-agents · S-108 user-feedback · S-110 hooks-system ·
S-111 clawhub-full · S-112 skill-evolution · S-113 stress-rehearsal ·
S-134 browser-cdp-refactor · S-154 electrum-server

---

## Cross-repo mapping to the reference architecture

| Reference layer | maistro-engine | AgentTuring / stronghold | Project_mAIstro |
|---|---|---|---|
| 1. User / Client | — | `turing-chat-streaming`, `turing-frontend-port`, `TURING-CONSOLE-README` | `specs/channels/*` (5) |
| 2. Orchestration / Control Plane | ADR-003, 005-010, 018 | K8S-013–015, K8S-030; `phase1-pipeline-wiring`, `complexity-triage`, `quartermaster-spec-emission`; epic-07 | `specs/conductor/*` (19) |
| 3. Agent Layer | ADR-004, 008 | K8S-022, K8S-027–029, K8S-031; `phase4-agent-configs`, `archie-*`, `rca-*`, `turing-self-talk-loop`, `turing-skills-lab`, `turing-blog-authoring`; epics 02, 05, 06, 11, 13, 14 | `specs/intelligence/*` (11) |
| 4. Tools & Integrations | — | K8S-019–026; `turing-synapse-crud-endpoints`, `turing-wordpress-publishing`; epic-04 | `specs/tools/*` (14) |
| 5. Memory & Knowledge | ADR-011, 013–017 | `turing-dossier`, `turing-memory-consolidator`, `turing-notebook-live-vault`, `turing-obsidian-store`; epic-12 (stub) | `specs/intelligence/{S-032,S-033}`; conductor `S-008,S-009`; tools `S-034` |
| 6. Monitoring & Observability | (gap) | epic-09 (canary/AB); `langfuse-setup` link via S-045 | `specs/infra/{S-015,S-045,S-101,S-102}` |
| 7. Reliability & Failure | (gap) | `phase2-verifier`; epic-01, epic-09 | `specs/intelligence/S-026`; tools `S-113` |
| 8. Governance & Security | — | K8S-002–005, K8S-011, K8S-018, K8S-019; epic-03; `backlog_security_spec`, `container_hardening_spec`, `vault_client_spec` | `specs/security/*` (16) |
| 9. Foundation / Infrastructure | ADR-001, 002, 012, 019 | K8S-001, K8S-006–010, K8S-012, K8S-016, K8S-017; `phase3-plan-caching`, `prompt-caching`; epic-08, epic-10 | `specs/infra/*` (30) |

## Observed gaps and overlaps

- **Monitoring & Observability (layer 6)** is the thinnest layer overall.
  Project_mAIstro covers it at the infra/UI level (S-015, S-101, S-102,
  S-045/Langfuse). AgentTuring covers it indirectly through epic-09.
  `maistro-engine` has no ADR scoped to tracing/metrics/alerting.
- **Reliability (layer 7)** has substantive coverage in AgentTuring
  (`phase2-verifier`, epic-01, epic-09) but no engine-level ADR in
  `maistro-engine`.
- **Memory** is owned by `maistro-engine` ADRs (011–017) but also re-stated
  by AgentTuring's Turing-* memory specs and Project_mAIstro's
  intelligence specs — three teams describing overlapping memory subsystems
  is a likely source of drift.
- **Agent catalogs** appear in three forms: AgentTuring's K8S-027 catalog,
  Project_mAIstro's conductor `S-005`/`S-138`, and `maistro-engine`'s
  ADR-009 spawner. Confirm canonical owner per ADR-019
  (canonical-source-split).
- **AgentTuring ↔ stronghold** are blob-identical at this snapshot; pick a
  single source of truth or document the divergence policy.
- **Project_mAIstro has no ADRs.** Many of its specs (S-138 conductor,
  S-145 hyperagent-graph, S-155 trust-root) describe decisions large enough
  that a corresponding ADR would be appropriate.

## Methodology

- Listings produced via the GitHub MCP API against each repo's default
  branch HEAD (snapshot 2026-05-07).
- Epic story counts under `docs/specs/epic-*` are not exhaustively
  enumerated; epic-01 (5 stories) and epic-12 (stub) were sampled to
  characterise the structure.
- Layer mapping is judgement-based against the agentic-AI reference
  architecture (User → Orchestration → Agents → Tools → Memory →
  Monitoring → Reliability → Governance → Foundation). Edge cases are
  attributed to the layer that owns the dominant decision.
