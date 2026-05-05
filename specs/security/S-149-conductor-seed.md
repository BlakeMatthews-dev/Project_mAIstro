---
id: S-149
title: "Conductor Seed — BIP39/BIP32 HD root of trust"
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

# S-149: Conductor Seed

## Problem

The conductor needs a single root of trust spanning multiple uses:

- Signing immutable `AgentSpec` envelopes (S-002, S-005)
- Signing audit-log entries (S-033 memory evolution; future audit-log spec)
- Signing HITL elevation approvals (S-142)
- Future on-chain identity (DID-style; cross-instance trust per S-114, S-115)
- Wallet keys for crypto Medley plugins (S-151)

A generic Ed25519 keypair handles the first three but does not extend to wallets. Generating separate keys per use creates multiple backup ceremonies, multiple recovery surfaces, and no unified provenance story. Operators won't manage multiple seeds correctly; they'll back up one and forget the others.

## Solution

Adopt **BIP39 (24-word mnemonic) + BIP32 (hierarchical-deterministic derivation)** as the root. One seed phrase backs up everything the conductor will ever sign or hold. Domain separation is achieved via standard derivation paths.

### Derivation tree

```
Conductor Seed (24 words, BIP39)
│
├── m/0'      →  AgentSpec / audit-log / elevation signing
│                (BIP32-Ed25519, SLIP-0010)
│
├── m/44'/0'/0'    →  Bitcoin cold wallet  (admin signs every tx)
├── m/44'/0'/1'    →  Bitcoin hot wallet   (S-151 spending policy)
│
├── m/44'/60'/0'   →  Ethereum / EVM cold
├── m/44'/60'/1'   →  Ethereum / EVM hot
│
├── m/44'/501'/0'  →  Solana cold
│
└── m/44'/9000'/0' →  Identity / DID anchor (cross-instance trust)
```

Future chains add new BIP44 coin-type paths without changing the seed. The signing path (`m/0'`) is independent of wallet paths so a non-crypto deployment never derives wallet material.

### Naming

In user-facing copy: **"Conductor Seed."** Wizard step 2 reads:

> *"Step 2: Generate your Conductor's seed phrase. Write down these 24 words. They are your conductor's identity, your wallet, and your root of trust. Anyone who has them can become your conductor."*

### Storage at rest

- Private seed material: encrypted file unlocked by an OS-keychain-stored unlock key, OR generated/held by a hardware wallet (S-150).
- Public key for `m/0'`: cleartext at `~/.conductor/admin.pub`.
- Seed phrase **never written to disk in cleartext** after the wizard.
- Process memory: derived private keys are zeroed after each signing operation; the seed itself is held only briefly during derivation and zeroed immediately.

### Recovery card

The wizard offers to print a one-page recovery card containing:

- The 24 words in a 6×4 grid
- A QR code of the `m/0'` public key (verifies the card belongs to the right instance)
- Instance name (from S-139 step 1) and generation date
- Warning text: *"This card recovers admin access to your conductor and any wallets it controls. Store it like a passport. Never photograph it."*

Print targets: PDF, system print dialog, or copy-paste plaintext fallback.

### Optional: SLIP39 Shamir backup

For high-value or contested deployments, the wizard offers SLIP39 (Trezor's Shamir-shared mnemonic standard) instead of plain BIP39:

- Default offered scheme: 3-of-5
- Each shard is its own recovery card; printable separately
- Use case: shard with lawyer + shard in safe + shards with trusted family members
- Reconstruction requires any 3 shards; fewer than 3 reveal nothing

## Acceptance Criteria

- [ ] Wizard generates a 24-word phrase using the canonical BIP39 English wordlist
- [ ] Phrase is displayed once with an explicit "I have written these down" gate before continuing
- [ ] Public key for every documented derivation path is reproducible across reboots and reinstalls from the same seed
- [ ] Private seed material is never written to disk in cleartext after the wizard exits
- [ ] Lost-seed recovery test: install on a fresh machine, restore from 24 words, verify identical public keys at every path
- [ ] SLIP39 variant: 3-of-5 shards reconstruct the seed; 2 shards reveal no information
- [ ] Recovery card prints to PDF and direct printer; QR scans cleanly to the public key
- [ ] `m/0'` signing path produces stable Ed25519 signatures consumable by AgentSpec / audit verifiers
- [ ] Hardware-wallet path (S-150) is offered as an alternative to software seed in the same wizard step
- [ ] Memory-zeroization verified by the test suite: no reachable string equal to the seed phrase or any derived private key after a signing operation completes

## Implementation Notes

- BIP39 wordlist: stable English wordlist (2048 words). Don't customize.
- BIP32 derivation: standard secp256k1 paths for chains; SLIP-0010 for Ed25519 paths (BIP32 was originally secp256k1-only).
- Libraries: `bip39` + `bitcoin` crates (Rust) or `bip-utils` (Python). Rust preferred for the conductor binary.
- OS-keychain unlock-key storage uses the same backend as S-141.
- The wizard step is part of S-139 setup flow but the cryptographic primitive is owned by this spec.
- For headless Linux servers without a keychain daemon, the unlock key is held in a passphrase-encrypted file with `chmod 600`; passphrase prompted at conductor startup.

## Verification

- Generate seed; record `m/0'` public key.
- Reboot host; verify same public key derived.
- Wipe `~/.conductor/`; reinstall; restore from 24 words; verify same public keys at all paths.
- Generate SLIP39; reconstruct from 3-of-5 shards; verify identical seed.
- Test that `cat /proc/<pid>/mem` (or equivalent on macOS) does not contain the seed phrase after a signing operation has completed.
