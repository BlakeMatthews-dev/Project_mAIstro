# Project Maistro

**Your AI assistant, everywhere you already are.**

A self-hosted, multi-channel AI gateway that connects large language models to 40+ messaging platforms — Slack, Discord, Telegram, WhatsApp, Signal, Matrix, Teams, and more. One brain, every conversation.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)
[![Node.js](https://img.shields.io/badge/Node.js-%3E%3D22-339933?style=for-the-badge&logo=node.js&logoColor=white)](https://nodejs.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](Dockerfile)

---

## What Is Maistro?

Maistro is an AI orchestration platform — not just a chatbot wrapper. It runs a **multi-agent conductor ensemble** (Planner, Coder, Reviewer, Scout) with an **Ultra Think** parallel generation pipeline that produces higher-quality outputs through iterative refinement. Connect any supported LLM provider, deliver through any messaging channel, keep everything on your own infrastructure.

### Key Capabilities

|                   | Feature                    | Details                                                                                                                              |
| ----------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Channels**      | 40+ messaging integrations | Slack, Discord, Telegram, WhatsApp, Signal, Matrix, Teams, IRC, iMessage, Google Chat, Line, Mattermost, Nostr, SMS, email, and more |
| **LLM Providers** | 9+ providers               | Anthropic Claude, Google Gemini, Ollama (local), OpenRouter, GitHub Copilot, Qwen, Minimax, OpenAI, and custom endpoints             |
| **Skills**        | 54 built-in skills         | GitHub, Trello, Notion, Spotify, weather, camera, file management, coding agents, and more                                           |
| **Compatibility** | Claude Code & OpenClaw     | Skills and plugins work across Maistro, Claude Code, and OpenClaw — drop-in compatible                                               |
| **Browser**       | Playwright automation      | Full browser control with Chrome extension relay for DevTools Protocol                                                               |
| **Voice**         | Multi-provider TTS/STT     | ElevenLabs, Google, OpenAI, Azure, and local Sherpa ONNX                                                                             |
| **Memory**        | Persistent context         | Vector embeddings, semantic search, knowledge graph, temporal decay                                                                  |
| **Security**      | Hardened by default        | Sandbox env sanitization, trust boundaries, CSPRNG tokens, IDN homoglyph protection                                                  |

---

## Architecture

```
                          ┌─────────────────────────────────────────┐
                          │            Gateway (WS :18789)          │
                          │  Auth · Rate Limiting · Session Mgmt   │
                          └──────┬──────────────┬──────────────┬───┘
                                 │              │              │
                    ┌────────────┘     ┌────────┘     ┌────────┘
                    ▼                  ▼              ▼
             ┌─────────────┐   ┌────────────┐  ┌───────────┐
             │  Conductor   │   │  Channels  │  │   Tools   │
             │  Ensemble    │   │  (40+)     │  │           │
             └──┬──┬──┬──┬─┘   └────────────┘  └───────────┘
                │  │  │  │
         ┌──────┘  │  │  └──────┐
         ▼         ▼  ▼         ▼
     Planner   Coder  Reviewer  Scout
```

**Conductor Ensemble** — Multi-agent system with 4 compute tiers:

- **Tier 1**: Single generation, low temperature — fast answers
- **Tier 2**: 3 parallel generations with review — balanced quality
- **Tier 3**: 5 generations + testing + review with thinking mode — high reliability
- **Tier 4**: 10 generations + full test suite + convergence analysis — maximum quality

**5-Layer Memory Stack**:

1. **Constraints** — Style, architecture, and security rules
2. **Working Memory** — Active conversation history
3. **Compressed** — Summarized older turns
4. **Changelog** — Task history with success metrics
5. **Knowledge Graph** — Module and function dependency map

---

## Quick Start

### Docker (recommended)

```bash
# Clone and start
git clone https://github.com/TheAIGuyFromAR/Project_mAIstro.git
cd Project_mAIstro
cp .env.example .env
# Edit .env with your API keys and gateway token

docker compose up -d
```

### Local Development

```bash
# Requirements: Node.js >= 22, pnpm
npm install
node maistro.mjs gateway
```

### Environment Setup

```bash
# Required: at least one LLM provider
ANTHROPIC_API_KEY=sk-ant-...        # Anthropic Claude
GEMINI_API_KEY=...                   # Google Gemini
OPENROUTER_API_KEY=...               # OpenRouter (multi-model)
OLLAMA_HOST=http://localhost:11434   # Ollama (local models)

# Required: gateway authentication
MAISTRO_GATEWAY_TOKEN=<64+ hex chars>

# Optional: channel tokens (enable as needed)
TELEGRAM_BOT_TOKEN=...
DISCORD_BOT_TOKEN=...
SLACK_BOT_TOKEN=...
SLACK_APP_TOKEN=...
```

---

## Supported Channels

| Category             | Channels                                                    |
| -------------------- | ----------------------------------------------------------- |
| **Chat Platforms**   | Slack, Discord, Telegram, WhatsApp, Google Chat, Mattermost |
| **Secure Messaging** | Signal, Matrix, iMessage (via BlueBubbles)                  |
| **Enterprise**       | Microsoft Teams, Nextcloud Talk                             |
| **Protocol**         | IRC, Nostr, WebChat                                         |
| **Asian Markets**    | LINE, Zalo, Feishu/Lark                                     |
| **Voice/SMS**        | Twilio, ElevenLabs, Sherpa ONNX                             |
| **Apple**            | iMessage, BlueBubbles                                       |

Each channel is a plugin with a standardized adapter interface — config, security, outbound delivery, threading, streaming, and more.

---

## Claude Code & OpenClaw Compatibility

Maistro is **drop-in compatible** with both Claude Code and OpenClaw ecosystems:

### Skills

Skills use the same `SKILL.md` format with YAML frontmatter. Place them in any of these directories:

```
~/.agents/skills/              # Personal skills (shared with Claude Code)
<workspace>/.agents/skills/    # Project-specific skills
<workspace>/skills/            # Workspace skills
~/.config/maistro/skills/      # Managed/installed skills
```

A skill is a Markdown file that defines a slash command:

```markdown
---
name: my-skill
description: "Does something useful"
metadata: { "maistro": { "emoji": "🔧", "requires": { "bins": ["jq"] } } }
---

Your skill prompt goes here. The agent receives this as instructions
when the user invokes /my-skill.
```

### Plugins

Plugins use `maistro.plugin.json` manifests (with `openclaw.plugin.json` fallback):

```json
{
  "id": "my-channel",
  "name": "My Channel",
  "channels": ["my-channel"],
  "configSchema": { "type": "object", "properties": {} }
}
```

### Tool Compatibility

Models trained on Claude Code work natively — Maistro automatically translates parameter conventions (`file_path` ↔ `path`, `old_string` ↔ `oldText`, `new_string` ↔ `newText`).

---

## Configuration

Maistro uses a JSON config file at `~/.maistro/maistro.json` with environment variable overrides:

```bash
# Config precedence (highest → lowest):
# 1. Process environment variables
# 2. ./.env (local)
# 3. ~/.maistro/.env (user home)
# 4. maistro.json env block
# 5. Config file direct keys
```

All environment variables use the `MAISTRO_` prefix:

| Variable                     | Purpose                                        |
| ---------------------------- | ---------------------------------------------- |
| `MAISTRO_GATEWAY_TOKEN`      | WebSocket auth token (64+ hex chars)           |
| `MAISTRO_GATEWAY_PASSWORD`   | Alternative password auth                      |
| `MAISTRO_STATE_DIR`          | Config/session storage (default: `~/.maistro`) |
| `MAISTRO_CONFIG_PATH`        | Config file path                               |
| `MAISTRO_BUNDLED_SKILLS_DIR` | Override bundled skills location               |

---

## CLI Commands

```bash
maistro gateway                     # Start the gateway server
maistro agent --message "prompt"    # Run agent in CLI mode
maistro channels status             # Check channel health
maistro models list                 # Show available models
maistro onboard                     # Interactive setup wizard
maistro doctor                      # Diagnose configuration issues
maistro sessions list               # List active sessions
maistro message send --to @user     # Send a direct message
```

---

## Security

Maistro is security-hardened with multiple layers of protection:

- **Sandbox Environment Sanitization** — 50+ sensitive env var patterns blocked from Docker sandboxes (API keys, tokens, passwords, AWS/SSH/GPG credentials). Configurable allowlist for explicit overrides.

- **Trust Boundaries** — Per-agent permission grants with glob-based path access control. Dangerous commands (`rm -rf`, `sudo`, `chmod 777`, `curl | sh`, `eval`) are detected and blocked.

- **CSPRNG Token Generation** — All security-sensitive IDs use `crypto.randomBytes()` instead of `Math.random()`. Shared utility at `src/utils/secure-random.ts`.

- **IDN Homoglyph Protection** — Origin checking normalizes international domain names via `domainToASCII()` to prevent Cyrillic/mixed-script lookalike attacks.

- **DM Pairing** — Unknown senders must complete a pairing code flow before accessing the assistant.

- **Rate Limiting** — Per-gateway, per-channel, and per-peer rate limits with configurable thresholds.

---

## LLM Providers

| Provider           | Auth                 | Notes                                |
| ------------------ | -------------------- | ------------------------------------ |
| **Anthropic**      | `ANTHROPIC_API_KEY`  | Claude models, thinking mode support |
| **Google Gemini**  | `GEMINI_API_KEY`     | Gemini models                        |
| **Ollama**         | `OLLAMA_HOST`        | Local models, no API key needed      |
| **OpenRouter**     | `OPENROUTER_API_KEY` | Multi-provider gateway               |
| **GitHub Copilot** | OAuth                | Via Copilot proxy extension          |
| **Qwen**           | `QWEN_API_KEY`       | Via portal auth extension            |
| **Minimax**        | `MINIMAX_API_KEY`    | Via portal auth extension            |
| **OpenAI**         | `OPENAI_API_KEY`     | OpenAI-compatible endpoints          |
| **Custom**         | Configurable         | Any OpenAI-compatible API            |

Model fallback chains are configurable — if a primary provider is rate-limited or errors, Maistro automatically falls back to the next provider in the chain.

---

## Built-in Skills (54)

<details>
<summary>Click to expand full skill list</summary>

| Skill                | Description                                   |
| -------------------- | --------------------------------------------- |
| `github`             | GitHub CLI integration (issues, PRs, actions) |
| `gh-issues`          | GitHub issue management                       |
| `trello`             | Trello board management                       |
| `notion`             | Notion page and database access               |
| `slack`              | Slack workspace tools                         |
| `discord`            | Discord server management                     |
| `spotify-player`     | Spotify playback control                      |
| `weather`            | Weather forecasts                             |
| `camsnap`            | Camera snapshot capture                       |
| `coding-agent`       | Autonomous coding sub-agent                   |
| `summarize`          | Content summarization                         |
| `tmux`               | Terminal multiplexer control                  |
| `obsidian`           | Obsidian vault access                         |
| `bear-notes`         | Bear notes integration                        |
| `apple-notes`        | Apple Notes access                            |
| `apple-reminders`    | Apple Reminders sync                          |
| `1password`          | 1Password secret lookup                       |
| `openai-whisper`     | Local speech transcription                    |
| `openai-whisper-api` | Cloud speech transcription                    |
| `openai-image-gen`   | Image generation                              |
| `voice-call`         | Voice call handling                           |
| `session-logs`       | Session log viewer                            |
| `model-usage`        | Token usage tracking                          |
| `gemini`             | Gemini-specific tools                         |
| `oracle`             | Knowledge base queries                        |
| `blogwatcher`        | Blog/RSS monitoring                           |
| `food-order`         | Food ordering assistant                       |
| `goplaces`           | Location/places search                        |
| `himalaya`           | Email client (himalaya)                       |
| `imsg`               | iMessage tools                                |
| `bluebubbles`        | BlueBubbles iMessage bridge                   |
| `sonoscli`           | Sonos speaker control                         |
| `openhue`            | Philips Hue lighting                          |
| `things-mac`         | Things 3 task manager                         |
| `gifgrep`            | GIF search                                    |
| `songsee`            | Song identification                           |
| `ordercli`           | Order tracking                                |
| `sag`                | Search and grep utility                       |
| `gog`                | Git operations                                |
| `wacli`              | WhatsApp CLI tools                            |
| `mcporter`           | Minecraft server tools                        |
| `video-frames`       | Video frame extraction                        |
| `clawhub`            | Extension marketplace                         |
| `blucli`             | Bluetooth CLI tools                           |
| `eightctl`           | 8sleep bed control                            |
| `sherpa-onnx-tts`    | Local TTS (Sherpa ONNX)                       |
| `nano-banana-pro`    | Nano device control                           |
| `nano-pdf`           | PDF processing                                |

</details>

---

## Docker Deployment

The included `Dockerfile` builds a security-hardened container:

- Non-root user execution
- Read-only filesystem
- Dropped Linux capabilities
- Multi-stage build for minimal image size

```yaml
# docker-compose.yml (simplified)
services:
  maistro-gateway:
    build: .
    ports:
      - "18789:18789"
    env_file: .env
    volumes:
      - maistro-data:/home/maistro/.maistro
    restart: unless-stopped
```

---

## Project Structure

```
├── maistro.mjs                  # CLI entry point
├── src/
│   ├── gateway/                 # WebSocket gateway server
│   ├── conductor/               # Multi-agent orchestration
│   │   ├── ensemble/            # Ultra Think pipeline
│   │   ├── memory/              # 5-layer memory stack
│   │   └── security/            # Trust boundaries
│   ├── agents/                  # Agent runtime & tools
│   │   ├── skills/              # Skill loading system
│   │   └── sandbox/             # Docker sandbox management
│   ├── channels/                # Channel plugin framework
│   ├── auto-reply/              # Message routing & delivery
│   ├── plugin-sdk/              # Public plugin SDK
│   ├── config/                  # Zod-validated configuration
│   ├── hooks/                   # Lifecycle hook system
│   └── utils/                   # Shared utilities
├── extensions/                  # 41 channel & provider plugins
├── skills/                      # 54 bundled skills
├── packages/
│   ├── clawdbot/                # Legacy compat shim
│   └── moltbot/                 # Legacy compat shim
├── Dockerfile
├── docker-compose.yml
└── fly.toml                     # Fly.io deployment config
```

---

## Hook System

Hooks let you run shell commands in response to lifecycle events:

```json
{
  "hooks": {
    "message.inbound": "logger --tag maistro 'Inbound: $MESSAGE'",
    "session.created": "notify-send 'New session started'",
    "agent.beforeToolCall": "echo $TOOL_NAME >> /tmp/tool-log.txt"
  }
}
```

Available events: `message.inbound`, `message.outbound`, `session.created`, `session.ended`, `agent.beforeToolCall`, `agent.afterToolCall`, `cron.execute`.

---

## Testing

```bash
npm test                  # Full test suite (vitest)
npm run test:fast         # Unit tests only
npm run test:coverage     # Coverage report (70% threshold)
npm run test:live         # Live provider tests (requires API keys)
```

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure `npm test` passes
5. Submit a pull request

---

## License

[MIT](LICENSE)
