# Project mAIstro — Backlog

> **Deprecated** — this file is no longer the source of truth.
> Active sprint and planned features live in [`specs/`](specs/) and the master timeline is [`specs/TIMELINE.md`](specs/TIMELINE.md).
> This file is kept for historical reference; do not update it.

**Last Updated:** 2026-03-23

## Priority Legend

- **P0**: Blocking — must fix before stack is usable
- **P1**: High — needed for core functionality
- **P2**: Medium — improves quality/speed
- **P3**: Low — nice to have / research

---

## Active Sprint

| #   | Priority | Task                                              | Status      | Notes                                                                                                                                                                   |
| --- | -------- | ------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 17  | P1       | Fix infrastructure issues                         | IN PROGRESS | Root disk 65% (improved), SnapRAID 77% unscrubbed, docker.bak still present                                                                                             |
| 24  | P2       | Alexa Media Player / Alexa Devices setup          | BLOCKED     | Amazon auth flow failing — phone verification issue. Try "Alexa Devices" core integration (Amazon OAuth) instead of HACS Alexa Media Player. Manual step through HA UI. |
| 25  | P2       | Email channel — conductor@emeraldfam.org          | PLANNED     | Cloudflare Email Routing → conductor. Inbound: sender allowlist. Outbound: digests, alerts. ~300 lines                                                                  |
| 26  | P3       | Uncapped tool loop for heartbeat tasks            | PLANNED     | Heartbeat tasks currently share the 3-round cap. Change to 50 rounds + token budget for autonomous tasks. ~30 lines                                                     |
| 27  | P3       | User profile extraction from conversations        | PLANNED     | Auto-learn timezone, preferences, communication style per user. Long-term memory 9→10. ~200 lines                                                                       |
| 28  | P3       | Confidence decay on learnings                     | PLANNED     | Unused learnings fade over 30 days. ~50 lines                                                                                                                           |
| 29  | P2       | Skill Evolution — natural selection for tools     | PLANNED     | Forged skills compete on usage/success rate, weak ones pruned. ~300 lines                                                                                               |
| 30  | P3       | PWA dashboard — mobile-installable                | PLANNED     | Service worker + manifest.json + web push. ~200 lines                                                                                                                   |
| 31  | P2       | User feedback on responses — thumbs up/down       | PLANNED     | Like digest ratings but for any chat response. ~150 lines                                                                                                               |
| 32  | P3       | Agent-to-agent networking                         | PLANNED     | From CONDUCTOR-ROADMAP.md. ~500 lines                                                                                                                                   |
| 33  | P3       | Collective Unconscious — federated wisdom sharing | PLANNED     | Cross-tenant T7 wisdom tier. ~400 lines                                                                                                                                 |

## Backlog

| #   | Priority | Task                                                   | Status       | Notes                                                                                                            |
| --- | -------- | ------------------------------------------------------ | ------------ | ---------------------------------------------------------------------------------------------------------------- |
| 10  | P1       | Better inference engine than Ollama                    | RESEARCH     | Options: mainline llama.cpp (supports qwen35moe), vLLM, ExLlamaV2. Goal: faster tok/s, more control              |
| 11  | P2       | Add qwen35moe support to ik_llama.cpp                  | BACKBURNERED | Port from mainline PR #19468 (17 files). Gated Delta Networks architecture                                       |
| 12  | P2       | Qwen3.5-35B-A3B optimization                           | BACKBURNERED | 35B/3B active, 256 experts, fits in P40 at 19GB. Model downloaded at `/vmpool/conductor-models/qwen3.5-35B-A3B/` |
| 13  | P2       | Speculative decoding with MTP                          | RESEARCH     | Multi-Token Prediction for speed boost                                                                           |
| 14  | P2       | RPC distributed inference (P40 + 3070 Ti)              | RESEARCH     | Split model across both GPUs via network                                                                         |
| 15  | P2       | Download BF16 source weights for proper requantization | PENDING      | Better quality quants from full-precision source                                                                 |
| 16  | P3       | Full expert profiling benchmark post-reboot            | PENDING      | Run speed_test.sh matrix with working GPU                                                                        |
| 18  | P2       | ~~SearXNG deployment~~                                 | DONE         | LXC 104 at 10.10.21.104:8888 — fully functional                                                                  |
| 19  | P3       | CouchDB/Obsidian LiveSync                              | PENDING      | Multi-device vault sync                                                                                          |
| 20  | P2       | WordPress posts as task input source                   | PENDING      | Create tasks for conductor/router via WordPress posts alongside Obsidian vault                                   |
| 21  | P2       | Move fast data to ZFS NVMe mirror                      | PENDING      | DBs, caches, configs → /vmpool/; models, media → /mnt/storage/                                                   |

## Completed

| #     | Task                                                                                      | Date       |
| ----- | ----------------------------------------------------------------------------------------- | ---------- |
| C28   | Voice agent — Alexa → HA Assist → Conductor (custom_components/conductor_agent)           | 2026-03-23 |
| C27   | Voice model group — fast routing, 2-4s responses                                          | 2026-03-23 |
| C26   | Phone notifications — ha_notify tool (Blake/Bella/Lilly/all)                              | 2026-03-23 |
| C25   | JWT auth — Keycloak RS256 validation + role-based tool access                             | 2026-03-23 |
| C24   | Per-user session isolation — session_id scoped by user_id                                 | 2026-03-23 |
| C23   | Episodic memory bridge — auto-promoted learnings → PG T4 LESSON                           | 2026-03-23 |
| C22   | Dashboard auth — conductor-dash behind Keycloak oauth2-proxy                              | 2026-03-23 |
| C21   | 3-phase classifier — keywords + negative signals + LLM fallback                           | 2026-03-23 |
| C20   | Morning digest — personalized briefings with 👍/👎 topic ratings (Blake 5:45, Lilly 7:20) | 2026-03-23 |
| C19   | Skill Forge — agent creates its own SKILL.md tools on demand                              | 2026-03-23 |
| C18   | ClawHub — community skill marketplace (search, install, uninstall, security scan)         | 2026-03-23 |
| C17   | OpenWebUI JWT passthrough — ENABLE_FORWARD_USER_INFO_HEADERS + X-OpenWebUI-\* header auth | 2026-03-23 |
| C16   | Positive pattern learning — learn from first-try successes, not just failures             | 2026-03-23 |
| C15.1 | Session summarization — expired sessions → episodic memories via LLM                      | 2026-03-23 |
| C15   | Keycloak OIDC migration — all 42 proxies + 6 native OIDC services                         | 2026-03-23 |
| C1    | Build moe_profiler.py tool                                                                | 2026-02-25 |
| C2    | Benchmark Coder-Next with cpu-moe (25 tok/s ceiling)                                      | 2026-02-25 |
| C3    | Download Qwen3.5-35B-A3B GGUF (19GB)                                                      | 2026-02-25 |
| C4    | GPU recovery after Xid 79                                                                 | 2026-02-25 |
| C5    | Thermal circuit breaker in profiler                                                       | 2026-02-25 |
| C6    | Benchmark Q3_K_M requant quality                                                          | 2026-02-24 |
| C7    | Benchmark UD-Q3_K_XL and IQ3_M quants                                                     | 2026-02-24 |
| C8    | Implement threshold-based adaptive routing                                                | 2026-02-24 |
| C9    | Conductor stack running end-to-end                                                        | 2026-02-25 |
| C10   | All services communicating (OpenWebUI→LiteLLM, Router→Cloud, Langfuse tracing)            | 2026-02-25 |
| C11   | Wiki updated: 7-page Conductor Stack Architecture section                                 | 2026-02-25 |
| C12   | WordPress admin login created                                                             | 2026-02-25 |
| C13   | WordPress conductor editor account created                                                | 2026-02-25 |
| C14   | Langfuse prompts synced (coder, planner, reviewer)                                        | 2026-02-25 |
| C15   | HA located at 10.10.42.174, conductor config updated                                      | 2026-02-25 |
| C16   | Official backlog created                                                                  | 2026-02-25 |
