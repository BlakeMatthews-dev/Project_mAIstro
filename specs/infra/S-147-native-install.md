---
id: S-147
title: "Hardened native install — systemd / launchd / Windows signed .msi"
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

# S-147: Hardened Native Install

## Problem

Agent Conductor's positioning is *"five-minute install on a fresh machine, browser-first."* The default install path must:

- Work on Linux, macOS, and Windows.
- Run as a managed service so it survives reboots and supervises itself.
- Apply OS-level sandboxing primitives to limit the conductor's blast radius (philosophy doc: the agent doesn't run as root).
- Use platform-native distribution mechanisms (signed binaries, code-signing chains the OS already trusts) so users don't get "untrusted developer" warnings.
- Not require any prerequisite software (Docker, Tailscale, Bitcoin Core, etc. — those are opt-ins, not preconditions).

The install ceremony for desktop users:

```
curl install.sh | sh   (Linux / macOS)
or
maistro-setup.msi      (Windows, signed)
  → conductor binary installed as a service
  → spawns localhost:9999 wizard
  → opens browser to http://127.0.0.1:9999/setup
  → user completes wizard in browser
  → conductor reconfigures, restarts at substrate URL
  → done in ~5 minutes
```

Zero terminal interaction for desktop users. Power users always have a CLI fallback.

## Solution

Three per-platform install paths, each producing a hardened service running as a low-privilege user with OS-level sandboxing applied. Containerization (S-148) is offered as an opt-in alternative; this spec covers the *native* default.

### Linux — systemd unit with hardening directives

`curl -fsSL maistro.dev/install.sh | sh` does:

1. Detects platform + arch (`amd64`, `arm64`).
2. Downloads conductor binary + `.sig` (Sigstore-signed by the project release key).
3. Verifies signature against a public key fetched from `https://maistro.dev/keys/release.pub` over TLS, with the key's fingerprint also pinned in the install script.
4. Creates a system user `conductor` (`/usr/sbin/nologin`, no home directory contents shared with humans).
5. Installs binary to `/usr/local/bin/maistro`.
6. Installs systemd unit to `/etc/systemd/system/maistro.service`:

```ini
[Unit]
Description=Agent Conductor
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=conductor
Group=conductor
ExecStart=/usr/local/bin/maistro run
Restart=on-failure
RestartSec=5
WatchdogSec=30

# State directory (under /var/lib/conductor by default)
StateDirectory=conductor
StateDirectoryMode=0700

# Hardening
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectKernelLogs=true
ProtectProc=invisible
ProcSubset=pid
LockPersonality=true
MemoryDenyWriteExecute=true
NoNewPrivileges=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources
CapabilityBoundingSet=
AmbientCapabilities=

# Resource caps
MemoryMax=4G
TasksMax=512

[Install]
WantedBy=multi-user.target
```

7. Starts the service (`systemctl start maistro`).
8. Spawns the localhost wizard endpoint (`127.0.0.1:9999`), opens the browser at it (or, if headless, prints the URL + token).
9. After wizard completion, the conductor restarts on the configured substrate (S-153).

### macOS — launchd plist + sandbox-exec, optional signed .pkg

Default: `curl -fsSL maistro.dev/install.sh | sh` does the equivalent on macOS:

- Verifies binary signature (Apple notarization + Sigstore) against the release key.
- Installs to `/usr/local/bin/maistro` (Homebrew Cellar if Homebrew is present).
- Creates `_conductor` system user (UID < 500, no shell).
- Installs launchd plist to `/Library/LaunchDaemons/dev.maistro.conductor.plist`.
- Wraps the conductor invocation in `sandbox-exec` with a profile restricting filesystem access to the state directory + writes to `/var/log/conductor/` only.
- Loads + starts the LaunchDaemon (`launchctl bootstrap system`).
- Spawns wizard, opens browser.

**Optional signed `.pkg` installer** for users who prefer a GUI install ("is curl-pipe-to-shell safe?"). Same outcome, packaged with macOS's Installer.app, double-clickable, signed + notarized. Distributed via maistro.dev/download or Homebrew cask.

### Windows — signed .msi installer

Windows is the platform where curl-pipe-to-shell ergonomics break down. The default Windows install is a **signed .msi installer** distributed from maistro.dev/download:

1. User downloads `maistro-setup-vX.Y.Z.msi`.
2. Installer is Authenticode-signed by the project release key; SmartScreen recognizes it.
3. Double-click → standard MSI install dialog.
4. Installs binary to `C:\Program Files\Maistro\maistro.exe`.
5. Creates a low-privilege service user `MaistroService`.
6. Registers a Windows Service running as that user with restricted token (no admin, no SeDebugPrivilege, etc.).
7. Configures Windows Firewall: inbound localhost only by default; outbound permitted.
8. Spawns wizard at `127.0.0.1:9999`, opens default browser.

MSI install path also produces an entry in Add/Remove Programs for clean uninstall. `winget install Maistro.AgentConductor` works as an alternative once the package is published.

### CLI fallback (all platforms)

Every install path supports `--cli` to skip the browser auto-open:

```
curl install.sh | sh -s -- --cli      # Linux / macOS
maistro-setup.msi /qn /CLI=1          # Windows quiet install
```

The wizard runs in the terminal in this mode (S-139). Same logic underneath; different presenter. For headless / SSH / paranoid setups.

### Update channel

Updates flow via the same signed-binary mechanism:

- `maistro update` checks the release endpoint, verifies signature, atomically swaps the binary, restarts the service.
- Updates can be paused (`maistro update --pause`) or pinned to a version (`maistro update --pin v1.2.0`).
- Updates are themselves signed; every update is recorded in the audit log as a VC.
- Sovereignty operators can bring their own update mirror (`MAISTRO_UPDATE_URL`) and pin a different release key.

### What this spec does NOT do

- It does not handle containerized deployment — see S-148.
- It does not bundle a substrate (Tailscale, Bitcoin Core, etc.). Substrates are opt-ins via the wizard.
- It does not handle multitenant / multi-host deploy — that's Agent Stronghold territory.
- It does not enable network exposure by default — the conductor binds localhost-only until the wizard configures a substrate (S-153).

## Acceptance Criteria

- [ ] Linux: `curl install.sh | sh` produces a hardened systemd-managed conductor in <5 min on Ubuntu, Debian, Fedora, Arch
- [ ] macOS: `curl install.sh | sh` AND `.pkg` double-click both produce a launchd-managed conductor with sandbox-exec profile
- [ ] Windows: signed `.msi` produces a Service running as low-privilege user with Firewall scoped to localhost
- [ ] All platforms: binary signature verified before install; install fails clearly on signature mismatch
- [ ] All platforms: conductor cannot escalate privileges; verified by attempting `chmod` on `/usr/local/bin/maistro` from inside the service — must fail
- [ ] Resource limits applied (4 GB RAM cap default); conductor process visible to operator via standard tools (`systemctl status`, `launchctl list`, Services.msc)
- [ ] Wizard auto-opens browser on desktop; CLI fallback works headless
- [ ] `maistro update` flows: detect new release → verify signature → atomic swap → restart → audit-log VC
- [ ] Uninstall is clean: `apt remove maistro` / `brew uninstall maistro` / Add/Remove Programs leaves no orphan files outside `~/.conductor/` (which is operator-managed)
- [ ] Sovereignty: operator can configure their own update mirror + signing key without source changes

## Implementation Notes

- **Release signing:** Sigstore (cosign) for transparency-logged signatures, optionally backed by a YubiKey-stored key for the release operator. Apple notarization for macOS.
- **MSI tooling:** WiX or Advanced Installer; signed with an EV code-signing certificate to satisfy SmartScreen instantly.
- **systemd unit:** the hardening directives above are the strict default. Operators can soften specific ones via `~/.conductor/systemd-overrides.conf` (loaded as a drop-in); audit log records any softening.
- **launchd plist:** uses `LimitLoadToSessionType Background` and `RunAtLoad true`; writes log to `/var/log/conductor/maistro.log`.
- **Windows Service:** uses `sc.exe` flags equivalent to systemd's `User=` and `NoNewPrivileges=true` via the restricted-token feature.
- **Browser open:** `xdg-open` (Linux), `open` (macOS), `start` (Windows). Falls back to printing the URL on headless.
- **Wizard handoff:** the temporary localhost server and the long-running substrate-bound server are the same conductor process. The wizard step that finalizes substrate configuration triggers an internal restart that re-binds the listener; the browser tab refreshes onto the new URL.
- **Atomic update swap:** Linux/macOS use `rename(2)` of the binary + `systemctl reload-or-restart`. Windows uses Service-Stop → file replace → Service-Start; takes ~2s.

## Verification

- Linux fresh-install test: Ubuntu 24.04 LTS VM, 2 CPU / 4 GB RAM, no prior software; run `curl install.sh | sh`; verify wizard opens in browser within 60s; complete wizard with Tailscale defaults; conductor reachable on tailnet within 5 min total.
- macOS fresh-install test: same on a fresh macOS 14 install; both `.pkg` and `curl` paths.
- Windows fresh-install test: `.msi` on Windows 11; SmartScreen recognizes signature; wizard opens in default browser.
- Hardening test: from inside the conductor service, attempt `mount`, `mknod`, `chmod` on `/usr/local/bin/maistro`, raw socket creation; all must fail with `EPERM`.
- Resource-cap test: induce a memory-leaking handler; verify systemd kills the service at MemoryMax; restart succeeds.
- Update test: trigger `maistro update`; verify atomic swap, no dropped requests, audit-log VC for the version change.
- Uninstall test: full uninstall on each platform; verify no orphan systemd unit / launchd plist / Service registration / firewall rule.
