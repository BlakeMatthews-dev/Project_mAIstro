---
id: S-154
title: "Electrum server — Medley plugin for household-private Bitcoin backend"
domain: tools
status: draft
priority: P2
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: ""
---

# S-154: Electrum Server Plugin

## Problem

S-151 makes the conductor Bitcoin- and Lightning-capable. Every wallet operation — balance check, address watch, fee estimation, tx broadcast — requires a chain backend. Two paths:

1. **Use public Electrum servers.** Easy. Costs nothing to set up. **Leaks every address the conductor queries** to the operator of that server. Anyone watching the conductor's queries learns the operator's wallet contents.
2. **Run your own.** The right answer for anyone who cares enough to install Agent Conductor in the first place — but historically a 60GB, multi-component setup that crypto-curious users don't bother with.

Meanwhile, every adult in the household running a phone wallet (Sparrow, BlueWallet, Phoenix, Zeus, Mutiny) faces the same choice with the same default: trust some random public server with their address book. A household-scale Maistro deployment with Tailscale (S-153) already has the perfect substrate to fix this for everyone, with one Medley install.

## Solution

A Medley plugin — `medley install electrum-server` — that packages a complete household-private Bitcoin backend:

- **Bitcoin Core** (pruned by default, full optional)
- **electrs** (Rust Electrum-protocol server)
- **Tailscale Serve** (or other substrate-equivalent) configuration exposing the Electrum protocol port to the tailnet only
- **Default configuration** tuned for household use: pruning depth, index settings, peer count, RPC limits

Once installed, three things become true simultaneously:

1. The conductor's Bitcoin/Lightning wallet (S-151) routes all chain queries to `localhost`.
2. Household members configure their phone wallets to point at `electrum.<instance>.<tailnet>.ts.net:50002` (TLS) and stop leaking addresses to public servers.
3. The Lightning plugin gets a local chain-data source for channel operations, removing the public-LSP dependency for chain interaction.

### Plugin shape

```yaml
# medley.yaml
name: electrum-server
version: 1.0.0
type: skill+service
requires:
  - substrate.has_https_endpoint  # provided by S-153
resources:
  disk: 60GB        # Bitcoin Core pruned + electrs index
  memory: 2GB       # at steady state
  bandwidth: 10GB/month  # initial sync excluded
services:
  - name: bitcoind
    command: bitcoind --conf=$PLUGIN_DIR/bitcoin.conf
    state: $PLUGIN_DIR/bitcoin
  - name: electrs
    command: electrs --conf $PLUGIN_DIR/electrs.toml
    depends_on: bitcoind
    state: $PLUGIN_DIR/electrs-db
exposes:
  - port: 50002
    protocol: electrum-tls
    substrate_path: /electrum   # tailnet-private by default
  - port: 8332
    protocol: bitcoin-rpc
    substrate_path: null         # localhost-only; conductor's wallet uses this
```

### Default configuration (household-tuned)

```toml
# bitcoin.conf
prune = 10000           # ~10GB chain state, sufficient for most household ops
txindex = 0             # not needed; electrs maintains its own index
rpcuser = (auto-generated, stored in S-141 vault)
rpcpassword = (auto-generated, stored in S-141 vault)
listen = 0              # outbound only; no public peer exposure
maxconnections = 8

# electrs.toml
daemon_rpc_addr = "127.0.0.1:8332"
electrum_rpc_addr = "127.0.0.1:50001"
electrum_rpc_tls_addr = "127.0.0.1:50002"
tls_cert = (provided by substrate)
db_dir = "$PLUGIN_DIR/electrs-db"
index_lookup_limit = 200
```

### Substrate exposure

With S-153's substrate abstraction:

| Substrate | Exposure mechanism | URL family wallets configure |
|---|---|---|
| Tailscale | `tailscale serve` on TCP 50002 | `<instance>.<tailnet>.ts.net:50002` |
| Headscale | Same as Tailscale | `<instance>.<headscale>:50002` |
| Cloudflare Tunnel | TLS pass-through tunnel | `<operator-domain>:50002` |
| LAN-mDNS | Direct LAN port | `<instance>.local:50002` (self-signed cert) |
| Localhost-only | Not exposed externally | conductor's wallet only |
| Manual | Operator's reverse proxy with TCP termination | Per operator config |

**Default for all substrates: tailnet/LAN-private. `tailscale funnel` for public exposure is explicitly NOT offered for the Electrum port** — a public Electrum server has different threat properties (DoS, bandwidth costs, address-set inference attacks) that are out of scope for a household plugin.

### Pairing with the Lightning plugin (S-151)

The Lightning plugin's chain-backend dependency is auto-satisfied when this plugin is installed. The Medley dependency resolver should prefer this pairing:

- `medley install lightning` with no chain backend → prompts: *"Lightning needs chain data. Install electrum-server (recommended, ~60GB, household-private) or configure a remote backend?"*
- `medley install lightning electrum-server` (both at once) → wires them together; LDK / LND uses local Bitcoin Core + electrs.

The Lightning plugin can run without electrum-server (using public chain providers), but the wizard prompts toward the privacy-preserving combination.

### Initial sync UX

Fresh install of Bitcoin Core pruned-mode is ~6-12 hours of sync depending on connection. The plugin handles this gracefully:

- Install completes immediately with a status banner: *"Initial sync in progress (~9h remaining). Wallet operations will work once chain head is current."*
- Dashboard Resources tab shows sync progress (current block / chain tip / ETA).
- Optional: pre-sync snapshot import from a trusted source (Casa, Mempool.space) cuts the sync to ~30 min. Trade-off: the operator trusts the snapshot publisher; documented but not default.
- Conductor's wallet (S-151) operates in lightweight mode using a public Electrum endpoint until local sync completes, then automatically migrates to the local server. Migration is a config flip; admin-signed.

### Update semantics

`medley update electrum-server` must not silently break wallet operations or corrupt chain state:

1. The conductor's wallet automatically falls back to the public Electrum endpoint at update start (same lightweight-mode fallback as initial sync).
2. electrs is stopped first (it depends on bitcoind).
3. bitcoind is stopped; binaries are replaced; checksums verified against the new plugin VC (S-111).
4. bitcoind is restarted and allowed to reach chain tip before electrs is started.
5. Once electrs is indexed, the conductor's wallet migrates back to localhost; admin-signed.

Rollback: if any step fails, the old binaries are restored from the plugin's version cache and services restarted on the previous version. The update failure is posted to the board.

### Chain data backup policy

The Bitcoin Core state and electrs index (up to 60 GB) are **not** included in vault backup (`maistro vault export`, S-141) — they are too large and fully re-syncable from the network. Operators should be aware:

- **What requires backup:** only the vault-stored RPC credentials and TLS material (already covered by `maistro vault export`).
- **Recovery from data loss:** delete `$PLUGIN_DIR/bitcoin` and `$PLUGIN_DIR/electrs-db`, restart the plugin, and re-sync (~6-12 hours). Lightning channel state is held by the Lightning plugin (S-151), not this plugin.
- `medley info electrum-server` surfaces this policy explicitly so operators are not surprised.

### What this plugin does NOT do

- Not a full archival node by default (pruning is on). Operator can disable pruning for full archival (~700GB) via plugin config.
- Not a public-internet Electrum server (see substrate exposure section above).
- Not a Lightning Service Provider (LSP). Lightning lives in the lightning plugin (S-151); this plugin only provides chain data.
- Not a block explorer with web UI. That would be `medley install mempool` (future plugin).
- Not a wallet itself. The conductor's wallet (S-151) is the consumer; this plugin is the backend.

## Acceptance Criteria

- [ ] `medley install electrum-server` brings up bitcoind + electrs as supervised services
- [ ] Initial sync completes and dashboard reflects accurate progress throughout
- [ ] Conductor's wallet (S-151) automatically uses the local backend once sync is current
- [ ] Lightning plugin (S-151) detects and uses the local Bitcoin node when both are installed
- [ ] Household phone wallets (Sparrow, BlueWallet, Phoenix, Zeus, Mutiny) successfully connect using the documented endpoint
- [ ] Tailnet-private exposure is the default; public exposure is not offered through normal config flow
- [ ] Plugin survives conductor restart with no data loss; bitcoind and electrs come back to a consistent state
- [ ] RPC credentials and TLS material are stored in the S-141 vault, never in plaintext config files visible to other plugins
- [ ] Resource caps (memory, bandwidth) are enforced via the substrate's per-plugin sandboxing (S-148 container path) or systemd cgroups (S-147 native path)
- [ ] Phantom Execution (S-030) verifies plugin behavior on signet before mainnet promotion
- [ ] Pre-sync snapshot import is offered as an option with explicit "trust this publisher" gate
- [ ] `medley update electrum-server` follows the ordered stop/update/restart sequence; wallet falls back to public endpoint during the update window; failed update rolls back to previous binaries and posts to board
- [ ] Chain data backup policy is documented in `medley info electrum-server`: chain data is NOT vault-backed; re-sync is the recovery path; only vault credentials require backup
- [ ] Port conflict detection: if the configured Electrum TLS port (default 50002) is already in use at install time, the install fails with a clear error message and directs the operator to set `electrum_rpc_tls_port` in plugin config

## Implementation Notes

- **Electrum-protocol server:** `electrs` (Rust, Romanian Andrei) is the recommended default; `Fulcrum` (C++, Calin Culianu) is offered as an alternative for operators who already prefer it. Both speak the same protocol; Medley plugin variant flag chooses.
- **Bitcoin Core distribution:** ship checksummed binaries from bitcoincore.org with PGP-verified release manifests. Plugin install verifies signatures before unpacking. Operator can point the plugin at a pre-existing bitcoind installation via config (`use_existing_bitcoind: true`).
- **Snapshot import:** UTXO set snapshots from `assumeutxo` (Bitcoin Core 25.0+) or chainstate snapshots from `mempool.space`. Both have explicit trust models; both are documented in the install prompt.
- **TLS certs for Electrum protocol:** when the substrate is Tailscale, use `tailscale cert` to obtain a valid LE cert for the conductor hostname; electrs serves Electrum-over-TLS using the same cert. For LAN-mDNS, mkcert-generated cert with operator-installed root. For localhost-only, self-signed; conductor's own wallet is the only consumer.
- **Family-wallet onboarding:** the dashboard generates a QR code containing the Electrum endpoint URL + cert fingerprint. Family members scan with their phone wallet to configure it in one step. No manual hostname-typing.
- **Storage location:** plugin storage lives at `~/.conductor/medley/electrum-server/` by default. Operators with separate disks can symlink to a larger volume; this is documented but not default.
- **Multiple chains:** v1 supports Bitcoin mainnet, signet, and testnet (selectable at install). Liquid, Litecoin, etc. are out of scope for v1; future Medley plugins (`medley install liquid-server`) extend this pattern.

## Verification

- Fresh install: `medley install electrum-server` on a host with no prior Bitcoin tooling completes in <5 minutes (sync runs in background).
- During sync: conductor's wallet falls back to a remote Electrum endpoint; no failed operations.
- After sync: kill the remote endpoint config; conductor's wallet operates against localhost only.
- Family wallet: scan dashboard QR with Sparrow on iOS → wallet connects, syncs, balance is correct.
- Lightning pairing: `medley install lightning` afterward auto-detects the local Bitcoin node and uses it.
- Privacy test: tcpdump the conductor's external traffic during a wallet operation — no Electrum-protocol packets leave the tailnet.
- Restart test: reboot the conductor host; bitcoind and electrs come back; first wallet query within 30s succeeds.
- Snapshot test: install with `--snapshot mempool.space` → sync to chaintip in <30 min; verify chain head matches a public block explorer.
- Phantom test: a new bitcoin-touching plugin installed alongside electrum-server runs against signet via the local server before mainnet promotion.
- Update test: run `medley update electrum-server`; verify wallet falls back to public endpoint during update; verify services restart cleanly; verify wallet migrates back to local.
- Port conflict test: bind port 50002 before installing; verify install fails with a clear port-conflict error.
