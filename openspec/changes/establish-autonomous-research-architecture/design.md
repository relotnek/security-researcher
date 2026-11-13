# Design

## Context

Greenfield system. See proposal.md — Why. The environment provides the building blocks: the **REA** reverse-engineering toolkit (firmware extraction, Frida/GDB, native/managed/web/mobile analysis, evidence bundles and snapshots), orchestration primitives (scheduled cloud agents, loops, multi-agent workflows), durable connectors (issue/knowledge/notification), and a container/VM substrate. This design assembles them into an autonomous researcher.

The central constraint: **LLM agents are episodic** — bounded context, they terminate. A hard target exhausts a single agent's context well before a proof-of-concept lands. So "always on" cannot mean one long-lived agent; it must mean durable state with disposable workers.

## Goals / Non-Goals

**Goals:**
- An architecture in which research survives agent episode boundaries (cold resume).
- Hard, layered safety: a logical scope fence and physical/network containment, both structural.
- Findings backed by reproducible proof-of-concepts.
- One substrate serving both directed (CVE/target spec → PoC) and discovery (scope → findings) modes.

**Non-Goals (design-level boundaries for this change):**
- Implementing frontier scoring, worker, verifier, or driver logic — authored as skeleton specs, built by later slices.
- Automated bounty submission — human-at-the-gate initially; the system drafts, a human submits.
- Target-specific exploit playbooks.

## Decisions

### D1 — Ephemeral workers, durable state (the inversion)

The always-on element is the **state**, not the agent. A driver re-spawns bounded episodes that read durable state, do one chunk, write state back, and die.

```
   +---------------------+
   |  DURABLE STATE      |  <-- always on
   |  KB + frontier +    |
   |  evidence bundles   |
   +----------+----------+
         ^          |
     (write)     (read)
         |          v
   +-----+----------+----+
   | ephemeral worker    |  <-- disposable, spawned by driver
   | episode (bounded)   |
   +---------------------+
```

Alternative rejected — one long-lived agent: blows context, loses all state on termination, unbounded cost.

### D2 — Durable state has two layers

- **Semantic (human-readable):** engagements, attack-surface maps, hypotheses, findings, dead-ends — files and/or issue/knowledge connectors.
- **Technical (reconstitutable analysis):** REA evidence bundles and snapshots. The evidence bundle is the cross-episode handoff; REA's reconstruction-obligation ledger is the resumable task state for a single deep finding (the checklist of what remains to be proven).

Cold resume protocol: episode N exports an evidence bundle and writes a KB delta; episode N+1 reads the KB, imports the bundle, and continues from the obligation ledger.

### D3 — Double safety boundary

Scope registry (authorization: *what* may be touched) and containment (isolation: *where* action happens) are orthogonal and both mandatory. Containment's default-deny egress also enforces scope at the network level, so scope is backed by a boundary the worker cannot talk past. Neither is a prompt instruction — both are structural gates a target action must pass.

```
  SCOPE (L0)        = "you may target X"              (logical)
  CONTAINMENT(L0.5) = "...only this boxed X, and you  (physical / network
                       can't reach anything else"       enforced)
  -> an action must pass BOTH
```

### D4 — Containment profiles by target class

- **Code / software** → Docker sandbox: ephemeral, default-deny egress, resource-capped, snapshot/restore, PoC detonates inside.
- **Device / firmware / network** → isolated network segment + VMs (emulated firmware or a physical unit on the segment), no route out except an explicit allowlist, capture at the segment boundary.

Rationale: matches the target substrate and REA's supported paths (firmware extraction/emulation and ADB for devices; container for software). Alternative rejected — a single uniform sandbox: cannot host firmware/device targets faithfully.

### D5 — Frontier as best-first search

The system's intelligence is **prioritization**, not the act of hacking. The search space (functions, endpoints, hypotheses) is combinatorial; undirected exploration burns the budget on a random walk. Workers *expand* a scored frontier; the driver always pops the top task. This makes "continuous" tractable and unifies the modes: directed mode is a frontier that **contracts** toward one PoC; discovery mode is a frontier that **expands** and emits a stream.

### D6 — PoC-gated verification

A separate, adversarial verifier must build a reproducible PoC (inside containment) before a candidate becomes a finding. This kills the dominant failure mode of autonomous security agents — confidently reporting non-bugs. No PoC, no finding.

### D7 — Driver on a scheduled agent with a budget governor

Always-on = a scheduled process that wakes, fans out workers (a workflow run per wake), checkpoints, and sleeps. A **per-wake and global budget cap is mandatory**: autonomous + LLM + always-on = unbounded spend without it. The driver halts and alerts on cap.

## Risks / Trade-offs

- Unbounded token/compute cost → budget governor (D7) + frontier pruning (D5).
- False-positive findings → PoC gate (D6).
- Scope or containment escape = legal/safety incident → structural double boundary (D3), default-deny egress (D4).
- Cold-resume loses deep analysis → evidence-bundle handoff + obligation ledger (D2).
- Design-of-record drift as capabilities are built piecemeal → `system-overview` spec holds the cross-cutting invariants; any change reshaping the architecture updates it as part of its scope.
- Tight coupling to REA availability → workers checkpoint before risky operations and degrade gracefully when a tool path is unavailable.

## Migration Plan

Greenfield; nothing to migrate. This change authors the full design-of-record (seven capability specs) and implements only the **foundation**: durable-state substrate, scope fence, and containment provisioning. Syncing the delta specs into `specs/` promotes the design-of-record so it exists whole before full implementation. Subsequent changes implement `frontier`, `worker-episode`, `verifier`, and `driver` as vertical slices, each refining its skeleton spec into detail. Rollback: discard the change; no running system is affected.

## Open Questions

- **Frontier scoring weights and calibration** — the exact factor weighting and normalization. Deferred safely: it does not change the capability boundaries, the foundation, or the task breakdown, and will be fixed in the `frontier` implementation change.
- **First vertical slice after the foundation** — leaning toward `worker-episode` for owned firmware/IoT, because owned devices make the scope fence trivial and a CVE→PoC goal gives a crisp success signal. To confirm when the foundation lands.
