# Design

## Context

See proposal.md — Why. The `worker-episode` skeleton establishes that workers are ephemeral, bounded, and expand the frontier, but leaves the actual analysis undefined. This design fixes how a worker runs a target-appropriate pipeline, resumes deep work across episodes, and stays inside the safety fences. The worker is the main consumer of the reverse-engineering toolchain (REA) and the point where the foundation's scope and containment gates are actually exercised.

## Goals / Non-Goals

**Goals:**
- A worker that picks the right analysis pipeline for the target class and drives REA to do it.
- Cold resume of a multi-episode investigation with no loss of established analysis.
- Every target action demonstrably inside scope and containment.
- Candidate findings shaped for the verifier to confirm.

**Non-Goals:**
- The verifier's confirmation logic — a separate capability; workers only emit candidates.
- Frontier scoring — defined in `frontier-scoring`; workers enqueue tasks through its operations contract.
- Exhaustive per-class playbooks — this design fixes the pipeline *selection and lifecycle*; the depth of each pipeline grows as targets are worked.

## Decisions

### D1 — Pipeline selection mirrors containment profiles

Target class drives both containment profile and analysis pipeline, so they stay aligned: firmware/device → extraction + native/binary analysis; mobile → app/runtime analysis; web → capture + endpoint analysis; native/software → binary/decompilation analysis. Rationale: the class is already known for containment (code vs. device), so reusing it avoids a second classifier and guarantees the pipeline matches the box the target runs in.

### D2 — Evidence bundle + obligation ledger as the resume unit

A single deep finding spans many episodes beyond one context window, so the durable handoff is REA's evidence bundle (reconstitutable analysis state) plus a reconstruction-obligation ledger (the checklist of what remains to prove). An episode imports the bundle, works the open obligations, and re-exports. Rationale: this is the concrete mechanism behind the system's "ephemeral agent, durable state" invariant for *technical* state, which human-readable KB notes alone cannot carry. Alternative (re-analyze from notes each episode) rejected: wastes the budget and loses fidelity.

### D3 — The worker is where the fences are enforced, not just declared

Scope authorization and containment are invariants system-wide, but the worker is the component that actually touches targets, so it calls the scope gate before every action and routes every action through the contained instance. Rationale: enforcing at the point of action — rather than trusting a prompt-level rule — is what makes the double boundary structural. This binds `worker-episode` to `scope-registry` and `containment`.

### D4 — Workers emit candidates, never findings

A worker's analysis produces *candidates* (hypothesis + evidence + reproduction leads), explicitly unconfirmed. Only the verifier, with a reproducible PoC in containment, promotes a candidate to a finding. Rationale: keeps the anti-hallucination gate single and authoritative; a worker that could self-declare findings reintroduces the false-positive failure mode.

### D5 — Episode lifecycle is fixed; pipeline depth is not

Every episode follows the same lifecycle (load state + bundle → run bounded pipeline work → emit observations/tasks/candidates → export bundle + ledger → terminate) regardless of target class. Only the pipeline body differs by class. Rationale: a uniform lifecycle lets the driver treat all workers identically and lets resume work the same way everywhere.

## Risks / Trade-offs

- Tight coupling to the reverse-engineering toolchain → the lifecycle (D5) isolates tool orchestration inside the pipeline body; a worker checkpoints before risky operations so a tool failure loses at most one episode's increment.
- Evidence bundles can grow large across many episodes → ledger tracks open obligations so a resuming episode loads what it needs; bundle retention is bounded per engagement.
- Misclassified target → wrong pipeline and wrong box → class is set once at engagement/containment time (D1); a worker that finds the class wrong records it rather than proceeding against a mismatched instance.

## Open Questions

- The depth and exact tool sequence of each per-class pipeline — grown iteratively as real targets are worked; it does not change the lifecycle, the resume unit, or the candidate shape fixed here.
