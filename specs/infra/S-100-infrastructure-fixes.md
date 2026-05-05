---
id: S-100
title: "Infrastructure fixes — disk space + SnapRAID unscrubbed"
domain: infra
status: in_progress
priority: P1
effort: ""
created: 2026-03-23
completed: ""
owner: conductor
commits: []
---

# S-100: Infrastructure fixes

## Problem
Root disk at 65% capacity. SnapRAID 77% unscrubbed (data integrity risk). Stale `docker.bak` directory still present.

## Solution
- Clear docker.bak and other reclaimed space
- Run SnapRAID scrub to completion
- Set up automated scrub schedule

## Acceptance Criteria
- [ ] Root disk < 50%
- [ ] SnapRAID scrub completes (0% unscrubbed)
- [ ] docker.bak removed
- [ ] Automated weekly scrub cron installed
