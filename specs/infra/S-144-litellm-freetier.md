---
id: S-144
title: "LiteLLM free-tier auto-configuration — OAuth-first onboarding for the LLM hook"
domain: infra
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-144: LiteLLM Free-Tier Auto-Configuration

## Problem

The value proposition of Agent Conductor for new operators is *"try free routing across multiple providers — stay for the security architecture."* That hook only works if onboarding LLM access is genuinely friction-free. Today, every personal-AI-agent project asks the user to:

1. Sign up at provider X.
2. Generate an API key.
3. Copy the key.
4. Paste it into a config file.
5. Repeat for providers Y and Z if you want fallback.

For the household audience, that's five steps too many before they see the agent respond. For the crypto-native / sovereignty audience, key-handling friction *is* the value (they want to manage their own keys), so the system also has to support BYO-key cleanly.

## Solution

The Console's LLM-config step (part of S-139) auto-configures **LiteLLM routing** with **OAuth-first sign-in to multiple free-tier providers**. Where OAuth is supported, the operator clicks "Sign in with Provider" and the API key flows directly into the vault (S-141). Where OAuth isn't supported, fallback to paste-API-key with explicit per-provider instructions.

### Default providers (OAuth-preferred)

Four providers configured by default. Operator can deselect any of them or add others later via Medley.

| Provider | Auth method | Models routed | Free-tier scope (approximate, subject to provider) |
|---|---|---|---|
| **Groq** | OAuth (sign in with Groq account) | Llama 3.3 70B, Llama 3.1 8B, Mixtral 8x22B, plus Groq-deployed models | ~30 req/min, ~14K tokens/day for free; rate-limit aware |
| **Cerebras** | API key (paste) — OAuth pending provider support | Llama 3.3 70B (Cerebras-fast), Llama 3.1 8B, Qwen-32B | ~tok/s leadership, daily token cap |
| **Cloudflare Workers AI** | API key paste, with one-click "create token" deep-link to Cloudflare dashboard scoped to Workers AI | Llama 3.1 8B, Mistral 7B, Qwen variants, embeddings | Free tier with daily request cap; CF account required |
| **OpenRouter** | OAuth (sign in with OpenRouter) | Aggregates 100+ providers; many free tiers across models | Per-model free credits; rotates over time |

All four are configured into LiteLLM as **fallback siblings**. The router prefers free-tier providers in cost-per-token order; falls back to whichever has remaining quota; degrades gracefully when all free quotas are exhausted.

### Wizard flow

In the Console (S-139, browser-based):

```
? Configure free-tier LLM providers (recommended)

  [✓] Groq           [ Sign in with Groq        → ]
  [✓] Cerebras       [ Paste API key            ]
  [✓] Cloudflare AI  [ Open Cloudflare token UI → ]
  [✓] OpenRouter     [ Sign in with OpenRouter   → ]

  Bring your own:
  [ ] Anthropic       [ Paste API key            ]
  [ ] OpenAI          [ Paste API key            ]
  [ ] Local model     [ Configure local URL      ]

  [Continue]
```

Each OAuth button opens the provider's auth page in a popup; on success, the provider's API key (issued via OAuth, scoped per LiteLLM's request) flows back to the Console which stores it in the vault (S-141) and configures LiteLLM. Paste-API-key flows the same way without the popup.

For sovereignty-minded operators: deselect all defaults, configure only the local-model option (e.g., `http://127.0.0.1:11434/v1` for a local llama.cpp / vLLM / Ollama / OpenAI-compatible endpoint). No external providers in the chain. This must be a fully supported configuration.

### LiteLLM routing configuration

The wizard generates `~/.conductor/litellm.yaml`:

```yaml
model_list:
  # Free-tier preference order: provider-internal cost → cap → quality
  - model_name: tier-1-coder
    litellm_params:
      model: groq/llama-3.3-70b-versatile
      api_key: "${vault:groq_api_key}"     # secrets.use, never plaintext
  - model_name: tier-1-coder
    litellm_params:
      model: cerebras/llama-3.3-70b
      api_key: "${vault:cerebras_api_key}"
  - model_name: tier-1-coder
    litellm_params:
      model: openrouter/meta-llama/llama-3.3-70b-instruct:free
      api_key: "${vault:openrouter_api_key}"
  # ...

router_settings:
  routing_strategy: cost-based-routing
  fallbacks:
    - { tier-1-coder: [tier-1-coder, tier-2-coder, byok-anthropic] }
  retry_policy:
    rate_limit_retries: 1
    timeout_retries: 1
  cooldown_time: 30   # seconds before retrying a provider that hit a 429

litellm_settings:
  drop_params: true   # silently drop unsupported params per-provider
  set_verbose: false
  cache: true
  cache_params:
    type: in-memory
    ttl: 600
```

LiteLLM resolves `${vault:...}` references via the `secrets.use()` API (S-141). Keys never appear in plaintext in the YAML or in logs.

### Daily quota dashboard widget

The Console gets a small first-run widget visible in the dashboard:

```
┌─ LLM usage today ──────────────────────────────────────┐
│ Groq          : 8.4K / 14K tokens   ~|||||||~~~~     │
│ Cerebras      : 2.1K / 12K tokens   ~|||~~~~~~~      │
│ Cloudflare AI : 312 / 10K req       ~|~~~~~~~~~      │
│ OpenRouter    : 4.5K / 10K credits  ~||||||~~~~      │
│                                                       │
│ Total today: 14,200 tokens, 0 paid                    │
└──────────────────────────────────────────────────────────┘
```

This is the conversion artifact: operators see they got real value from their free-tier configuration; they're more invested in keeping it working; the architecture wins by accumulation.

### Bouncer integration

LiteLLM responses pass through the Bouncer like any other tool output (S-022). A model that returns a malicious tool-call sequence is screened before it reaches the agent loop. This is a defense-in-depth claim independent of provider trust.

## Acceptance Criteria

- [ ] Setup wizard offers 4 default free-tier providers; OAuth where supported, paste-API fallback elsewhere
- [ ] OAuth flows for Groq and OpenRouter complete in-browser without leaving the Console
- [ ] Cloudflare deep-link opens the CF dashboard scoped to Workers AI token creation; user pastes the resulting token; vault stores it
- [ ] Cerebras paste-API-key flow works without OAuth (until provider supports it); Console flags this as "OAuth pending provider support"
- [ ] All API keys stored in the vault (S-141); never written to disk in cleartext, never appear in litellm.yaml as a plaintext value
- [ ] LiteLLM routing prefers free-tier providers, falls back across them on rate-limit / outage, degrades gracefully when all are exhausted
- [ ] Daily quota widget on Console first run shows real numbers
- [ ] Sovereignty mode: configuration with zero external providers and one local OpenAI-compatible endpoint is fully supported and tested
- [ ] BYO Anthropic / OpenAI / others is supported via paste-API-key; appears in the wizard as an explicit non-default choice
- [ ] Bouncer screens LiteLLM responses; malicious tool-call sequences from any provider are caught
- [ ] Adding a new free-tier provider later is a Medley plugin install, not a conductor source change
- [ ] OAuth token expiry: when an OAuth-issued API key expires or is revoked by a provider, conductor surfaces a `PROVIDER_AUTH_EXPIRED` alert on the dashboard naming the provider and offering a one-click re-authentication link; LiteLLM routing automatically excludes the expired provider and falls back to remaining configured providers immediately — expired credentials are not silently retried until they begin generating 401 errors
- [ ] Privacy disclosure: the setup wizard explicitly surfaces a "free providers may train on your prompts" warning before storing any external API keys; the warning includes a link to each selected provider's privacy policy; sovereignty mode (local-only) is presented as a clear alternative in the same screen

## Implementation Notes

- **LiteLLM as router:** preferred over rolling our own. LiteLLM already handles 100+ providers with consistent params; we layer routing strategy + vault integration on top.
- **OAuth library:** standard OAuth 2.0 / OIDC flow per provider; use `authlib` or `oauth2-client` for the Console-side flow. Provider OAuth scopes are `litellm:read` / `litellm:write` equivalent where supported; minimum needed.
- **OAuth token refresh:** for providers that issue short-lived OAuth tokens, store the refresh token in the vault alongside the access token. A background task checks expiry 5 minutes ahead and refreshes; on refresh failure (revocation, expired refresh token), `PROVIDER_AUTH_EXPIRED` is posted to the dashboard.
- **Cloudflare deep-link:** Cloudflare doesn't expose OAuth for Workers AI tokens at API level today; the deep-link to https://dash.cloudflare.com/profile/api-tokens with a pre-filled template is the cleanest UX. Console waits for the user to paste back, then verifies by calling the Workers AI endpoint with the token.
- **Provider list updates:** the default-provider list lives in `~/.conductor/litellm-defaults.yaml`, shipped with each conductor release. Operators can override; updates land via the conductor update channel.
- **Quota tracking:** LiteLLM's per-provider request counters expose enough to build the widget; values are also persisted to SQLite (S-140) so usage survives reboots.
- **Rate-limit cooldown:** when a provider 429s, LiteLLM marks it cool-down for 30s and routes to siblings. Cooldown duration is per-provider configurable.
- **Composing with Ultra Think (S-039):** Ultra Think uses the same routing layer; quota-aware multi-model parallel generation respects the same per-provider counters.
- **Privacy:** by default, free-tier provider terms apply (most allow training-on-traffic). The wizard surfaces this honestly: *"Free providers may train on your prompts. For private workloads, use a local model or BYO commercial provider."* Sovereignty-minded operators see the warning and choose accordingly.

## Verification

- Fresh wizard run → all four default providers configured via OAuth/paste → first prompt routes successfully → daily widget shows non-zero usage.
- Sovereignty configuration: deselect all defaults, configure local llama.cpp endpoint → first prompt routes locally → zero external HTTP from conductor verified by tcpdump.
- BYO key: deselect free tier, paste Anthropic API key only → routing uses Anthropic exclusively.
- Rate-limit drill: artificially exhaust Groq's quota → router falls back to Cerebras → then Cloudflare → then OpenRouter; verify each transition in Langfuse traces.
- Vault leakage test: grep `~/.conductor/litellm.yaml` for known API key prefixes → zero matches; verify keys are only in `secrets.age`.
- Bouncer drill: LiteLLM mock returns a known prompt-injection payload → Bouncer rejects → agent loop never sees it.
- OAuth expiry test: simulate a revoked Groq OAuth token (set expiry to now); verify `PROVIDER_AUTH_EXPIRED` dashboard alert appears within 60s; verify routing falls back to Cerebras / OpenRouter immediately without 401 errors; re-authenticate; verify Groq re-enters the routing pool.
- Privacy disclosure: walk through wizard with all four defaults selected; verify warning appears before `[Continue]` is enabled; verify each provider's privacy policy link resolves.
- Provider addition: install a hypothetical `medley install litellm-fireworks` plugin → Fireworks appears as a routable provider without conductor source changes.
