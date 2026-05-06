---
id: S-135
title: "Monorepo consolidation — absorb maistro-engine into project_maistro"
domain: infra
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
---

# S-135: Monorepo consolidation

## Problem

Two repositories share one architecture: `project_maistro` hosts the orchestrator (TypeScript `src/` + Python `conductor/` + dashboard + skills + Swift app), while `maistro-engine` hosts the Python inference / LiteLLM service that the orchestrator calls into. Cross-repo coupling means:

- Specs and roadmap are fragmented (specs live here, but reference engine paths)
- Coordinated changes require two PRs and version pinning
- CI cannot run integration tests against both sides in one job
- Onboarding requires cloning two repos and reading two READMEs

## Solution

Absorb `maistro-engine` into `project_maistro` under `apps/engine/`, **preserving git history via `git subtree`**. Reorganize `project_maistro` into monorepo shape:

```
project_maistro/
  apps/
    orchestrator/     # current conductor/ + TS src/ moved here
    engine/           # absorbed from maistro-engine (history preserved)
    dashboard/        # current ui/ or apps/* dashboard
  packages/           # shared types, schemas
  specs/              # single source of truth (already in place)
  scripts/
  pnpm-workspace.yaml # extended workspaces (TS); uv/Poetry handles Python under apps/engine
```

After absorption, `maistro-engine` repo is archived (read-only) with a redirect notice in its README.

## Acceptance Criteria

- [ ] `apps/engine/` exists in `project_maistro` with full git history from `maistro-engine`
- [ ] CI runs both TS (vitest) and Python (pytest, alembic) suites in one workflow
- [ ] Root `docker-compose.yml` brings up engine + orchestrator together
- [ ] Old import paths in `maistro-engine` consumers updated
- [ ] `specs/`, `AGENTS.md`, `README.md` updated to reflect monorepo layout
- [ ] `maistro-engine` repo archived on GitHub with README pointing to new location

## Implementation Notes

History-preserving merge command (run **locally**, not via API):

```bash
cd project_maistro
git checkout -b chore/absorb-engine
git remote add engine https://github.com/BlakeMatthews-dev/maistro-engine.git
git fetch engine
git subtree add --prefix=apps/engine engine main
```

Follow-up commits (each independently reviewable):

1. Move existing top-level dirs (`conductor/`, top-level `src/` if applicable) into `apps/orchestrator/`.
2. Update CI workflows, Dockerfiles, and `docker-compose.yml` to the new paths.
3. Update `AGENTS.md`, `README.md`, and `specs/TIMELINE.md` to reference monorepo layout.

The `maistro-engine` branch `claude/setup-maistro-refactor-c6xwX` is left as a bare pointer; no work lands there. After consolidation, it can be deleted along with the rest of the repo (archive first).

## Open questions

- Python toolchain in monorepo: `uv` vs Poetry? `maistro-engine` uses `pyproject.toml`; `project_maistro` is npm/pnpm.
- Deploy: does engine still ship as its own container, or fold into the orchestrator's compose?
- Versioning: per-app semver tags vs unified release?

## Verification

- `git log apps/engine/` shows pre-merge commits originally from `maistro-engine`
- Workspace-level test runner exercises both sides
- `docker-compose up` brings up engine + orchestrator + ancillary services from a single clone
- A delete-and-reclone of `project_maistro` is sufficient to develop both halves
