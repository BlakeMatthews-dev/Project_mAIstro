# Conductor Roadmap

**Last updated:** 2026-03-23

## Built and Running

| #   | Feature                                                   | Status                       |
| --- | --------------------------------------------------------- | ---------------------------- |
| 1   | Heartbeat wired into conductor main loop                  | DONE                         |
| 2   | Systemd services (gateway + conductor)                    | DONE                         |
| 3   | Factory wired into Spawner (variant selector, recipes)    | DONE                         |
| 5   | ARTIFACT intent handler                                   | DONE                         |
| 9   | HTTP webhook delivery                                     | DONE                         |
| 13  | Dream Loop — idle-time memory consolidation               | DONE                         |
| 14  | Adversarial Self-Hardening (Red Team / Blue Team)         | DONE                         |
| 15  | Model Tournament Arena — private leaderboard              | DONE (needs reviewer wiring) |
| 18  | Context Archaeology — forensic failure autopsy            | DONE                         |
| 19  | Temporal Pattern Recognition                              | DONE                         |
| 21  | Phantom Execution — shadow-run skills                     | DONE                         |
| 23  | Mood Ring — adaptive behavior from system health          | DONE                         |
| 24  | Time Capsule — scheduled self-reminders                   | DONE                         |
| —   | Agent Factory (recipes, Thompson sampling, typed outputs) | DONE                         |
| —   | Bouncer (security screening, 20+ regex + LLM)             | DONE                         |
| —   | Skills subsystem (scanner, loader, trust tiers, gitleaks) | DONE                         |
| —   | Secrets Manager (Vaultwarden integration)                 | DONE                         |
| —   | APM (7-section personality template)                      | DONE                         |
| —   | 7-tier episodic memory (PG + pg_trgm)                     | DONE                         |
| —   | Message board (agent → human)                             | DONE                         |
| —   | Memory evolution history (git-tracked)                    | DONE                         |
| —   | Progress tracking + dashboard API                         | DONE                         |
| —   | Dashboard UI (command center)                             | DONE                         |
| —   | CONVERSATION intent handler                               | DONE                         |

## Remaining

| #   | Feature                                                 | Effort     | Priority        |
| --- | ------------------------------------------------------- | ---------- | --------------- |
| 4   | Secrets → Vaultwarden migration                         | 2 hours    | HIGH (security) |
| 7   | Traefik route for dashboard (proper HTTPS)              | 15 min     | MEDIUM          |
| 8   | General hooks system (event-driven shell commands)      | ~250 lines | MEDIUM          |
| 6   | ClawHub package manager (install/search)                | ~200 lines | MEDIUM          |
| 10  | ClawHub full (publish, versions, dependency resolution) | ~300 lines | LOW             |
| 11  | Agent-to-agent networking                               | ~500 lines | LOW             |
| 12  | Skill Forge — agent writes its own skills               | ~300 lines | HIGH (cool)     |
| 16  | Stress Rehearsal — controlled chaos testing             | ~250 lines | MEDIUM          |
| 17  | Skill Evolution — natural selection for tools           | ~300 lines | MEDIUM          |
| 22  | Collective Unconscious — federated wisdom sharing       | ~400 lines | LOW             |
