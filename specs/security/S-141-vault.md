---
id: S-141
title: "Secrets vault — age-encrypted file unlocked by admin keypair"
domain: security
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
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

### Bouncer integration (final-line defense)

The Bouncer (S-022) gets a special pattern set computed at startup: SHA-256 prefixes of every credential value in the vault. Any agent output containing one of those prefixes is rejected with `SAFETY_VIOLATION` before reaching the user or being logged.

This is the final-line defense if a credential somehow slipped through `use()` — e.g., via an upstream library that logs raw HTTP request bodies. The Bouncer catches it before the value escapes the conductor's process boundary.

The pattern set is regenerated whenever the vault changes. Pattern values themselves are *also* in the vault (encrypted at rest) so the Bouncer's pattern file isn't a credential leak surface.

### Adding / rotating / removing secrets

```
maistro vault add <name>           # prompts for value via TTY (no echo); never via argv
maistro vault rotate <name>        # provides new value; old kept for rollback grace period
maistro vault remove <name>        # tombstoned; actually deleted on next vault rebuild
maistro vault list                 # names only, never values
maistro vault rebuild              # re-encrypts the vault from scratch (compaction + key rotation)
```

All vault mutations require admin signature (S-142) and are recorded as VCs in the audit log (S-152).

## Acceptance Criteria

- [ ] `secrets.use(name, callback)` is the ONLY public API; `secrets.get` does not exist anywhere in the codebase
- [ ] CI grep for `secrets.get` outside test fixtures fails the build
- [ ] Vault file `secrets.age` is encrypted to the admin's `m/0'` public key from S-149
- [ ] Admin private key is held in OS keychain on desktop, passphrase-encrypted file on headless Linux; never on disk in cleartext
- [ ] At startup, vault is decrypted into mlock'd process memory; private key zeroed after decryption; in-memory state zeroed on process death
- [ ] Bouncer rejects agent output containing any vault-credential prefix (final-line defense)
- [ ] Restoring the seed on a new machine reconstitutes the vault identically; trust install ceremony for the OS keychain on the new machine restores access
- [ ] Vault rebuild rotates the encryption key (advances the age recipient), zero-downtime to the running conductor
- [ ] All vault mutations are admin-signed and recorded as VCs in the audit log
- [ ] No credential value is ever in a Langfuse trace, log line, or panic stack

## Implementation Notes

- **age library:** use the Rust `age` crate or Go `filippo.io/age`. Both stable, both small.
- **OS keychain:** use Rust `keyring-rs` or Python `keyring` library; abstracts macOS Keychain / libsecret / Windows CredMan.
- **Headless Linux:** when no D-Bus session is detected, fall back to a passphrase-encrypted private-key file (`~/.conductor/admin.priv.age`). Wizard prompts for passphrase at every conductor start. Documented as the headless trade-off.
- **mlock:** lock the in-memory vault pages so they cannot be swapped to disk. `mlock(2)` on Linux/macOS, `VirtualLock` on Windows.
- **Memory zeroization:** use `zeroize` crate (Rust) or equivalent. Avoid Python's GC for credentials — the vault implementation is in Rust or a sandboxed FFI module.
- **Tombstoning vs. delete:** `remove` marks the entry as tombstoned in the vault metadata; the actual encrypted bytes are removed on next `rebuild`. This gives a rollback window without indefinitely retaining old credentials.
- **Rotation grace period:** rotated credentials retain the old value for 24h tagged as `<name>.previous`; agents can opt in to fallback by passing a flag to `use`. Default: rotation is hard cutover.
- **Composes with S-149:** the admin keypair is `m/0'` from the Conductor Seed. Lose the seed, lose the vault. Restore the seed, restore the vault. One backup ceremony.

## Verification

- Add a credential via `maistro vault add openai_api_key`; restart conductor; verify `secrets.use("openai_api_key", ...)` works.
- Wipe the host; restore from BIP39 phrase; verify the vault decrypts identically.
- Code coverage check: `secrets.get` is not invoked by any production code path (CI gate).
- Memory test: capture process memory after a `use()` call returns; verify the credential value is not present.
- Bouncer test: configure a fake credential containing a known marker string; have an agent prompt-injection attempt to print the marker; verify the Bouncer rejects the output.
- Headless test: set up a Linux server with no D-Bus session; verify the passphrase-fallback mode works end-to-end.
- Rotation test: rotate `openai_api_key`; verify old value is unavailable after grace period; verify VC for the rotation is in the audit log.
