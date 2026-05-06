---
id: S-148
title: "Optional Podman containerization — rootless filesystem-isolated install"
domain: infra
status: draft
priority: P2
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-148: Optional Podman Containerization

## Problem

The native install (S-147) is hardened with OS-level sandboxing primitives, but some operators want a stronger filesystem boundary:

- Sovereignty operators who want "the conductor cannot see anything outside its declared volumes" as an enforced property, not a hardening directive.
- Operators running multiple Maistro instances on the same host (e.g., a personal one and a household-shared one) who want filesystem isolation between them.
- Operators with existing Podman / Docker workflows who want consistency with their other services.
- Reset-and-restart ergonomics: `podman rm conductor && podman run ...` is faster than reinstalling the OS service.

We should not *require* containerization (it adds friction, particularly for desktop users), but we should support it as a first-class alternative for operators who want it. The native install remains the default; the containerized install is an opt-in via `maistro setup --container`.

## Solution

Ship a Podman-based containerized install path that produces functionally equivalent behavior to S-147 with stronger filesystem isolation. **Rootless by default** (consistent with the philosophy: "no root" applies to the container runtime too).

### Why Podman, not Docker

| Property | Podman | Docker |
|---|---|---|
| Rootless by default | **Yes** | Daemon runs as root; rootless is opt-in |
| Daemonless | **Yes** | Daemon-based, single point of failure |
| License | **Apache-2** | Docker Desktop: paid for orgs >250 employees |
| Cross-platform | Linux native; Mac/Win via Podman Machine | Same (Docker Desktop on Mac/Win) |
| systemd integration | `podman generate systemd` produces a unit | Possible but more friction |

Podman matches our "no root in the runtime that runs your AI" posture. Docker users who already have Docker installed can use it via the `OCI` runtime adapter (Podman's CLI is largely Docker-compatible), but the documented default is Podman.

### Install ceremony

```
maistro setup --container
  → detects existing Podman: yes → use it
                            : no  → prompts to install via the platform's package manager
                                    (apt / dnf / brew / winget)
                                    documented; one shell command
  → pulls the maistro container image (signed via Sigstore + Cosign)
  → verifies image signature against release key
  → generates a Podman quadlet / systemd-managed container unit
  → starts the container (rootless, by default user `conductor`)
  → spawns wizard, opens browser at http://127.0.0.1:9999/setup
```

The rest of the wizard (S-139) is identical; the container is just a different *substrate* for the conductor process.

### Container layout

```
maistro-conductor:vX.Y.Z
  /usr/local/bin/maistro
  /etc/conductor/                   (read-only configs)
  /var/lib/conductor/               (state; bind-mounted from host)
  /var/run/conductor/socket         (Unix socket for CLI / Console comms)
```

Volumes bind-mounted from the host:

- `~/.conductor/` → `/var/lib/conductor/` (state, vault, audit log, sqlite-vec database)
- `~/.config/conductor/` → `/etc/conductor/` read-only (operator-edited config files)

No other host filesystem is visible inside the container. Network is bridged by default (rootless network namespace); the conductor binds `0.0.0.0:9999` *inside* the container, which Podman maps to `127.0.0.1:9999` on the host.

### Substrate integration

The substrate (S-153) runs *outside* the container on the host (Tailscale daemon, Cloudflare Tunnel client, etc.). The container speaks to the host substrate via Podman's `--network=slirp4netns:enable_ipv6=true,allow_host_loopback=true` so it can reach the substrate's localhost endpoint.

Exception: `tailscaled` can run *inside* the container with `--cap-add=NET_ADMIN` for operators who want a fully-isolated networking stack. Documented but not the default — most operators get cleaner behavior with the substrate on the host.

### Image distribution

- Built via reproducible build (S-156... err, mobile-distribution-style; defer the cross-spec ref to a future mobile spec) with deterministic flags.
- Pushed to a public registry (`ghcr.io/blakematthews-dev/maistro-conductor:vX.Y.Z`).
- Signed via Sigstore Cosign; image digest pinned per release.
- Tagged with `latest`, semver versions, and release-channel tags (`stable`, `next`).
- Sovereignty operators can build the image locally from the source repo with `make container` and use the local digest.

### Update path

- `maistro update` in container mode pulls a new image, verifies signature, replaces the container with `podman replace`, restarts. ~5s downtime.
- Container update is also a VC in the audit log.

### CLI access

From the host: `maistro` CLI talks to the container via the Unix socket bind-mounted at `~/.conductor/socket`. Same CLI commands as native install; the operator doesn't notice the container indirection.

### Switching between native and containerized

An operator can switch by:

1. Stopping the existing service (native or container).
2. Backing up `~/.conductor/`.
3. Running `maistro setup --container` (or `maistro setup --native`) to reinstall.
4. The state directory survives intact — same Conductor Seed, same vault, same audit log, same identity.

The Conductor Seed is the source of truth; the substrate and container choice are reversible.

## Acceptance Criteria

- [ ] `maistro setup --container` produces a working rootless-Podman install in <5 min on a host with Podman already present
- [ ] If Podman is absent: wizard offers to install via the platform's package manager and waits for user confirmation
- [ ] Container image is signed via Cosign; install fails clearly on signature mismatch
- [ ] Container runs rootless; verified by `podman info` showing UID mapping
- [ ] State directory (`~/.conductor/`) persists across container recreates; verified by `podman rm` + `podman run` cycle preserving Conductor Seed and audit log
- [ ] CLI from host (`maistro logs`, `maistro vault list`) works against the containerized conductor via the bind-mounted socket
- [ ] Substrate (Tailscale / NetBird / etc.) runs on the host by default; container reaches it via slirp4netns; tested with each substrate
- [ ] Native↔container migration: state is preserved across the switch; same Conductor Seed reconstitutes identical identity
- [ ] Update flow: `maistro update` in container mode pulls new image, verifies signature, replaces container, restarts; <5s downtime; audit-log VC
- [ ] Sovereignty: operator can build the image locally with `make container`; pin to a local digest
- [ ] Reproducible build: independent rebuild from the same source produces a byte-identical image (modulo build timestamps)

## Implementation Notes

- **Podman quadlet** (`*.container` files) is the recommended mechanism for systemd-managed containers; we generate one at install. Falls back to `podman generate systemd` for older Podman versions.
- **Rootless networking:** slirp4netns is the default; pasta is the modern alternative (Podman 4+). Both work; pasta is preferred when available.
- **Image base:** distroless or scratch + statically-linked Maistro binary keeps the attack surface minimal (~50 MB image vs 200+ MB for distro-based).
- **Build tooling:** Buildah for the image build; `make container` wraps it with sane defaults.
- **macOS / Windows containers:** Podman Machine runs a Linux VM under the hood; container behavior matches Linux.
- **Update without downtime:** for operators who want zero downtime, run two containers in parallel (blue/green) and swap via a substrate-level config change. Documented as an advanced pattern; not the default.
- **GPU passthrough (for local-LLM operators):** documented as an advanced opt-in via `podman run --device nvidia.com/gpu=all` (or AMD ROCm equivalent). Not the default — most operators use cloud-routed LLMs (S-144), not local GPU.

## Verification

- Fresh install with `--container` on Ubuntu without Podman: wizard offers to install via apt; user confirms; install completes in <5 min total.
- Same on a host with Podman already present: install in <2 min.
- Rootless verification: `ps -ef | grep maistro` shows the conductor process running as the unprivileged user, not root.
- State persistence: complete wizard, generate Conductor Seed, run for 1h, `podman rm maistro` + `podman run`, verify same Seed reconstitutes, same audit log present.
- Substrate integration: configure Tailscale on host, verify containerized conductor is reachable at the tailnet hostname; same for NetBird.
- Migration test: install native, run for 1d, switch to container, verify identity preserved (`maistro identity show` returns same DID); reverse.
- Reproducible-build test: two independent CI runs produce containers with identical SHA-256 digests (modulo build timestamp).
