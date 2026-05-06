---
id: S-139
title: "Setup wizard — browser-first install ceremony, CLI fallback, shares Console codebase"
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

# S-139: Setup Wizard

## Problem

Fresh-install onboarding is the conversion moment. Every other spec in Agent Conductor exists to support a household / power-user / sovereignty-minded operator going from `curl install.sh | sh` (or `.msi` double-click on Windows) to a working conductor. If the wizard is bad, none of the other architectural choices reach a user.

The wizard has to:

- Run in the browser (S-138, S-147), with CLI fallback for headless installs.
- Be functionally identical across Linux / macOS / Windows.
- Walk an operator through *every* required configuration step — seed phrase, admin keypair, user creation, network substrate, TLS mode, LLM providers, channels, optional crypto — in one continuous flow.
- Never produce an insecure install. Two-user mandate (S-142), Bouncer enabled (S-022), vault encrypted (S-141), substrate selected (S-153), TLS chosen (S-155).
- Take ~5 minutes for the easy path (Tailscale, free LLM, no crypto), longer for opt-in paths.
- Share code with the running Console (S-016) so design + auth surface is consistent.

## Solution

A **browser-first wizard** served from a temporary localhost endpoint by the conductor binary at first run. The wizard is built into the same web UI codebase as the runtime Console (S-016); installation and ongoing operation use the same components, the same theming, the same session model.

### Install ceremony, end to end

```
# Linux / macOS
curl -fsSL maistro.dev/install.sh | sh
   └─ verifies signature
      installs binary as systemd unit / launchd plist
      conductor binary starts in setup mode
      binds 127.0.0.1:9999 with one-time token
      attempts to open the default browser at http://127.0.0.1:9999/setup?token=<one-time>
      on headless: prints the URL + token + instructions for ssh -L forwarding

# Windows
Double-click maistro-setup-vX.Y.Z.msi (signed .msi, S-147)
   └─ SmartScreen recognizes signature
      MSI installer registers Windows Service
      Service starts in setup mode → same localhost flow
      opens default browser
```

The operator interacts with the wizard in their browser; everything else happens automatically.

### Wizard flow (the steps)

```
Step 1 — Name your conductor
        Single text input. "Brigid" / "Atelier" / "Maestro Junior" / etc.
        This name flows into:
          - dashboard header
          - audit-log entries
          - DID document (S-152)
          - federation handshake (S-156)
        Validation: alphanumeric + hyphens, 3-32 chars.

Step 2 — Generate Conductor Seed (S-149)
        Three sub-options:
          a) Generate a 24-word BIP39 phrase (default)
          b) Connect a hardware wallet (Ledger / Trezor) — S-150
          c) SLIP39 Shamir backup (3-of-5 by default)
        Whichever path, the wizard:
          - Displays the phrase ONCE (visual reveal animation, no copy-paste)
          - Requires explicit "I have written these down" gate
          - Offers to print a recovery card with QR of the m/0' public key
          - Verifies the operator can re-enter at least 3 random words from the
            phrase before continuing (proof-of-write-down)

Step 3 — Create admin
        Admin password (passphrase-style, used to unlock OS-keychain on desktop
          OR the headless private-key file on Linux without D-Bus).
        Admin keypair is derived from the seed (S-149 m/0'), not separately generated.
        Admin recovery card (single page):
          - 24 words
          - QR of public key
          - Instance name + date
          - "Store this like a passport" warning
        Print / save / acknowledge.

Step 4 — Create user one (REQUIRED)
        Form fields: name, optional email, role (always 'user' here).
        User identity keypair is derived from the seed at m/44'/9000'/1' (S-142).
        Form does not advance without a name.
        There is no "skip" button. There is no CLI flag. (S-142 invariant)

Step 5 — Anyone else in your household?
        Optional. "Add another user" / "Continue."
        Add 0..N more users; each gets m/44'/9000'/<index>'.
        Each user gets their own welcome card with their identity keypair fingerprint.

Step 6 — Network this conductor (substrate, S-153)
        Menu:
          Mesh substrates (recommended class):
            • Tailscale (default; managed coordination)
            • Headscale (self-hosted Tailscale-compatible)
            • NetBird (open-source mesh + Reverse Proxy + OIDC)
            • ZeroTier (Layer-2; bring your own identity)
          Tunnel:
            • Cloudflare Tunnel
          Local-only:
            • LAN-mDNS
            • Localhost-only
          Manual:
            • Bring-your-own reverse proxy
        Each option triggers its substrate-specific auth flow (browser OAuth
          for Tailscale / NetBird / OpenRouter-style; paste API token for CF;
          S-149 challenge configuration for ZT / LAN / localhost).

Step 7 — TLS mode (S-155)
        Three choices:
          • Public CA (recommended; substrate provides LE certs where supported)
          • Local CA (sovereignty mode; trust install ceremony for each device)
          • Both (parallel chains)
        If Local CA selected: wizard generates the QR install ceremony for
          household devices (covered in S-155); each device scans + installs.

Step 8 — LLM providers (S-144)
        OAuth-first: Sign in with Groq, OpenRouter; click-through API token
          page for Cloudflare; paste API key for Cerebras (until provider OAuth ships).
        Or sovereignty: "I'll bring my own local model" / paste-API-key for
          Anthropic / OpenAI / etc.
        All keys flow into the vault (S-141) via secrets.use, never plaintext.

Step 9 — Channels (S-041 / S-103 / etc.)
        Optional. Telegram / voice / email / Obsidian inbox.
        Each channel gets its own substep with provider OAuth or token-paste flow.

Step 10 — Crypto features (S-151) — OPTIONAL, default Skip
        Choices:
          • Skip (default) — no wallet plugin, no chain code paths
          • Lightning only (medley install lightning + faucet onboarding S-151)
          • Bitcoin + Lightning (medley install bitcoin lightning electrum-server)
          • Bring my own (connect to existing LN / Bitcoin node)
        If Lightning chosen: faucet onboarding sub-wizard (faucet / BYO invoice /
          BYO node / skip-and-fund-later) per S-151.

Step 11 — Smoke tests (the install-time security audit)
        The wizard runs five smoke tests in real time, displaying pass/fail:
          ✓ Bouncer rejects a known prompt-injection payload
          ✓ CONVERSATION role has the empty tool list (capability envelope works)
          ✓ Vault round-trip: secrets.use callback returns expected result
          ✓ Audit-log VC produced for the install ceremony itself, signed by m/0'
          ✓ Substrate reachability: dashboard reachable at the configured URL
        These are baseline assertions the operator can re-run later ("the install-
          time guarantees still hold").

Step 12 — Finalize
        Wizard summary page:
          - Conductor name, instance ID, DID
          - Substrate URL, TLS mode
          - Configured users, configured channels, configured LLM providers
          - Crypto status, federation status
          - "Open the Console" button → redirects browser to substrate URL
        Temporary localhost server shuts down.
        Conductor restarts on the substrate-bound listener.
        Browser tab redirects automatically when the new endpoint is up.
```

### Browser-first, CLI fallback

```
# Browser path (default)
curl install.sh | sh
  → conductor binds 127.0.0.1:9999
  → attempts xdg-open / open / start (Linux/macOS/Windows)
  → success: browser opens automatically
  → failure: prints URL + one-time token, waits for connection

# Explicit CLI path
curl install.sh | sh -s -- --cli
  → conductor runs the wizard in the terminal directly
  → same logic underneath, different presenter
  → hardware-wallet steps prompt for device USB connection in the terminal
  → OAuth steps print URLs the operator opens manually

# Headless / SSH
curl install.sh | sh
  → detects no DISPLAY / no graphical session
  → prints: "Open this URL on a device on the same network:
              http://<host>:9999/setup?token=...
             Or: ssh -L 9999:127.0.0.1:9999 <host>
              and visit http://127.0.0.1:9999/setup?token=... locally"
  → waits for connection, runs browser wizard against the connected client
```

### Resume + idempotency

- Wizard state is checkpointed after each step in `~/.conductor/wizard-state.json` (vault-encrypted once admin keypair is created in Step 3, plaintext before that).
- Closing the browser mid-wizard → reopen the URL, resume from the last completed step.
- Conductor crash mid-wizard → same behavior. Restart `maistro setup` and resume.
- Re-running `maistro setup` on an already-configured conductor: the wizard recognizes existing state and offers "reconfigure" (specific steps) or "start over" (destructive, requires admin signature).

### Shared codebase with Console (S-016)

The wizard PWA and the runtime Console PWA are the same web app. Three modes:

- **Setup mode** — served from temporary localhost during install; only the wizard routes are reachable; no auth required (one-time token in URL).
- **Authenticated Console mode** — served from substrate URL post-install; full dashboard routes; substrate-attested identity (S-153).
- **Recovery mode** — admin-only re-entry (e.g., re-running specific wizard steps); requires admin signature.

All three modes share components, theming, design system, accessibility primitives, and i18n. One codebase, three entry points.

### Sovereignty path through the wizard

For operators who want minimum third-party involvement, the wizard's defaults can all be deselected:

- Substrate: localhost-only or LAN-only (Step 6)
- TLS: local-CA mode (Step 7)
- LLM: "I'll bring my own local model" (Step 8)
- Channels: skip all (Step 9)
- Crypto: skip (Step 10)

Result: a working conductor with zero outbound traffic to any third party. The smoke tests in Step 11 still pass. The same wizard, the same flow.

## Acceptance Criteria

- [ ] Default-everything wizard run completes in <5 minutes browser-first on a fresh Linux laptop with Tailscale already installed (and <10 min on a fresh machine including substrate install)
- [ ] All 12 steps render correctly on Chromium, Firefox, Safari (desktop + mobile-responsive)
- [ ] Step 4 (Create user one) is structurally required — form does not advance without a name; verified by browser automation
- [ ] Step 11 smoke tests run live and display real pass/fail; failures block wizard completion with clear remediation steps
- [ ] Wizard state persists across browser close + reopen + conductor crash
- [ ] CLI fallback (`--cli`) walks the same logical flow with a TUI presenter; verified on a no-display VM
- [ ] Headless install: prints URL + token + ssh-tunnel instructions when no graphical session detected
- [ ] Sovereignty configuration: localhost substrate + local-CA + local model + skip crypto produces a working conductor with zero outbound HTTP verifiable via tcpdump
- [ ] OAuth flows (Tailscale, NetBird, Groq, OpenRouter) complete in-browser without leaving the Console
- [ ] Hardware-wallet path (Ledger / Trezor) connected at Step 2 completes without falling back to software seed
- [ ] After wizard completion, browser auto-redirects to the substrate URL (no manual navigation required)
- [ ] Re-running `maistro setup` on a configured conductor offers reconfigure (specific steps) or full reset (admin-signed)
- [ ] On Windows: signed `.msi` install + wizard sequence completes without SmartScreen warnings
- [ ] On macOS: signed `.pkg` install (S-147) and `curl install.sh` both produce identical wizard experiences

## Implementation Notes

- **Wizard PWA stack:** same as Console (S-016) — likely TS/React or similar; reuses dashboard components.
- **Backend:** the conductor binary serves the wizard's HTTP endpoint directly during setup; same binary that will later serve the Console. No separate "installer" process.
- **One-time token:** generated at setup-mode start, included in the URL the conductor prints / opens, exchanged for a session cookie on first hit. Token is single-use; subsequent visits to the URL without a valid session cookie are rejected.
- **Browser auto-open:** detect platform; `xdg-open` (Linux), `open` (macOS), `start` (Windows). Failure to open is non-fatal; conductor falls back to printing the URL.
- **Headless detection:** no `DISPLAY` env (Linux), `LaunchServices` query failure (macOS), `SessionId == 0` (Windows Service mode).
- **Hardware-wallet UX in browser:** WebUSB / WebHID for Ledger/Trezor; the connection happens in the user's browser, not the conductor process. Cleaner: the conductor receives the public keys + signed seed via the wizard form, never sees raw HID traffic.
- **OAuth popup:** standard popup window flow with a `postMessage` callback to the wizard tab; same pattern as countless web apps.
- **Validation:** Zod-style schemas client-side and server-side; both validate every wizard input.
- **i18n:** strings localized; English default. Sovereignty audience overlaps significantly with non-English-first users; localization is not a v2 concern.
- **Telemetry default-off:** the wizard explicitly does not phone home about completion / failure. If telemetry is ever added, it's opt-in with a separate spec.
- **Composition with PHILOSOPHY:** the wizard is the operator-facing artifact of the philosophy doc's invariants. Step 4 (user1 mandatory) is the philosophy's invariant #1 in concrete UX form. Step 11 (smoke tests) is the philosophy's claims ("Bouncer rejects injection," "vault is brokered," etc.) validated at install time.

## Verification

- Default-everything install on Linux: `curl install.sh | sh`; complete wizard with Tailscale defaults, free LLM defaults, no crypto; reach working Console at `https://<instance>.<tailnet>.ts.net` in under 5 minutes total.
- Sovereignty install: same machine, deselect every default; localhost substrate + local-CA + local model + skip crypto; verify zero outbound HTTP via tcpdump for 10 minutes after wizard completes.
- Step 4 invariant test: browser automation attempts to advance Step 4 without filling user-name; verify the form refuses; verify no `--skip-user` flag works.
- Headless: SSH into a remote VM with no DISPLAY; run install; verify the printed URL + token + ssh-tunnel instructions; verify wizard completes from the operator's local browser.
- Resume test: kill the wizard browser tab mid-Step 7 (TLS mode); reopen the URL; verify the wizard resumes at Step 7 with previous steps' state intact.
- Crash test: kill `maistro` process during Step 6; restart `maistro setup`; verify the wizard resumes.
- Hardware-wallet test: connect Ledger at Step 2; complete seed-from-device flow; verify conductor never holds raw seed material.
- Smoke-tests test (Step 11): inject a fault in the Bouncer (test mode) so the prompt-injection payload is *not* rejected; verify the wizard reports failure and refuses to complete.
- Cross-browser: complete wizard on Chromium, Firefox, Safari; identical behavior, identical post-install state.
- Re-run test: complete wizard, then run `maistro setup` again; verify reconfigure / reset menu appears and respects admin-signature gate for reset.
- Windows .msi: complete install on a fresh Windows 11 VM; SmartScreen recognizes signature; wizard opens in default browser; conductor runs as Windows Service; ARP / Add-Remove Programs entry exists.
