---
id: S-026
title: "Adversarial Self-Hardening — Red Team / Blue Team"
domain: intelligence
status: done
priority: P2
effort: ""
created: 2026-02-25
completed: 2026-03-23
owner: conductor
commits: [259bf0b]
---

# S-026: Adversarial Self-Hardening

Red agent generates attack prompts against conductor. Blue agent defends and updates the bouncer's pattern library. Findings logged to dashboard Security tab.

## Key files
- `conductor/orchestrator/agents/experimental/red_team.py`
