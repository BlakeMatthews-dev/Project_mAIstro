---
id: S-143
title: "1kHz reactor loop — event-driven runtime, replaces 30-min heartbeat"
domain: conductor
status: draft
priority: P1
effort: ""
created: 2026-04-25
completed: ""
owner: conductor
commits: []
supersedes: "S-001 (heartbeat becomes a degenerate event source on the reactor)"
---

# S-143: 1kHz Reactor Loop

## Problem

The original heartbeat (S-001) runs at 30-minute cadence: a wall-clock tick wakes the conductor, it scans `HEARTBEAT.md` for action items, decides whether to act or return `HEARTBEAT_OK`, and goes back to sleep. This was right as a bootstrap pattern — it gave the conductor *some* sense of time — but it wedges the architecture into a polling shape that doesn't fit the actual product:

- **Background work is event-driven.** Mood Ring (S-031) wants to react to system-health changes as they happen, not 30 minutes later. Phantom (S-030) wants to fire when a skill changes, not on the next tick. Federation (S-156) wants to handle incoming Lightning messages immediately. "Wait for the next 30-minute heartbeat" is the wrong default.
- **Latency on heartbeat-spawned tasks is 30 min average.** A reminder set for 14:01 fires at the 14:30 tick. Time Capsule (S-034) and Morning Digest (S-011) work around it with their own scheduling, but each is a separate cron-shaped subsystem.
- **The capability envelope (S-002–S-005) is decoupled from scheduling.** Heartbeat-spawned tasks (S-105) get an extended tool-call cap *because* heartbeat is special. With a reactor loop, every event source uses the same envelope construction; "who fired this and what cap do they get" is per-source policy, not heartbeat-vs-chat.

## Solution

Replace the 30-minute polling heartbeat with a **1kHz event-driven reactor loop** — epoll on Linux, kqueue on macOS, IOCP on Windows. Every background subsystem becomes an event source on the reactor. The 30-minute wall-clock tick becomes one event source among many; "heartbeat" persists as a name for that specific tick but is no longer the runtime's primary cadence.

### Reactor architecture

```
  Event sources                     Reactor                  Handlers
  -------------                     -------                  --------
  wall-clock ticks (cron-like)  ───▶
  filesystem watches (inotify)  ───▶
  network: HTTP / LN keysend     ───▶                         construct AgentSpec
  IPC: subsystem signals          ───▶ [event loop]   ────▶ (S-002..005), spawn,
  skill-trigger events           ───▶   ~1kHz cycle           run, log to audit
  user prompt arrival             ───▶                         (S-152), submit state
  federation incoming             ───▶                         writes (S-140)
  GPU / system-health signals    ───▶
```

**1kHz** here means *the loop checks for ready events at most once per millisecond*; quiescent periods sleep on the kernel wait, no busy spin. "1kHz" is the upper bound on latency from event-ready-on-fd to handler-invoked, not a steady-state work rate. Steady-state CPU under no load is near zero.

### Built-in event sources

| Source | Replaces / adds | AgentSpec capability |
|---|---|---|
| `wall-clock-tick` | Original heartbeat (S-001), Time Capsule (S-034), Morning Digest (S-011) | per-source (digest gets digest tools, time-capsule gets reminder tools) |
| `filesystem-watch` | Plugin install events, Obsidian inbox arrivals | reactor source, narrow envelope |
| `network-http` | User prompt arrivals on the substrate (S-153) | live-chat envelope (3-round cap, S-105 contrasts) |
| `network-ln` | Federation incoming (S-156); Lightning tip arrivals (S-151) | federation envelope (LN-paid, capability per peer trust VC) |
| `ipc-signal` | Subsystem-to-subsystem (Bouncer pattern updates, Tournament results, Phantom completions) | privileged envelope (admin signature required for graph mutations) |
| `skill-trigger` | A skill announces it wants to run on a specific event | per-skill envelope from trust tier (S-030) |
| `system-health` | Mood Ring (S-031) consumes GPU temps, disk usage, memory pressure | observation-only; emits internal events for other subsystems |
| `user-fired` | Explicit user requests via Console / CLI / channel | identity-attested per S-153 |

### What "heartbeat" means now

S-001's heartbeat is **one event source** on the reactor, firing every 30 minutes. Existing heartbeat behavior (scan `HEARTBEAT.md`, decide action, message user or return `HEARTBEAT_OK`) is preserved as the handler for `wall-clock-tick:30m`. Code that previously called `heartbeat_runner.tick()` is now a reactor handler; the API surface is unchanged for callers but the engine underneath is event-driven.

This means S-105 (uncapped tool loop for heartbeat tasks) generalizes: any reactor source can declare its envelope policy (live-chat vs. heartbeat-style autonomous), and the spawner constructs the envelope accordingly. The 3-round cap is for `network-http` chat; the 50-round cap is for `wall-clock-tick`, `filesystem-watch`, and other autonomous sources.

### Capability envelope per source

Reactor sources declare their envelope construction policy at registration:

```python
reactor.register(
    source = "wall-clock-tick:30m",
    handler = heartbeat_handler,
    envelope_policy = AgentSpecPolicy(
        role           = "HEARTBEAT",
        tool_whitelist = ["file_ops", "messaging", ...],
        tool_call_cap  = 50,           # was 3 for chat (S-105)
        token_budget   = 200_000,
        identity       = "system",     # not user-attested
    ),
)
```

The spawner (S-002) consumes this policy to construct the AgentSpec when the source fires. No source bypasses the Bouncer (S-022); Bouncer screens every event payload before the handler runs.

### Single-writer SQLite contract (S-140)

Reactor handlers do not write directly to SQLite. They submit transactions to `state.submit()` (S-140's queue). The reactor + writer thread + WAL combination handles thousands of writes/second without contention; the queue keeps the writer hot without blocking handlers.

### Telemetry

- Per-source event count, handler latency p50/p95/p99 — emitted to Langfuse (S-021).
- Reactor cycle latency (wake → handler dispatch) tracked separately; flagged when > 5ms p95 (indicates contention or a slow handler).
- Quiescent-period CPU near zero; under load, CPU is dominated by handler work, not loop overhead.

## Acceptance Criteria

- [ ] Reactor loop wakes within 5ms p95 of an event becoming ready
- [ ] All existing heartbeat behavior (S-001) works as a `wall-clock-tick:30m` event source on the reactor
- [ ] Quiescent CPU usage < 1% on a typical desktop
- [ ] Multiple event sources can fire concurrently without race conditions; test with a deliberately racing pair (network + wall-clock + filesystem)
- [ ] Each source declares its capability-envelope policy at registration; spawner uses that policy to construct the AgentSpec
- [ ] No event source bypasses the Bouncer; every event payload is screened before the handler runs
- [ ] All state mutations from handlers go through `state.submit()` (S-140); no direct write-mode SQLite connections
- [ ] Reactor handlers cannot block the loop — long-running handler work is offloaded to a worker pool; handler return must be ≤5ms p95
- [ ] Telemetry: per-source event count and latency visible in the Console
- [ ] Failing handler does not crash the reactor; reactor logs the error and continues

## Implementation Notes

- **Linux:** `epoll` directly, or via `tokio` (Rust) / `asyncio` (Python with `uvloop`).
- **macOS:** `kqueue`, same wrappers.
- **Windows:** IOCP via the same async runtime.
- **Cross-platform abstraction:** Tokio (Rust) or asyncio with uvloop (Python) handle the platform differences cleanly.
- **Worker pool:** for handlers that can't return in 5ms (e.g., LLM calls, file IO), the handler enqueues work to a worker pool and returns. The worker emits a follow-up event when it completes; the reactor handles that event in the next cycle.
- **Backpressure:** if any source produces events faster than handlers consume, the reactor applies per-source rate limits and backpressure. A misbehaving source cannot starve others.
- **Hot-reload:** new event sources can be registered at runtime (e.g., a Medley plugin that adds a new source). Sources can be deregistered cleanly.
- **Clock source:** monotonic clock for tick scheduling (immune to wall-clock changes); wall-clock for log timestamps.
- **Migration of S-001:** existing heartbeat code is wrapped as a reactor source; no behavior change for callers. The heartbeat-runner module becomes a thin shim that registers `wall-clock-tick:30m` and dispatches to the existing `tick()` function.

## Verification

- Idle conductor for 1 hour → CPU < 1% sustained, only the 30-minute heartbeat tick consuming any cycles.
- Generate 10K events/second mixed across 5 sources → reactor sustains; no event drop; latency p95 < 5ms.
- Run a test handler that sleeps 100ms (deliberate violation) → reactor logs the violation and offloads it to the worker pool; subsequent cycles unaffected.
- Heartbeat compatibility: existing S-001 acceptance criteria pass with no change — the heartbeat looks identical to callers; verify by running the old heartbeat test suite against the reactor implementation.
- Filesystem-watch test: drop a file in the Obsidian inbox → reactor fires within 5ms; handler runs.
- LN federation test: incoming Lightning keysend → reactor fires; Bouncer screens; handler dispatches to federation logic; round-trip in <100ms on a healthy network.
- Failing handler test: register a handler that raises on every invocation; verify reactor logs the error and continues; verify telemetry shows the failure rate.
