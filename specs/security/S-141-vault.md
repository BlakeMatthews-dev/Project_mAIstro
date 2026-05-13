---
id: SPEC-011
title: "Secrets vault — age-encrypted file unlocked by admin keypair"
repo: Project_mAIstro
kind: spec
status: Proposed
created: 2026-04-25
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# S-141: Secrets Vault

## Problem

The philosophy doc commits us to **"can't leak what it doesn't know"** as a load-bearing claim. Two things have to be true to honor it:

1. The agent never holds credential *values* in its variable scope. The vault is a broker, not a key/value store.
2. The secrets backend must work without external infrastructure. Vaultwarden is the right choice for Agent Stronghold (multitenant, S-023) but is overkill for Agent Conductor's single-host / household scale.

We need a secrets backend that is sovereign, works headless, has no external services, and reuses the Conductor Seed (S-149) as its root of trust so the operator manages one ceremony, not two.

## Solution

**age-encrypted file** at `~/.conductor/secrets.age`, unlocked at startup by the admin keypair derived from the Conductor Seed. Vault API is `secrets.use(name, callback)` exclusively — there is no `secrets.get`.

### Backend (storage layer)

```
~/.conductor/
  secrets.age          # all credentials, encrypted to admin's m/0' public key
  admin.pub            # cleartext public key (verifies vault belongs to this admin)
  (admin private key) → OS keychain (libsecret / macOS Keychain / Windows CredMan)
                        passphrase-encrypted file fallback for headless Linux
```

Startup flow:

1. Read `admin.pub`.
2. Ask OS keychain for admin private key (or prompt for passphrase to unlock the encrypted private-key file on headless).
3. age-decrypt `secrets.age` into a process-local in-memory map.
4. Zero the private key from process memory immediately after decryption.
5. Serve `secrets.use(name, callback)` calls from the in-memory map.
6. On any signal that the process is dying (SIGTERM, panic), the in-memory map is zeroed before exit.

The vault's *file* is encrypted at rest. The vault's *runtime state* is in process memory only — never written to swap (mlock the pages on Linux/macOS), never written to disk, never logged.

### API (broker, not get/set)

```python
# Right — vault brokers; agent never sees the value
response = secrets.use("openai_api_key", lambda key: openai.call(prompt, key))
# `key` lives only inside the lambda's scope; zeroed after return.
# `response` is whatever the callback returned (an LLM response, an HTTP result, etc.)
# The credential value never enters the agent's variable scope.

# Wrong — not implemented; would violate the claim
# secrets.get("openai_api_key")  # this function does not exist
```

Rule: the conductor codebase does not contain a `secrets.get` symbol anywhere. Code review enforces this; CI greps for the substring and fails the build if found outside test fixtures.

### Why age and not something else

| Option | Verdict |
|---|---|
| **age + admin keypair** *(this spec)* | Single binary (~3MB), cross-platform, headless-OK, reuses S-149 keypair, file-based so git-friendly for change history (encrypted blobs in git is fine), trivial migration to Vaultwarden later. **Picked.** |
| OS keychain *as the vault itself* (libsecret / Keychain / CredMan via `keyring`) | Works on desktops, **breaks on headless Linux servers** (no D-Bus session). Disqualifies as the cross-platform default. Used here for *one thing* only: storing the admin private key that unlocks `secrets.age`. |
| Vaultwarden | Separate service. Belongs in Agent Stronghold. |
| Bitwarden CLI | Belongs in Stronghold. |
| HashiCorp Vault | Same — separate service, multitenant-shaped. |
| SOPS | Solid alternative; uses age under the hood. We use age directly so we control the key derivation. |

### Credential backup

The Conductor Seed restores the vault's *encryption key* but not the credential *values*. If `secrets.age` is lost (disk failure, accidental deletion), the operator must re-enter every credential manually. This is the trade-off of a sovereign vault: no third party holds a backup copy.

Three options, surfaced by the wizard at setup time:

**Option A: Encrypted file backup (recommended)** — `maistro vault export --encrypted > secrets.age.bak`. The export is itself age-encrypted to the same admin key. Store on a second device, a USB drive, or any untrusted medium — the file is encrypted and safe to store anywhere. This is the recommended default.

**Option B: Print credential cards** — `maistro vault export --print`. Each credential prints as a labeled QR code on a single page. Store with the recovery card from S-149. High-friction but fully sovereign and offline.

**Option C: No backup (explicitly acknowledged)** — Wizard prompts: *"Have you backed up your vault? Without a backup, losing `secrets.age` means re-entering all your API keys manually."* Operator must explicitly confirm to skip.

Vault backups are not automatically synced anywhere. The operator is responsible for storing the backup file in a safe location separate from the conductor host.

Import: `maistro vault import secrets.age.bak` — decrypts using the current admin key; merges into the running vault. Add-only: existing entries are not overwritten. Conflicts are shown for manual resolution.

### Bouncer integration (final-line defense)

The Bouncer (S-022) gets a special pattern set computed at startup: the first 8 bytes (64 bits) of the SHA-256 hash of every credential value in the vault. Any agent output containing a string whose SHA-256 prefix matches any pattern is rejected with `SAFETY_VIOLATION` before reaching the user or being logged.

The 8-byte prefix length is chosen to minimize false positives (collision probability ~1 in 10^19 per random 8-byte string) while ensuring the pattern set itself contains no recoverable credential material.

This is the final-line defense if a credential somehow slipped through `use()` — e.g., via an upstream library that logs raw HTTP request bodies. The Bouncer catches it before the value escapes the conductor's process boundary.

The pattern set is regenerated whenever the vault changes. Pattern values themselves are *also* in the vault (encrypted at rest) so the Bouncer's pattern file isn't a credential leak surface.

### Adding / rotating / removing secrets

```
maistro vault add <name>           # prompts for value via TTY (no echo); never via argv
maistro vault rotate <name>        # provides new value; old kept for rollback grace period
maistro vault remove <name>        # tombstoned; actually deleted on next vault rebuild
maistro vault list                 # names only, never values
maistro vault rebuild              # re-encrypts the vault from scratch (compaction + key rotation)
maistro vault export --encrypted   # produces age-encrypted backup file
maistro vault import <backup>      # merges backup into running vault (add-only)
```

All vault mutations require admin signature (S-142) and are recorded as VCs in the audit log (S-152).

## Acceptance Criteria

- [ ] `secrets.use(name, callback)` is the ONLY public API; `secrets.get` does not exist anywhere in the codebase
- [ ] CI grep for `secrets.get` outside test fixtures fails the build
- [ ] Vault file `secrets.age` is encrypted to the admin's `m/0'` public key from S-149
- [ ] Admin private key is held in OS keychain on desktop, passphrase-encrypted file on headless Linux; never on disk in cleartext
- [ ] At startup, vault is decrypted into mlock'd process memory; private key zeroed after decryption; in-memory state zeroed on process death
- [ ] Vault unavailability at startup: if the admin private key cannot be retrieved from the OS keychain AND the passphrase-encrypted fallback file is absent or fails to decrypt, conductor refuses to start with a `VAULT_UNAVAILABLE` error and clear recovery instructions (`maistro vault recover`); conductor never starts with an empty or partial vault — fail-closed is the only acceptable behavior
- [ ] Bouncer rejects agent output containing any vault-credential prefix (final-line defense); the match pattern is the first 8 bytes (64 bits) of the SHA-256 hash of each credential value; prefix length is fixed and documented in the Bouncer implementation
- [ ] Bouncer pattern set is regenerated within 100ms of any vault mutation (add, rotate, remove, rebuild)
- [ ] Restoring the seed on a new machine reconstitutes the vault encryption key; importing a backup file restores credential values
- [ ] Vault rebuild rotates the encryption key (advances the age recipient), zero-downtime to the running conductor
- [ ] All vault mutations are admin-signed and recorded as VCs in the audit log
- [ ] No credential value is ever in a Langfuse trace, log line, or panic stack
- [ ] `maistro vault export --encrypted` produces an age-encrypted file importable on a fresh install with the same seed
- [ ] `maistro vault import <backup>` merges credentials without overwriting existing entries; conflicts surfaced for manual resolution
- [ ] Setup wizard asks about vault backup; operator must explicitly acknowledge "no backup" to skip
- [ ] Export file never contains plaintext credential values; it is encrypted to admin's `m/0'` key

## Implementation Notes

- **age library:** use the Rust `age` crate or Go `filippo.io/age`. Both stable, both small.
- **OS keychain:** use Rust `keyring-rs` or Python `keyring` library; abstracts macOS Keychain / libsecret / Windows CredMan.
- **Headless Linux:** when no D-Bus session is detected, fall back to a passphrase-encrypted private-key file (`~/.conductor/admin.priv.age`). Wizard prompts for passphrase at every conductor start. Documented as the headless trade-off.
- **mlock:** lock the in-memory vault pages so they cannot be swapped to disk. `mlock(2)` on Linux/macOS, `VirtualLock` on Windows.
- **Memory zeroization:** use `zeroize` crate (Rust) or equivalent. Avoid Python's GC for credentials — the vault implementation is in Rust or a sandboxed FFI module.
- **Tombstoning vs. delete:** `remove` marks the entry as tombstoned in the vault metadata; the actual encrypted bytes are removed on next `rebuild`. This gives a rollback window without indefinitely retaining old credentials.
- **Rotation grace period:** rotated credentials retain the old value for 24h tagged as `<name>.previous`; agents can opt in to fallback by passing a flag to `use`. Default: rotation is hard cutover.
- **Composes with S-149:** the admin keypair is `m/0'` from the Conductor Seed. Lose the seed, lose the vault key. Restore the seed, restore the vault key. Lose `secrets.age` without a backup, lose the values. One backup ceremony covers the key; a second covers the values.
- **Export encryption:** `maistro vault export --encrypted` re-encrypts to the same age recipient (admin's `m/0'` public key). The backup file is safe to store on untrusted media.
- **Startup failure behavior:** vault unlock is attempted exactly once at startup. On failure, conductor logs `VAULT_UNAVAILABLE` with the specific cause (keychain error, passphrase decryption error, `secrets.age` not found) and exits. It does not retry, does not start in degraded mode, and does not serve requests. `maistro vault recover` provides a guided recovery flow.

## Verification

- Add a credential via `maistro vault add openai_api_key`; restart conductor; verify `secrets.use("openai_api_key", ...)` works.
- Wipe the host; restore from BIP39 phrase; import vault backup; verify all credentials present and `secrets.use()` works.
- Export vault; corrupt `secrets.age`; import from backup; verify recovery succeeds.
- Attempt import with a backup encrypted to a different admin key; verify import is rejected with a clear error.
- Code coverage check: `secrets.get` is not invoked by any production code path (CI gate).
- Memory test: capture process memory after a `use()` call returns; verify the credential value is not present.
- Bouncer test: configure a fake credential containing a known marker string; have an agent prompt-injection attempt to print the marker; verify the Bouncer rejects the output.
- Headless test: set up a Linux server with no D-Bus session; verify the passphrase-fallback mode works end-to-end.
- Rotation test: rotate `openai_api_key`; verify old value is unavailable after grace period; verify VC for the rotation is in the audit log.
- Setup wizard test: attempt to skip vault backup step without explicitly acknowledging; verify wizard does not advance.
- Vault-unavailable test: with conductor stopped, delete the OS keychain entry and the passphrase fallback file; attempt to start conductor; verify process exits with `VAULT_UNAVAILABLE` error and recovery instructions; verify no requests were served and no partial vault state exists.
- Bouncer prefix test: add a credential with value `sk-test-ABCDEF0000`; craft a prompt-injection that outputs the full value; verify Bouncer blocks it. Craft a prompt that outputs only 7 characters of the value; verify whether Bouncer blocks at the configured prefix length (8 bytes) — output must not include the full credential regardless.
