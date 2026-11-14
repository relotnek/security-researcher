# Design

## Context

See proposal.md — Why. The `frontier` skeleton (from `establish-autonomous-research-architecture`) establishes that the frontier is a scored queue with dead-end pruning, but leaves the scoring model and operations undefined. This design fixes those so the capability is buildable. The frontier reads and writes the durable-state substrate delivered by the foundation change; it does not own persistence itself.

## Goals / Non-Goals

**Goals:**
- A scoring function that yields comparable priorities across targets and engagements.
- A task representation rich enough to score, de-duplicate, and re-score.
- Operations with stable semantics that `worker-episode` and `driver` can build against.

**Non-Goals:**
- Learned/adaptive scoring (weights tuned by outcomes over time) — a later enhancement; this design fixes a transparent, hand-weighted function first.
- The per-target hypothesis generation itself — that is `worker-episode`'s job; the frontier only defines the task shape it accepts.
- Persistence mechanics — owned by the durable-state substrate.

## Decisions

### D1 — Transparent weighted score over a learned model

Priority = a weighted combination of normalized factors (likelihood, impact, engagement value, cost, novelty), with cost in the denominator:

```
  priority = (w_l*likelihood + w_i*impact + w_v*value + w_n*novelty)
             / (w_c*cost + epsilon)
```

Each factor normalized to [0,1] before combining. Rationale: a hand-weighted, inspectable function is debuggable and calibratable by a human researcher from day one; a learned model needs outcome data that does not exist yet and hides why a task ranked where it did. Weights are configuration, so they can be tuned without a spec change. Alternative (learned ranking) deferred to Non-Goals.

### D2 — Novelty as an explicit factor, not just a tiebreaker

Novelty measures how much a task explores regions not yet investigated (by code region, endpoint, hypothesis class). It is a first-class scoring factor so the frontier actively favors breadth early and resists re-treading, rather than only breaking ties. This is the main defense against the random-walk failure mode.

### D3 — Equivalence by canonical task key

De-duplication and dead-end matching use a canonical key derived from (target reference, normalized objective, action class) rather than exact structural equality, so trivially-reworded duplicates collapse. Equivalence is checked on enqueue against both open tasks and recorded dead-ends. Alternative (exact-match only) rejected: workers phrase the same hypothesis many ways and would flood the queue.

### D4 — Re-scoring is explicit, not continuous

Factor estimates update only when a caller supplies new evidence (re-score operation); the frontier does not silently recompute. This keeps scoring deterministic and auditable — a task's position changes only on a recorded event.

### D5 — Operations contract as the integration seam

`enqueue`, `pop-highest`, `peek`, `mark-dead-end`, `re-score` are the only ways workers and the driver touch the frontier. Fixing these now lets the `worker-episode` and `driver` slices build against a stable interface even before the internal scoring is tuned.

## Risks / Trade-offs

- Hand-tuned weights may misrank early → weights are configuration and inspectable (D1); re-scoring (D4) corrects individual tasks as evidence arrives.
- Canonical-key equivalence may over-merge genuinely distinct tasks → key includes action class and objective; tune the normalization, and workers can force-distinguish via provenance when needed.
- Novelty requires tracking explored regions → the frontier records a coverage footprint per task; bounded by target surface, persisted in the substrate.

## Open Questions

- Default weight values and the exact factor normalizations — calibrated during implementation against a sample target; they are configuration and do not change the spec or the operations contract.
