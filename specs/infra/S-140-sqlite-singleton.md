---
id: S-140
title: "SQLite singleton writer — the invariant that protects state under the reactor"
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

# S-140: SQLite Singleton Writer

## Problem

Agent Conductor uses SQLite + sqlite-vec as its primary state store (S-138). Under a 1kHz reactor loop (S-143) with multiple subsystems generating writes — memory consolidation (S-008, S-025), audit-log VCs (S-152), federation handshakes (S-156), wallet operations (S-151), Bouncer pattern updates (S-026), trust-tier promotions (S-030), recipe ELO scores (S-027) — SQLite is at risk if write paths are not coordinated.

SQLite's write model is single-writer at the file-handle level: WAL mode helps concurrent reads but every write still serializes. Multiple processes opening write-mode connections to the same database produce `SQLITE_BUSY` errors, locked-row contention, and (in degenerate cases) silent state divergence.

The naive fix is per-call backoff and retry. The correct fix is **structural**: only one writer ever opens the database in write mode; every other code path either reads (WAL handles that) or queues writes through the singleton. Foot-guns get caught at construction time, not at runtime.

## Solution

The conductor process runs **exactly one writer thread / task** that owns a single write-mode SQLite connection. Every other code path that wants to mutate state submits a write to the singleton via an in-process queue. Code that opens a write-mode connection from anywhere else is rejected at construction.

### Architecture

```
  Subsystems         Writer queue         Singleton writer
  -----------        ------------         ----------------
  Bouncer          ───▼                       │
  Memory             ▼                       │
  Audit log        ───▶ [in-memory]    ───▶ ┌───────────────────┐
  Federation         ▲    bounded queue       │ SQLite (WAL,    │
  Wallet ops       ───│    backpressure        │  synchronous=    │
  Skill Forge        │    on overflow         │  NORMAL,         │
  Tournament       ───┘                       │  busy_timeout=  │
                                              │  5000ms)         │
  Console (read)   ───▶ [WAL readers]  ───▶ └───────────────────┘
  Memory queries   ───▶ (multi-reader OK,                  ▲
                         no contention)                      │
                                                              │
                                          External tooling ──┘ (read-only;
                                          (sqlite3 CLI)        WAL mode allows)
```

### Construction-time enforcement

- **One write-mode connection.** The conductor's database module exposes `open_writer()` (returns the singleton) and `open_reader()` (returns a fresh read-only connection). `open_writer()` raises if called more than once per process; `open_reader()` opens with `mode=ro` flag.
- **Subsystem API.** Subsystems do not call `open_writer()` directly. They call `state.submit(transaction)` where `transaction` is a structured op (a function plus its arguments) that runs on the writer thread.
- **CI gate.** A grep / linter rule fails the build if any production code opens SQLite in non-`ro` mode outside the singleton module.

### Queue properties

- **Bounded.** Default 10,000 pending writes. Beyond that the queue applies backpressure: submitters block until drain. Prevents OOM under runaway producers.
- **Ordered per source.** Writes from the same subsystem run in submission order. Across subsystems, order is not guaranteed (each transaction is atomic so cross-subsystem ordering shouldn't matter).
- **Promise-returning.** `state.submit()` returns a future the caller can `await`. Most callers don't — they fire-and-forget audit writes — but synchronous-feeling code is supported.
- **Crash-safe.** SQLite is the source of truth. The queue is in-memory. On conductor crash, in-flight queue entries are lost; SQLite remains consistent. Subsystems that need durable submission write a journal entry (separate file) before submitting.

### SQLite tuning

```
PRAGMA journal_mode  = WAL;            # concurrent readers + one writer
PRAGMA synchronous   = NORMAL;         # fsync at commit, not on every write
PRAGMA busy_timeout  = 5000;           # 5s backoff on lock
PRAGMA cache_size    = -65536;         # 64 MiB cache
PRAGMA temp_store    = MEMORY;
PRAGMA mmap_size     = 268435456;      # 256 MiB mmap
PRAGMA foreign_keys  = ON;
```

WAL files are checkpointed periodically (every N seconds or M MiB, whichever first). Long-running transactions are forbidden — they block WAL truncation.

### Why not Postgres / libSQL / Turso

- **Postgres** is the right answer for Agent Stronghold (multitenant) where multi-host concurrent writes matter. For Agent Conductor's single-host scale, SQLite is dramatically simpler with no operational overhead.
- **libSQL / Turso** is a SQLite fork that adds replication. Drop-in upgrade if a Conductor instance grows to need replication. Out of scope today; pre-noted as the upgrade path.
- **DuckDB** is read-optimized for analytical workloads; not the right fit for OLTP-shaped agent state.

## Acceptance Criteria

- [ ] Conductor process opens exactly one SQLite write-mode connection across its lifetime
- [ ] `open_writer()` raises if called more than once; `open_reader()` returns read-only connections
- [ ] CI gate fails the build if any production code opens SQLite in non-`ro` mode outside the singleton module
- [ ] All subsystem writes route through `state.submit(transaction)`
- [ ] Queue is bounded; overflow applies backpressure (submit blocks) rather than dropping or OOMing
- [ ] Concurrent reads from many subsystems + Console + external `sqlite3` CLI work without contention while the writer is active
- [ ] WAL checkpoint runs periodically; database file does not grow unboundedly
- [ ] Conductor crash: SQLite state remains consistent; in-flight queue entries are lost (documented; subsystems that need durability journal first)
- [ ] State database backups are encrypted with the admin keypair (S-141-style age encryption) before writing to disk; no plaintext copy of `state.db` is ever written to `~/.conductor/backups/`; backup files use the `.db.age` suffix and are importable via `maistro db restore`
- [ ] Schema migrations run atomically at startup; a failed migration rolls back completely and conductor refuses to start with a `MIGRATION_FAILED` error naming the failing migration; conductor never starts with a partially-migrated schema
- [ ] Migration path to libSQL / Turso documented (drop-in upgrade for replication)

## Implementation Notes

- **Language:** if conductor is Rust, use `rusqlite` with the `bundled` feature for a stable SQLite version. If Python, use `sqlite3` (stdlib) wrapped in a single asyncio task.
- **sqlite-vec extension:** loaded into the writer connection at startup; reader connections also load it for vector queries.
- **External tooling:** `sqlite3 ~/.conductor/state.db` works for read-only inspection because of WAL mode. Documented for operators.
- **Backups:** use SQLite's online-backup API (`VACUUM INTO`) on a schedule. Backups live in `~/.conductor/backups/state-<timestamp>.db.age` (encrypted with admin keypair, S-141-style). The plaintext intermediate (`VACUUM INTO` target) is age-encrypted in the same atomic step and the plaintext file deleted; this means the plaintext database is briefly on disk only during the backup window — documented as the accepted trade-off.
- **Schema migrations:** atomic, version-stamped, run by the singleton at startup. Failed migrations roll back; conductor refuses to start if migration cannot complete.
- **Profiling:** the writer thread emits per-transaction latency metrics to Langfuse; outliers (>100ms) are flagged.

## Verification

- Run conductor under load (1000 writes/second from mixed subsystems for 1 hour) → no `SQLITE_BUSY` errors; queue stays bounded; WAL checkpoint occurs.
- Attempt to open a second write-mode connection from a test → raises with a clear error.
- CI gate: introduce a `sqlite3.connect("...", isolation_level=None)` outside the singleton in a test branch → build fails with the gate's message.
- Crash test: kill -9 the conductor mid-write → restart → verify SQLite state is consistent and the conductor recovers.
- Concurrent reader test: 50 simultaneous read connections from Console + 5 subsystems while writer runs → no errors, no notable latency degradation.
- Backup test: trigger online backup; verify the resulting `.db.age` file requires the admin keypair to decrypt; verify no unencrypted `.db` remains after the backup completes; verify the decrypted file opens cleanly with `sqlite3`.
- Migration failure test: introduce a deliberately broken migration; attempt to start conductor; verify `MIGRATION_FAILED` error with the migration name, conductor exits, database is unchanged.
