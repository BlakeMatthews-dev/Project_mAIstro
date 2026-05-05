---
id: S-150
title: "Hardware signing devices — Ledger / Trezor / YubiKey / mobile"
domain: security
status: draft
priority: P2
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
---

# S-150: Hardware Signing Devices

## Problem

The Conductor Seed (S-149) is encrypted at rest, but is decrypted into process memory during signing operations. For high-value deployments, or for operators who already keep keys on dedicated hardware, the seed should never enter the conductor process at all. Hardware-wallet integration is also the operational path crypto-native users expect by default — they will not adopt a system that wants their seed in software.

## Solution

Four integration modes, all selectable in the S-139 setup wizard. Each replaces or augments the seed source from S-149.

### Mode 1: Ledger / Trezor as seed source

- The hardware device generates the BIP39 seed (or imports one the user already holds).
- Conductor never sees private material at any point.
- Signing requests route to the device via WebUSB/HID (desktop) or Bluetooth (Ledger Nano X).
- Every signature shows a structured prompt on the device screen; user confirms with hardware buttons.
- Use case: BIP39 + BIP32 paths (S-149) for both signing and wallets. Highest-trust mode.

### Mode 2: YubiKey HSM (PIV applet)

- YubiKey holds an Ed25519 + secp256k1 keypair in tamper-resistant storage via the PIV applet.
- Not BIP32-HD-derivable: YubiKey does not support hierarchical derivation.
- Suitable for `m/0'`-equivalent operations (AgentSpec / audit / elevation signing) but **not** for wallet operations.
- Operator deployment: keep wallet paths in software (S-149) but route signing-only ops to YubiKey.
- Use case: enterprise deployments where wallet signing is rare but AgentSpec/audit signing is constant.

### Mode 3: Mobile device with hardware-backed keystore

- Admin's phone holds the signing key in iOS Secure Enclave or Android Keystore.
- Conductor sends signed-payload requests to a wallet app (Phoenix, Mutiny, Zeus, Breez — any BIP-322-compatible wallet); admin signs via biometric tap.
- Same signing surface serves Lightning payments (S-151) and HITL elevation requests — see S-151 §“Unified HITL via hot wallet.”
- Use case: the operational default for non-paranoid users; "your phone is your hardware wallet."

### Mode 4: Software seed (S-149 default)

- Documented for completeness. The setup wizard makes this the default with explicit messaging that hardware-backed modes are stronger.

### Setup wizard interaction

Wizard step 2 (S-149) presents:

```
? Conductor Seed source:
  > Generate software seed (default; recommended for first-time users)
    Connect Ledger or Trezor (highest trust; requires device)
    Use YubiKey for signing (no wallet support)
    Configure mobile signing later (recommended after install)
```

Mode 3 (mobile) is intentionally a follow-up step — the install completes with software-or-hardware seed first; the user pairs their phone after the dashboard is up and running.

## Per-Device Support Matrix

| Device | BIP39/BIP32 | Curves | Connectivity | Sign types |
|---|---|---|---|---|
| Ledger Nano S+ | Yes | secp256k1, Ed25519 | USB-C | All |
| Ledger Nano X | Yes | secp256k1, Ed25519 | USB-C, Bluetooth | All |
| Trezor Model T | Yes | secp256k1, Ed25519 | USB-C | All |
| Trezor Safe 3 | Yes | secp256k1, Ed25519 | USB-C | All |
| YubiKey 5 (PIV) | No | secp256k1, Ed25519 (one each) | USB / NFC | AgentSpec / audit / elevation; no HD wallet |
| iOS Secure Enclave | No native BIP39, but wallet apps wrap one | secp256k1, P-256 | Push + biometric | Lightning + BIP-322 messages |
| Android Keystore | Same as iOS | Per-device | Push + biometric | Lightning + BIP-322 messages |

## Acceptance Criteria

- [ ] Setup wizard offers all four modes; mode 1 and mode 2 require device-connected detection before being selectable
- [ ] Ledger/Trezor: can generate or import seed; can sign AgentSpecs, elevation approvals, and Bitcoin/ETH/Solana txs; conductor never holds private key material
- [ ] YubiKey: signs AgentSpecs and elevation approvals; rejects HD-derivation requests with a clear error
- [ ] Mobile: push notification arrives within 5s of request; admin biometric-signs within 30s; same protocol surface for tx signing and HITL elevation (S-151)
- [ ] Hardware unplugged or unavailable: conductor enters degraded mode (no signing operations) and prompts admin instead of crashing
- [ ] Mode-switching: an operator can migrate from software seed to hardware-held seed via a documented re-pairing flow without re-installing
- [ ] Audit log records the signing modality for every signed operation (`software`, `ledger`, `trezor`, `yubikey`, `mobile`)

## Implementation Notes

- Use HWI (Hardware Wallet Interface, https://github.com/bitcoin-core/HWI) as the abstraction layer for Ledger/Trezor; avoids vendor-specific protocol drift.
- Native libs: `hidapi` for USB HID, `btleplug` (Rust) for BLE, `libykpiv` for YubiKey PIV.
- Mobile signing protocol: BIP-322 ("Generic Signed Message Format") for arbitrary payloads, including elevation approvals. Wallet apps that already support BIP-322 (Phoenix, Mutiny, Zeus) work without custom integration.
- Push transport for mobile: WebPush (VAPID) plus an end-to-end-encrypted payload envelope. Server (conductor) holds only the wallet's pubkey + push subscription endpoint.
- Mode 3 pairing: QR-code-based; phone scans QR shown by dashboard, exchanges keys, registers push endpoint. Standard pattern from existing wallet apps.

## Verification

- Plug Ledger; run wizard; verify a Bitcoin testnet send signs on-device.
- Plug Trezor; sign an AgentSpec; verify signature validates against the device's `m/0'` pubkey.
- Insert YubiKey; sign an elevation approval; verify the conductor records modality `yubikey`.
- Pair phone; trigger a HITL elevation in the dashboard; verify push notification arrives, signs via biometric, and the operation proceeds.
- Unplug hardware mid-session; verify conductor refuses subsequent signing ops with a user-facing prompt rather than crashing.
