---
id: S-111
title: "Medley full — publish, versions, signed VC trust chain, dependency resolution"
domain: tools
status: draft
priority: P2
effort: "~300 lines"
created: 2026-03-23
completed: ""
owner: conductor
commits: []
supersedes: "S-037 (extends Medley basics)"
---

# S-111: Medley full

## Problem

S-037 (Medley basics) supports search / install / uninstall. It lacks four things that turn a marketplace into infrastructure:

- **Publishing** — there's no flow for an external author to upload a plugin
- **Versioning** — there's no semver pinning, no upgrade path, no compatibility metadata
- **Dependency resolution** — `depends_on` between plugins is not resolved transitively
- **Trust chain** — there's no cryptographic anchor for "who issued this plugin"

Without these, Medley can't grow beyond ad-hoc single-author skills.

## Solution

Four capabilities, each composing on existing primitives:

### 1. `medley publish` flow

```
medley publish ./my-plugin/
  → Reads manifest.toml
  → Computes content hash
  → Issues a publisher VC (S-152) signed by the publisher's DID
  → Uploads tarball + manifest + VC to the configured Medley registry
  → Updates the publisher's DID document with the new plugin reference
```

The publisher VC asserts: *"did:web:lightning-labs.com publishes plugin `lightning` version 1.2.0 with content hash <sha256>, valid until 2027-04-25."* Verifiers fetching the plugin can resolve the publisher's DID, fetch the public key, verify the VC, and confirm the content hash matches.

### 2. Semantic version pinning

Installed plugins record a semver range in `~/.conductor/medley/lockfile.toml`:

```toml
[lightning]
version_range = "^1.2.0"
installed_version = "1.2.3"
publisher_did = "did:web:lightning-labs.com"
vc_fingerprint = "<sha256>"
```

`medley update` honors the range; major-version updates require explicit `medley update lightning --major`.

### 3. Dependency resolution

Manifest declares:

```toml
[depends_on]
bitcoin = "^2.0.0"
electrum-server = "^1.0.0"
```

Resolver computes the transitive closure at install time and reports conflicts with a structured error (`bitcoin@^2.0.0` conflicts with already-installed `bitcoin@^1.5.0`). Operator can override or pick a version.

### 4. Verifiable trust chain

Every install verifies:

1. Publisher's DID resolves successfully
2. VC signature validates against the DID's public key
3. VC is not in the publisher's revocation list
4. Plugin content hash matches the VC claim
5. Plugin version is in the publisher's claimed-version-range

A failure at any step blocks the install. Unsigned plugins require explicit `medley install --allow-unsigned <name>` *plus* an admin signature (S-142).

Revoked publisher VCs propagate via the publisher's DID document; conductors check on each install attempt and can be configured to re-check daily for already-installed plugins.

## Acceptance Criteria

- [ ] `medley publish` produces a signed publisher VC + uploads plugin tarball + updates publisher DID document
- [ ] Installed plugins pin to a semver range; `medley update` respects the range
- [ ] `depends_on` plugins auto-installed transitively; conflicts reported clearly
- [ ] Every install verifies the publisher VC against the DID document (signature + hash + revocation status)
- [ ] Unsigned plugin install blocked unless `--allow-unsigned` + admin signature
- [ ] Revoked publisher VC blocks future installs; periodic re-check flags compromised already-installed plugins
- [ ] `medley info <name>` displays publisher DID, VC fingerprint, content hash, install date, version, trust tier
- [ ] Lockfile is operator-readable + version-controlled (sovereignty: operator can audit what's pinned)

## Implementation Notes

- **Registry transport:** the registry is itself a Medley plugin (`medley install medley-registry`); operator chooses a registry endpoint (community-hosted, self-hosted, or DID-resolved).
- **VC schema:** uses S-152's plugin-publisher VC type. JSON-LD or JWT-VC; both supported at install verifier.
- **Content hashing:** SHA-256 of the plugin tarball; published in the VC.
- **Revocation propagation:** publisher's DID document carries a `revokedPlugins` list; install verifier consults it. Self-revocation by the publisher requires their DID's signing key.
- **Default registry:** ships with one community-curated registry pinned by content hash; operator can swap for any registry that speaks the protocol.
