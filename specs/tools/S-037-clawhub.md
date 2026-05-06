---
id: S-037
title: "Medley — community plugin marketplace (search, install, uninstall, security scan)"
domain: tools
status: done
priority: P2
effort: ""
created: 2026-03-23
completed: 2026-03-23
owner: conductor
commits: []
---

# S-037: Medley

Community plugin marketplace. Plugins can be skills, channels, agents, or whole subgraphs. Search by tag/keyword, install to `~/.conductor/medley/`, security scan via gitleaks + Bouncer (S-022) + Phantom Execution (S-030) before trust promotion. Per-plugin signing via publisher VCs lands in S-111.

## Plugin types

| Type | What it is | Lifecycle gates |
|---|---|---|
| **skill** | Single executable capability (a `SKILL.md` + binary) | Phantom + trust tiers (S-030, S-035) |
| **channel** | Input/output adapter (Telegram, Gmail, etc.) | Same gates as skills + channel allowlist enforcement |
| **agent** | Importable agent node (Claude SDK agent, LangGraph chain, etc.) | Wrapped in `AgentSpec` envelope (S-002) |
| **graph** | Multi-agent subgraph (e.g. `builders-graph` = Scout + Architect + Extractor + Validator from S-040) | Each contained agent runs under its own AgentSpec |

Folding agent / graph / channel into Medley collapses what would otherwise be separate distribution channels into a single plugin format. The runtime knows how to load each type.

## CLI surface

```
medley install <name>...        # one or many: medley install ha-ai telegram gmail builders-graph
medley search <query>
medley list                     # what's installed
medley info <name>              # type, version, capabilities, trust tier, publisher
medley remove <name>
medley publish <path>           # see S-111 for full publish flow
medley update [<name>...]       # all if no name given
medley trust <name>             # promote tier (admin-only, signed by S-149 keypair)
```

`medley` is its own binary, sibling to `maistro`. Avoids `maistro medley install ...` repetition.

## Key files
- `~/.conductor/medley/` (install root)
- `medley` binary (CLI + library)
- Per-plugin `manifest.toml` declaring type, version, dependencies, publisher DID
