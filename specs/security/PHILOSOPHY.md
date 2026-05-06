# Project mAIstro — Philosophy

_The "why" behind the security model. Specs answer how; this document answers why._

**Status:** living document
**Audience:** anyone reading the spec tree for the first time, anyone evaluating whether this project's posture matches their values, anyone reviewing a PR that touches a security-relevant primitive.

---

## The headline

> **Windows doesn't run apps as Administrator. Linux requires sudo. Why does your AI agent default to root?**
>
> Agent Conductor is secure by design — human-in-the-loop for critical actions, separation of privilege by default. You don't give your handyman your banking login or the keys to your safe. So why give them to your AI?
>
> Your conductor stores credentials in a sealed vault. It can't leak what it doesn't know.

Three sentences, three claims, every word load-bearing.

---

## Why these analogies, not others

### "Why does your AI agent default to root?"

Operating systems learned this lesson decades ago. Windows nudged users away from running as Administrator over multiple OS generations because it kept being the dominant malware vector. Linux made `sudo` mandatory for privileged commands and considered it a basic safety property. Both made the conscious choice that the *default* mode for the user is non-privileged, and elevation is *deliberate, audited, and reversible*.

The AI agent industry skipped this step. The dominant pattern — OpenClaw, similar projects, even most enterprise agent platforms — is: one user, that user has root, the agent runs in that user's privilege. A single prompt-injection drains a wallet. A single misconfigured plugin exfiltrates a calendar. Cisco's AI security team [found this in production](https://www.crowdstrike.com/en-us/blog/what-security-teams-need-to-know-about-openclaw-ai-super-agent/) inside the most popular open-source agent of 2026. It is not a hypothetical risk.

Maistro's privilege primitive (S-142) makes single-user-as-root structurally impossible. The setup wizard does not produce a working installation with one user. The capability envelope (S-002–S-005) is constructed against a verified identity that is *either* admin *or* user1 — never both, never neither. Elevation is signed, audited, and reversible. The OS lesson, applied to the AI agent.

### "You don't give your handyman your banking login or the keys to your safe."

This is the analogy for non-technical operators. Everyone gets it instantly. You hire a handyman because you trust them to fix the sink. You don't trust them with your bank account, because *you don't have to* — the sink job doesn't require it.

Most AI agent integrations today demand far more privilege than the task requires. Mailbox-reading agents get full mailbox write access. Calendar-summarizing agents get appointment-scheduling access. Wallet-reading agents get spending authority. The handyman is being handed the safe keys because the agent platform doesn't know how to scope.

Maistro's response is structural: every privileged action requires elevation, every elevation is signed by admin's key (S-149/S-150/S-151), every signature is recorded as a Verifiable Credential (S-152) in an audit log the operator can replay. The handyman fixes the sink. The conductor reads your calendar but cannot create events without you tapping approve. The agent gets exactly the keys the job needs, for exactly the duration of the job.

### "Your conductor stores credentials in a sealed vault. It can't leak what it doesn't know."

The load-bearing word is *can't*, not *shouldn't* or *won't*.

Most AI agent platforms store credentials such that the agent process can read them and emit them in trace logs, prompt outputs, or tool arguments. "Don't leak credentials" becomes a behavioral rule the model is supposed to follow. Behavioral rules fail under prompt injection — they're trained, not enforced.

Maistro's vault (S-141) inverts the architecture. The agent never holds credential *values* in its variable scope. The vault API is `secrets.use(name, callback)`: the vault opens a lambda scope, hands the credential into it, runs the callback, then zeroes the memory and returns the result. The agent gets a result. It does not get the secret. The Bouncer (S-022) additionally rejects any agent output containing a substring matching a vault entry — a final-line defense if a credential somehow slipped.

This is the architectural choice that makes "can't leak what it doesn't know" a load-bearing claim instead of a vibe.

---

## What this philosophy commits us to

Four invariants flow from these analogies. They are non-negotiable in the spec tree.

### 1. Two users by default, always.

The setup wizard's flow does not produce a working installation with fewer than two users. There is no admin-only mode, no "single power user" shortcut, no environment variable to disable user1. If the operator wants no second human in the loop, they create a user1 named "automation" or similar and decide which capability tier it gets — but the *separation* exists, even when the operator is the only person around. This is the structural property that makes everything else hold. (S-142)

### 2. Capability envelopes are typed, immutable, and code-constructed.

A `CONVERSATION` role has the empty tool list. Always. There is no flag, no override, no user input that promotes a CONVERSATION-classified turn to tool-bearing. The envelope is a Python object constructed by the intent classifier and the heartbeat runner; it never round-trips through disk; it cannot be edited by the agent. Operators who want different capability scoping can edit `agent_spec.py` and ship a new release — they cannot get there at runtime by talking to the conductor. (S-002–S-005)

### 3. Secrets are brokered, not handed out.

The vault API is `secrets.use(name, callback)`. The shape `secrets.get(name)` does not exist anywhere in the conductor codebase. Agent code cannot ever hold a credential value in its variable scope. The vault is the only thing that knows secret values; the conductor is the only thing that talks to the vault; the agent is the only thing that can request a `use`, and only via callback. (S-141)

### 4. Every privileged action is signed, every signature is a VC, every VC is replayable.

Elevation approvals are BIP-322-signed by admin's key derived from the Conductor Seed (S-149). Each signed approval is recorded as a Verifiable Credential (S-152) in the audit log. The dashboard's Intel tab can replay the chain at any time and verify each link against the conductor's published DID. "Why did this agent do that?" has a structured answer that survives the agent's death, the host's death, and the operator's memory. (S-149/S-150/S-151/S-152)

---

## What this philosophy explicitly is not

- **It is not a promise that the conductor cannot be compromised.** It is a promise that compromise is bounded — by the capability envelope, by the spending policy, by the hot/cold wallet split, by the audit log that records what happened.
- **It is not a promise that operators can't shoot themselves in the foot.** They can disable the Bouncer, install unsigned plugins with `--allow-unsigned`, set their daily-spend cap to a billion sats, run user1 with admin privileges. But they have to *do those things deliberately*, and each one is recorded.
- **It is not a promise that we'll keep up with every novel attack class.** The Red/Blue self-hardening loop (S-026) generates novel attacks against the conductor continuously, and the Bouncer's pattern library grows from confirmed bypasses. But "the model gets smarter than the Bouncer" is a real risk class and we say so plainly.
- **It is not a promise that crypto / Lightning / DID is required to use Maistro.** All of those are opt-in (S-151, S-152, S-156). A conductor with no crypto installed is fully functional and security-bearing. The crypto features add capability for operators who want it; they do not gate the core posture for operators who don't.

---

## Where this lives in the spec tree

This document is referenced as the *why* by every security-bearing spec:

- **S-022** (Bouncer) cites this for "why a hard pre-execution gate"
- **S-024** (JWT auth) cites this for "why role-keyed tool whitelists"
- **S-141** (Vault) cites this for "why brokered, not get/set"
- **S-142** (Privilege separation) cites this for "why two users mandatory"
- **S-149** (Conductor Seed) cites this for "why one root of trust under the operator's control"
- **S-152** (DID + VC) cites this for "why every action is verifiable post-hoc"
- **S-155** (Internal trust root) cites this for "why operators can run their own CA"

If a future spec needs to *break* one of these invariants, it must justify the break here, and the discussion happens publicly in the spec tree before the code lands.
