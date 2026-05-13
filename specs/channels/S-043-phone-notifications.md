---
id: S-043
title: "Phone notifications — ha_notify tool (Blake/Bella/Lilly/all)"
domain: channels
status: done
priority: P2
effort: ""
created: 2026-03-23
updated: 2026-05-13
completed: 2026-03-23
owner: conductor
commits: []
depends_on: [S-022, S-007]
---

# S-043: Phone Notifications

`ha_notify` sends push notifications to family members via HA mobile app. Targets: `blake`,
`bella`, `lilly`, or `all` (broadcast). This channel serves two distinct uses:

1. **System path**: orchestrator calls notification API directly for 2FA confirmations,
   P0 alerts, and morning digests — never goes through the agent tool.
2. **Agent tool path**: `ha_notify` available in AgentSpec tool list for tasks that need
   to surface a result or status to a person.

These paths have separate authorization gates and separate rate-limit budgets.

## The spam problem

The existing conductor fires notifications freely — no caps, no coalescing, no quiet hours.
This creates alert fatigue and trains users to dismiss notifications without reading them,
which directly undermines the 2FA model (a "Yes" tap from a fatigued user who stopped
reading is not meaningful consent). The controls below are mandatory, not optional.

## Agent tool path — authorization

`ha_notify` is gated by AgentSpec tier:

| AgentSpec tier | ha_notify access | Target scope |
|---|---|---|
| `CONVERSATION` | None — tool not in list | — |
| `ARTIFACT` | Single targeted recipient only | `blake` \| `bella` \| `lilly` |
| `PRIVILEGED` | Any target including broadcast | `blake` \| `bella` \| `lilly` \| `all` |

`target="all"` is only available in a `PRIVILEGED`-scoped AgentSpec. An ARTIFACT-tier task
attempting to broadcast must be rejected at tool call time, not silently ignored.

## Rate limiting (agent tool path)

Per-recipient hard cap: **5 notifications per hour, 20 per day**.
Global cap: **50 notifications per day** across all recipients.

Broadcast (`target="all"`) counts as N notifications against each recipient's budget and
against the global budget (e.g., broadcast to 3 recipients = 3 deductions).

Excess notifications are dropped and logged. The agent receives a `RATE_LIMIT_EXCEEDED`
tool error so it does not retry silently.

## Rate limiting (system path)

2FA confirmations, P0 alerts, and morning digests use a separate budget and are exempt
from the agent tool caps above. However:

- P0 alerts: max 3 per hour per alert type (deduplication prevents storm)
- 2FA confirmations: 1 per pending task — no retries unless user explicitly requests resend
- Morning digest: 1 per day per recipient

## Notification coalescing

If the same task or trigger would fire multiple notifications to the same recipient within
a **60-second window**, collapse to a single notification. The collapsed notification
includes the count:
> "3 updates from conductor — tap to view"

Deduplication key: `(recipient, content_hash)` within the coalescing window. Same message
sent twice in 60 seconds = one delivery.

## Quiet hours

Each recipient has configurable quiet hours (default: 22:00–07:00 local time).

| Notification type | During quiet hours |
|---|---|
| `CONVERSATION` / `ARTIFACT` agent tool | Queued — delivered at quiet hours end |
| `PRIVILEGED` agent tool | Delivered immediately |
| P0 alert (system path) | Delivered immediately |
| 2FA confirmation (system path) | Delivered immediately — time-sensitive |
| Morning digest (system path) | Delivered at quiet hours end (by design) |

## Actionable notifications (2FA response path)

2FA confirmations include HA notification actions (`APPROVE` / `REJECT`). When the user
taps an action, HA fires a `mobile_app_notification_action` event. The conductor component
listens for this event and correlates it to a pending task by `notification_id`.

**Replay protection**: each `notification_id` is a single-use UUID. The first action event
consumed marks the ID as spent; any subsequent event with the same ID is discarded and
logged. This prevents a double-tap or a replayed push from approving a task twice.

**Action timeout**: if no action event arrives within 15 minutes, the task remains in the
Dashboard queue (not auto-dropped). The push notification is marked expired in the audit
trail.

## Content rules

- Notification body: max 100 chars. Truncate with `…` if longer.
- No PII (email addresses, phone numbers, account numbers) in notification body — these
  appear on lock screens.
- Agent-generated content sanitized before insertion (strip markdown, escape special chars).
- 2FA confirmation body format: `"[Task summary ≤80 chars] — Approve?"` (fixed template,
  not agent-generated).

## Vault pattern

HA long-lived access token for notification delivery fetched via `secrets.use()`.

```python
async def send_notification(target: str, message: str, actions: list | None = None) -> None:
    await secrets.use("ha_notify_token", lambda token:
        ha_client.notify(target=target, message=message, actions=actions, token=token)
    )
```

## Acceptance Criteria

**Agent tool gating**
- [ ] `ha_notify` absent from `CONVERSATION` AgentSpec tool list
- [ ] `ARTIFACT`-tier tasks can notify a single named recipient only — broadcast rejected at tool call time
- [ ] `PRIVILEGED`-tier tasks can use any target including `all`

**Rate limiting**
- [ ] Per-recipient cap: 5/hour, 20/day — enforced before tool call reaches HA
- [ ] Global cap: 50/day across all recipients
- [ ] Broadcast deducted from each recipient's budget and global budget
- [ ] Excess returns `RATE_LIMIT_EXCEEDED` tool error to agent (not silent drop)
- [ ] System path (2FA, P0, digest) uses separate budget — not deducted from agent cap
- [ ] P0 alerts deduplicated: max 3/hour per alert type

**Coalescing + deduplication**
- [ ] Multiple notifications to same recipient within 60s collapsed to one
- [ ] Dedup key: `(recipient, content_hash)` within coalescing window
- [ ] Collapsed notification shows count

**Quiet hours**
- [ ] CONVERSATION/ARTIFACT notifications queued during quiet hours, delivered at end
- [ ] PRIVILEGED, P0, and 2FA bypass quiet hours
- [ ] Quiet hours configurable per recipient (default 22:00–07:00)

**Actionable notifications (2FA)**
- [ ] 2FA confirmations include `APPROVE` / `REJECT` HA notification actions
- [ ] `notification_id` is a single-use UUID — replay of same ID discarded and logged
- [ ] Action timeout (15 min): task remains in Dashboard queue, push marked expired in audit

**Content**
- [ ] Notification body capped at 100 chars, truncated with `…`
- [ ] No PII in notification body
- [ ] Agent-generated content sanitized before insertion
- [ ] 2FA body uses fixed template, not agent-generated text

**Credentials**
- [ ] HA token fetched via `secrets.use()` — not stored in env or config

**Audit**
- [ ] Every notification logs: recipient, target, notification_id, type (agent/2FA/P0/digest), rate-limit status
- [ ] Every replay-protection discard logged
- [ ] Every rate-limit drop logged with task ID and current budget state

## Verification

| Scenario | Expected |
|---|---|
| CONVERSATION task calls `ha_notify` | Tool error — not in AgentSpec |
| ARTIFACT task calls `ha_notify(target="all")` | Rejected at tool call, logged |
| ARTIFACT task calls `ha_notify(target="blake")` | Delivered (if within budget, not quiet hours) |
| Recipient hits 5/hour cap | `RATE_LIMIT_EXCEEDED` returned to agent, notification dropped |
| Same message sent twice within 60s | One delivery, collapsed notification |
| 2FA push tapped "Approve" twice (double-tap) | Second tap discarded, logged (replay protection) |
| 2FA push during quiet hours | Delivered immediately (exempt) |
| ARTIFACT notification during quiet hours | Queued, delivered at quiet hours end |
| P0 alert fires 4 times in one hour | First 3 delivered, 4th deduplicated and dropped |
| HA token: inspect call | Token fetched via `secrets.use()`, not in logs or env |
