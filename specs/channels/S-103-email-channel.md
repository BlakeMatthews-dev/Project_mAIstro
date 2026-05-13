---
id: S-103
title: "Email channel — conductor@emeraldfam.org"
domain: channels
status: draft
priority: P2
effort: "~600 lines"
created: 2026-03-23
updated: 2026-05-13
completed: ""
owner: conductor
commits: []
depends_on: [S-022, S-141, S-143, S-007]
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
- Attachment filenames and MIME types

A Bouncer hit returns `SAFETY_VIOLATION` and logs to the Security dashboard tab. The sender
receives no bounce (no oracle).

**2FA callback for privileged tasks:**

The 3-phase classifier (S-007) assigns an intent tier to each email. Tiers map to action:

| Classifier output | Action |
|---|---|
| `CONVERSATION` | Process directly — no tools, no confirmation needed |
| `ARTIFACT` (file write, search) | Process directly — low blast radius |
| `PRIVILEGED` (skill execution, infra alert, memory write) | Send 2FA confirmation to sender's preferred channel before proceeding |

The 2FA confirmation is a short push/HA/email notification:
> "Conductor received an email from you: [task summary — max 80 chars]. Approve? Yes / No"

Only on `Yes` does the task proceed. Timeout (15 min) = implicit No. This is the only step
that requires any action from the sender, and only for sensitive operations.

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
- [ ] Attachment types outside the allowlist (plain-text, PDF) are rejected with a logged reason

**AgentSpec scoping**
- [ ] All email-originated tasks default to `CONVERSATION` AgentSpec (empty tool list)
- [ ] Only the 3-phase classifier (S-007) can upgrade the tier — never user input alone
- [ ] `PRIVILEGED`-tier tasks require a confirmed 2FA callback before the AgentSpec is constructed

**2FA callback**
- [ ] `PRIVILEGED` tasks trigger a confirmation notification to the sender's configured preferred channel
- [ ] Confirmation timeout (15 min) = implicit rejection; task is dropped and logged
- [ ] Confirmation includes a human-readable summary of the requested action (≤80 chars)
- [ ] A rejected or timed-out confirmation logs to the audit trail

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
- [ ] Every 2FA confirmation/rejection/timeout is recorded in the audit trail
- [ ] Every outbound email logs: recipient (hashed), template name, trigger event

## Implementation Notes

### Personalized address table schema

```python
class EmailSender(Base):
    code: str          # 8-char random token — this is the routing key
    display_name: str
    email_address: str # for audit/display only, not used for auth
    preferred_channel: str  # "push" | "ha" | "email" | "telegram"
    privilege_tier: str     # "conversation" | "artifact" | "privileged"
    rate_limit_per_hour: int = 20
    active: bool = True
    created_at: datetime
    rotated_at: datetime | None
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
| Email to `a7x3b2qp.conductor@emeraldfam.org` with valid DKIM + correct code | Task created (or 2FA triggered) |
| Email with valid code but failing DKIM | Rejected, logged, no task |
| Email with invalid/unknown code prefix | Silently dropped |
| Body contains prompt-injection payload | Bouncer rejects, logged to Security tab, no task |
| Quoted reply block contains injection payload | Bouncer rejects on quoted block scan, no task |
| `PRIVILEGED`-tier task: user approves 2FA | Task proceeds with correct AgentSpec |
| `PRIVILEGED`-tier task: user ignores (timeout) | Task dropped, logged |
| `PRIVILEGED`-tier task: user rejects | Task dropped, logged |
| Sender exceeds 20 emails/hour | Excess silently dropped, logged |
| Outbound digest: inspect SMTP call | No API key in logs, no key in env — fetched via `secrets.use()` |
