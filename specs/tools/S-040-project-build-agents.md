---
id: S-040
title: "Project build agents — Scout, Architect, Extractor, Validator"
domain: tools
status: done
priority: P1
effort: ""
created: 2026-03-23
completed: 2026-03-23
owner: conductor
commits: [4852a8f]
---

# S-040: Project build agents

Four-role build pipeline: Scout (inventory), Architect (design), Extractor (copy+sanitize files), Validator (docker build + import check + pytest). Wired with Ultra Think + Reviewer loop.

## Key files
- `conductor/orchestrator/agents/recipes/scout_analyze.yaml`
- `conductor/orchestrator/agents/recipes/architect_design.yaml`
- `conductor/orchestrator/agents/recipes/extractor_transform.yaml`
- `conductor/orchestrator/agents/recipes/validator_check.yaml`
