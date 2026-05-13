---
id: SPEC-002
title: "Email channel — conductor@emeraldfam.org"
repo: Project_mAIstro
kind: spec
status: Proposed
created: 2026-03-23
substrate: []
implements: []
related:
  - Project_mAIstro#SPEC-001
  - Project_mAIstro#SPEC-011
  - Project_mAIstro#SPEC-013
  - Project_mAIstro#S-007
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# S-103: Email Channel

## Problem

No email ingestion or outbound email from conductor. Can't reach conductor via email. The
original spec had a single security control (sender allowlist) which is insufficient — email
`From:` headers are trivially spoofable, and email bodies are a high-value prompt-injection
surface because they arrive as arbitrary untrusted text from an external network.

## Solution

### Inbound: Cloudflare Email Routing + personalized addresses + Bouncer

Each approved sender gets a **personalized routing address** rather than sharing a single
public address:

```
{per-user-code}.conductor@emeraldfam.org  →  inbound handler
```

The `{per-user-code}` is a short random token (8 chars, alphanumeric) assigned when the
sender is added to the allowlist. They save it in their contacts once and never think about
it again. Zero ongoing friction. If a code is compromised, rotate only that sender's code —
no other senders are affected.

The catch-all Cloudflare worker extracts the prefix, validates it against the allowlist
table, then passes the envelope to the inbound handler. Emails to the bare
`conductor@emeraldfam.org` address are silently dropped (no bounce — no oracle for
attackers).

**Anti-spoofing layer (invisible to senders):**

Cloudflare Email Routing exposes DKIM/SPF/DMARC verification results in the forwarded
envelope headers. The inbound handler rejects any message where:
- SPF result is not `pass`
- DKIM result is not `pass` for the sender's domain
- DMARC policy is `reject` or `quarantine` and the message failed alignment

Gmail, iCloud, Outlook, and Fastmail all set these automatically. A legitimate sender on
any major provider passes all three without doing anything differently. Only a spoofer fails.

**Bouncer wiring (invisible to senders):**

Every inbound email passes through the Bouncer (S-022) before any task is created:
- Subject line
- Plain-text body (HTML stripped first)
- Each quoted/forwarded reply block scanned *separately* (see Implementation Notes)
- Attachment filenames, MIME types, and file content (via `warden.file_scan()` — see S-022)

A Bouncer hit returns `SAFETY_VIOLATION` and logs to the Security dashboard tab. The sender
receives no bounce (no oracle).

**Dashboard queue + optional 2FA for privileged tasks:**

The 3-phase classifier (S-007) assigns an intent tier to each email. Tiers map to action:

| Classifier output | Action |
|---|---|
| `CONVERSATION` | Process directly — no tools, no confirmation needed |
| `ARTIFACT` (file write, search) | Process directly — low blast radius |
| `PRIVILEGED` (skill execution, infra alert, memory write) | Held in Dashboard Approvals queue until approved |

**Primary approval path — Dashboard queue:** `PRIVILEGED`-tier tasks land in the Dashboard
Approvals queue and wait there until the owner approves or rejects via an authenticated
Keycloak session. No action required from the sender.

**Optional shortcut — 2FA push:** If the sender has a preferred channel configured (`push`,
`ha`, or `telegram`) and that channel differs from the request channel (email), conductor
sends a parallel notification:
> "Conductor received an email from you: [task summary — max 80 chars]. Approve? Yes / No"

Approving via the push notification clears the Dashboard queue entry and the task proceeds
immediately. Rejecting via push also clears it. Either way, the Dashboard queue is always
the authoritative record.

**Channel isolation rule:** The 2FA shortcut channel must never be the same as the request
channel. An email request cannot use `email` as its 2FA channel — that would allow an
attacker who can send email to also intercept the confirmation loop. Approved 2FA channels
for email requests: `push`, `ha`, `telegram`. If no out-of-band channel is configured, the
task waits in the Dashboard queue only.

```python
def get_confirmation_path(request_channel: str, sender_2fa_channel: str | None) -> str:
    if sender_2fa_channel and sender_2fa_channel != request_channel:
        return "dashboard_plus_2fa_push"
    return "dashboard_only"
```

Push timeout (15 min with no response) does not drop the task — it remains in the Dashboard
queue. The task is only dropped if explicitly rejected via push or Dashboard.

### Outbound: Vault-brokered SMTP

Outbound email (morning digests, P0 alerts) uses an SMTP relay or transactional API
(Postmark, etc.). Credentials are fetched via `secrets.use()` — never stored in env vars or
config files. Outbound content that includes agent-generated text is sanitized before HTML
insertion (strip unsupported tags, escape dynamic values).

## Acceptance Criteria

**Inbound identity & anti-spoofing**
- [ ] Emails to the bare `conductor@emeraldfam.org` address are silently dropped
- [ ] Each approved sender has a unique `{code}.conductor@emeraldfam.org` address stored in the allowlist table
- [ ] Emails failing SPF, DKIM, or DMARC alignment are rejected before allowlist check
- [ ] Allowlist check validates the `{code}` prefix, not the `From:` header alone
- [ ] Rotating a sender's code does not affect any other sender

**Bouncer + injection defense**
- [ ] Subject line passes through Bouncer before task creation
- [ ] Plain-text body (HTML stripped) passes through Bouncer before task creation
- [ ] Each quoted reply block is extracted and scanned separately by the Bouncer
- [ ] A Bouncer hit drops the email silently and logs to the Security dashboard tab
- [ ] All attachments pass through `warden.file_scan()` (S-022) before content enters any agent context
- [ ] Files failing magic-bytes check are hard-blocked (`FILE_INTEGRITY_VIOLATION`)
- [ ] Files triggering zip-bomb detection are hard-blocked (`ZIP_BOMB_DETECTED`)
- [ ] Non-text-carrier files with extracted strings are labeled untrusted and Warden-scanned with elevated scrutiny
- [ ] Parser-vs-strings diff content is labeled untrusted and Warden-scanned with elevated scrutiny

**AgentSpec scoping**
- [ ] All email-originated tasks default to `CONVERSATION` AgentSpec (empty tool list)
- [ ] Only the 3-phase classifier (S-007) can upgrade the tier — never user input alone
- [ ] `PRIVILEGED`-tier tasks require approval before the AgentSpec is constructed

**Dashboard queue + 2FA**
- [ ] `PRIVILEGED` tasks are held in the Dashboard Approvals queue, visible only to authenticated (Keycloak) sessions
- [ ] If sender's preferred channel is configured and differs from the request channel, a 2FA push notification is sent in parallel
- [ ] The 2FA channel must never match the request channel — enforced at `EmailSender` registration and task dispatch
- [ ] Approving via push clears the Dashboard queue entry and proceeds the task
- [ ] Rejecting via push clears the Dashboard queue entry and drops the task
- [ ] Push timeout (15 min) leaves the task in the Dashboard queue — not auto-dropped
- [ ] Explicit rejection via Dashboard or push logs to the audit trail with reason
- [ ] Confirmation push includes a human-readable summary of the requested action (≤80 chars)

**Outbound**
- [ ] SMTP/transactional API credentials fetched via `secrets.use()` — no plaintext in env or config
- [ ] Morning digests deliverable via email (not just channel message)
- [ ] P0 infrastructure alert emails sent within 60 seconds of event
- [ ] All agent-generated content sanitized before insertion into HTML email templates

**Rate limiting**
- [ ] Per-sender cap: max 20 inbound emails per hour; excess dropped and logged
- [ ] Global inbound cap: max 100 emails per day across all senders; excess queued with back-pressure

**Audit**
- [ ] Every inbound email creates a Langfuse trace including: sender code, DKIM/SPF result, Bouncer verdict, classifier tier, task ID (if created)
- [ ] Every Dashboard queue action (approval/rejection) and 2FA push event (sent/approved/rejected/timeout) is recorded in the audit trail
- [ ] Every outbound email logs: recipient (hashed), template name, trigger event

## Implementation Notes

### Personalized address table schema

```python
class EmailSender(Base):
    code: str          # 8-char random token — this is the routing key
    display_name: str
    email_address: str # for audit/display only, not used for auth
    preferred_channel: str  # "push" | "ha" | "telegram" — never "email" (channel isolation rule)
    privilege_tier: str     # "conversation" | "artifact" | "privileged"
    rate_limit_per_hour: int = 20
    active: bool = True
    created_at: datetime
    rotated_at: datetime | None
```

### Channel isolation rule

The 2FA push shortcut is only available when `preferred_channel != request_channel`. For
email-originated requests, `preferred_channel` must be `push`, `ha`, or `telegram`. If
`preferred_channel` is unset or equals the request channel, the task uses the Dashboard
queue only — no 2FA push is sent.

The same principle applies symmetrically to other channels: a voice request can use `email`
as its 2FA channel (different channel), but not `voice`. This is enforced at task dispatch,
not just at registration, to handle edge cases where configuration changes after
registration.

```python
def get_confirmation_path(request_channel: str, sender_2fa_channel: str | None) -> str:
    if sender_2fa_channel and sender_2fa_channel != request_channel:
        return "dashboard_plus_2fa_push"
    return "dashboard_only"
```

### Reply-chain stripping

Most email clients quote prior messages with `>` prefixes or `-- Original Message --`
delimiters. The inbound handler must:
1. Split the body on known quote delimiters (`>`, `On [date] ... wrote:`, `-- Original Message --`, `From:` at line start)
2. Scan the *new content* (top section) first — this is the sender's actual message
3. Scan each quoted block *separately* — a Bouncer hit in any block rejects the whole email
4. Never concatenate new content and quoted content before scanning (defeats context isolation)

This prevents the forwarded-thread injection pattern: attacker sends a benign email → user
replies forwarding it to conductor → attacker's original content is now in the quoted block.

### Cloudflare Email Worker sketch

```javascript
export default {
  async email(message, env, ctx) {
    // 1. Extract routing code from the To address
    const to = message.to;  // e.g. "a7x3b2qp.conductor@emeraldfam.org"
    const match = to.match(/^([a-z0-9]{8})\.conductor@/i);
    if (!match) { message.setReject("Unknown address"); return; }
    const code = match[1];

    // 2. Validate DKIM/SPF (Cloudflare surfaces these as headers)
    const dkim = message.headers.get("X-Google-DKIM-Signature") ?? 
                 message.headers.get("DKIM-Signature");
    // Full validation happens in the inbound handler via envelope metadata

    // 3. Forward to inbound handler with envelope metadata
    await fetch(env.CONDUCTOR_EMAIL_WEBHOOK, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        from: message.from,
        subject: message.headers.get("Subject"),
        message_id: message.headers.get("Message-ID"),
        // raw forwarded for full parsing in handler
      })
    });
  }
}
```

### Vault pattern for outbound credentials

```python
# Correct — credential never held in variable scope
async def send_digest(recipient: str, body: str) -> None:
    await secrets.use("smtp_api_key", lambda key:
        smtp_client.send(to=recipient, body=body, api_key=key)
    )

# Wrong — never do this
api_key = await secrets.get("smtp_api_key")
smtp_client.send(to=recipient, body=body, api_key=api_key)
```

## Verification

| Scenario | Expected |
|---|---|
| Email to bare `conductor@emeraldfam.org` | Silently dropped, no bounce |
| Email to `a7x3b2qp.conductor@emeraldfam.org` with valid DKIM + correct code | Task created (or queued for approval) |
| Email with valid code but failing DKIM | Rejected, logged, no task |
| Email with invalid/unknown code prefix | Silently dropped |
| Body contains prompt-injection payload | Bouncer rejects, logged to Security tab, no task |
| Quoted reply block contains injection payload | Bouncer rejects on quoted block scan, no task |
| Attachment: declared PNG, magic bytes are ZIP | Hard block (`FILE_INTEGRITY_VIOLATION`), logged |
| Attachment: ZIP with >1000:1 compression ratio | Hard block (`ZIP_BOMB_DETECTED`), logged |
| Attachment: JPEG with embedded strings | Strings labeled untrusted, Warden-scanned with elevated scrutiny |
| Attachment: PDF with hidden instructions in raw binary | Parser-vs-strings diff labeled untrusted, Warden-scanned |
| `PRIVILEGED`-tier task, no 2FA channel configured | Task held in Dashboard queue only |
| `PRIVILEGED`-tier task, `preferred_channel = "email"` | Dashboard queue only (channel isolation suppresses 2FA push) |
| `PRIVILEGED`-tier task: push configured, user approves via push | Dashboard entry cleared, task proceeds |
| `PRIVILEGED`-tier task: push configured, user ignores (15 min timeout) | Task remains in Dashboard queue, not dropped |
| `PRIVILEGED`-tier task: user rejects via Dashboard | Task dropped, logged |
| `PRIVILEGED`-tier task: user rejects via push | Task dropped, logged |
| Sender exceeds 20 emails/hour | Excess silently dropped, logged |
| Outbound digest: inspect SMTP call | No API key in logs, no key in env — fetched via `secrets.use()` |
