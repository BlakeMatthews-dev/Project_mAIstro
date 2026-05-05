---
id: S-111
title: "ClawHub full — publish, versions, dependency resolution"
domain: tools
status: draft
priority: P2
effort: "~300 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
supersedes: "S-037 (extends basic ClawHub)"
---

# S-111: ClawHub full

## Problem
S-037 (basic ClawHub) supports search/install/uninstall. No skill publishing, versioning, or dependency resolution.

## Solution
Add: `clawhub publish` (sign + upload), semantic version pinning, `depends_on` in SKILL.md resolved at install time.

## Acceptance Criteria
- [ ] `clawhub publish` uploads a skill with version tag
- [ ] Installed skills pin to a semver range
- [ ] `depends_on` skills auto-installed transitively
- [ ] Version conflicts reported clearly
