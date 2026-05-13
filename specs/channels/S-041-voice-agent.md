---
id: S-041
title: "Voice agent — Alexa → HA Assist → Conductor"
domain: channels
status: done
priority: P2
effort: ""
created: 2026-03-23
updated: 2026-05-13
completed: 2026-03-23
owner: conductor
commits: []
depends_on: [S-022, S-007, S-042, S-104]
---

# S-041: Voice Agent

Custom HA component (`custom_components/conductor_agent`) routes Alexa voice commands
through HA Assist pipeline to conductor. 2–4s response via voice model group (S-042).

## Pipeline

Every voice command travels through a fixed sequence before any task is created or
executed. No step can be skipped.

```
Alexa STT → Voice ID check → Intent classify + query rewrite → Warden scan → Tier dispatch
```

### 1. STT transcript (untrusted)

The raw transcript arriving from Alexa is treated as untrusted external input — same
threat model as an email body. It is never inserted into an agent context directly.

### 2. Alexa Voice ID → speaker identity

Alexa passes a `voice_profile_id` in the request metadata when Voice ID is enrolled and
matches. The HA component looks this up in the `VoiceProfile` table:

- **Match found, profile active**: speaker is identified; proceed with their `privilege_tier`
  and `preferred_channel`.
- **No match or Voice ID not enrolled**: speaker is **anonymous**. Anonymous speakers are
  treated as unprivileged — any `PRIVILEGED`-tier intent routes to the admin dashboard queue.

### 3. Intent classification + query rewrite

The raw transcript is passed to the intent classifier (S-007 equivalent for voice). The
classifier returns:
- `tier`: `CONVERSATION` | `ARTIFACT` | `PRIVILEGED`
- `rewritten_prompt`: a clean, structured prompt form of the request — voice artifacts
  ("um", "uh", "hey conductor"), filler words, and trailing context stripped; intent
  expressed as a direct imperative.

The **rewritten prompt**, not the raw transcript, is what enters all downstream processing.

### 4. Warden scan

The rewritten prompt passes through Warden (S-022) before any task is created:
- Injection patterns, exfil patterns, prompt-attack signatures
- A Warden hit drops the request silently — no response on the Alexa device, no oracle
- Hit logged to Security dashboard tab with speaker identity (or "anonymous") and raw
  transcript (redacted to first 80 chars)

### 5. Tier dispatch

| Speaker | Tier | Action |
|---|---|---|
| Any | `CONVERSATION` | Execute directly — default AgentSpec (no tools) |
| Any | `ARTIFACT` | Execute directly — low blast radius |
| Identified + permissioned | `PRIVILEGED` | 2FA push to speaker's preferred channel |
| Anonymous or not permissioned | `PRIVILEGED` | Route to admin Dashboard Approvals queue |

**Channel isolation rule (same as S-103):** The 2FA confirmation channel must differ from
the request channel. Voice requests may use `push`, `ha`, `email`, or `telegram` for 2FA.
Voice-to-voice confirmation is not permitted.

```python
def get_voice_confirmation_path(profile: VoiceProfile | None) -> str:
    if profile and profile.privilege_tier == "privileged":
        return "2fa_push"
    return "admin_queue"
```

2FA push approval clears the admin queue entry and proceeds the task. Rejection drops it.
Timeout (15 min) leaves the task in the admin queue — not auto-dropped.

## Audio attack surface

**Ultrasonic injection** (inaudible commands at 18–24 kHz): Alexa hardware applies acoustic
bandpass filtering that attenuates frequencies outside human speech range. At the conductor
level, the defense is layered:
1. The rewritten prompt is Warden-scanned regardless of how the command arrived.
2. Privileged actions require out-of-band 2FA — an inaudible command cannot approve its
   own execution.

**Speaker spoofing / playback attacks**: Alexa's Voice ID enrollment includes liveness
detection. At the conductor level, an unrecognized voice (including a played-back
recording that fails Voice ID) is treated as anonymous and cannot trigger privileged tasks
without admin approval.

## Acceptance Criteria

**Pipeline integrity**
- [ ] Raw STT transcript is never inserted into agent context — only rewritten prompt proceeds
- [ ] Rewritten prompt passes through Warden before task creation
- [ ] A Warden hit silences the response on the Alexa device and logs to Security tab
- [ ] All voice-originated tasks default to `CONVERSATION` AgentSpec (empty tool list)
- [ ] Only the intent classifier can upgrade the tier — never the raw transcript alone

**Speaker identification**
- [ ] Alexa Voice ID `voice_profile_id` is resolved against `VoiceProfile` table before dispatch
- [ ] Unmatched or missing `voice_profile_id` → speaker treated as anonymous
- [ ] Anonymous speaker + `PRIVILEGED` intent → admin Dashboard Approvals queue

**Privilege confirmation**
- [ ] Identified + permissioned speaker + `PRIVILEGED` intent → 2FA push to preferred channel
- [ ] 2FA channel must not be `voice` (channel isolation enforced at dispatch)
- [ ] Push timeout (15 min) leaves task in admin queue — not auto-dropped
- [ ] Explicit rejection via push or Dashboard drops the task and logs it

**Audit**
- [ ] Every voice command creates a Langfuse trace: speaker identity (or "anonymous"), Warden verdict, classifier tier, task ID (if created)
- [ ] Every 2FA push event and dashboard action recorded in audit trail
- [ ] Warden hits include redacted transcript (first 80 chars) and full rewritten prompt

**Rate limiting**
- [ ] Per-profile cap: max 30 voice commands per hour; excess silently dropped and logged
- [ ] Global cap: max 200 voice commands per day across all profiles

## Implementation Notes

### VoiceProfile schema

```python
class VoiceProfile(Base):
    alexa_voice_id: str      # Alexa voice_profile_id from request metadata
    display_name: str
    privilege_tier: str      # "conversation" | "artifact" | "privileged"
    preferred_channel: str   # "push" | "ha" | "email" | "telegram" — never "voice"
    rate_limit_per_hour: int = 30
    active: bool = True
    created_at: datetime
```

### Pipeline sketch

```python
async def handle_voice_command(transcript: str, alexa_metadata: dict) -> None:
    voice_id = alexa_metadata.get("voice_profile_id")
    profile = await VoiceProfile.get_by_alexa_id(voice_id) if voice_id else None

    tier, rewritten_prompt = await intent_classifier.classify_and_rewrite(transcript)

    verdict = await warden.scan(rewritten_prompt, source="voice")
    if verdict.blocked:
        await audit.log_violation(verdict, source="voice", speaker=profile)
        return  # silence — no oracle

    if tier == "privileged":
        path = get_voice_confirmation_path(profile)
        if path == "admin_queue":
            await dashboard.queue_for_admin(rewritten_prompt, source="voice")
        else:
            await send_2fa_push(profile, rewritten_prompt)
    else:
        await execute_with_agentspec(rewritten_prompt, tier, source="voice")

def get_voice_confirmation_path(profile: VoiceProfile | None) -> str:
    if profile and profile.privilege_tier == "privileged":
        return "2fa_push"
    return "admin_queue"
```

### Key files
- `custom_components/conductor_agent/` (existing HA component)
- `conductor/orchestrator/channels/voice_handler.py` (pipeline implementation)
- `conductor/orchestrator/models/voice_profile.py` (VoiceProfile model)

## Verification

| Scenario | Expected |
|---|---|
| Recognized voice, `CONVERSATION` tier | Rewritten, Warden-scanned, executed |
| Recognized voice, `PRIVILEGED`, permissioned | 2FA push to preferred channel |
| Recognized voice, `PRIVILEGED`, not permissioned | Admin dashboard queue |
| Unrecognized voice, `PRIVILEGED` | Admin dashboard queue |
| Warden hit on rewritten prompt | Silenced on device, logged to Security tab |
| 2FA push approved | Task proceeds with correct AgentSpec |
| 2FA push rejected | Task dropped, logged |
| 2FA push timeout (15 min) | Task remains in admin queue |
| Ultrasonic command (if bypasses Alexa hardware) | Warden-scanned; if PRIVILEGED, requires human 2FA approval |
| Playback attack (Voice ID fails) | Treated as anonymous; PRIVILEGED routes to admin queue |
| Speaker exceeds 30 commands/hour | Excess silently dropped, logged |
