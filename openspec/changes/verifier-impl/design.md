# Design

## Context

See proposal.md — Why. The `verifier` skeleton establishes that verification is adversarial and that PoCs detonate inside containment, but leaves the mechanism undefined. This design fixes intake, PoC construction, the reproducibility criterion, and the evidence package so the gate is buildable. The verifier sits between `worker-episode` (which emits candidates) and reporting (which publishes findings), and it is the only component allowed to promote a candidate to a finding.

## Goals / Non-Goals

**Goals:**
- A gate that confirms a candidate only with a reproducible, threshold-meeting PoC detonated in containment.
- A confirmed finding that a human can reproduce from the evidence package alone.
- Adversarial-by-construction verification that resists the producing worker's optimism.

**Non-Goals:**
- Candidate generation — that is `worker-episode`'s job; the verifier only consumes candidates.
- Report formatting and submission — downstream reporting owns that; the verifier produces the evidence package.
- Scoring/prioritization internals — triage ordering reuses the candidate's frontier value rather than defining a new model.

## Decisions

### D1 — Reproducibility is a multi-run threshold, not a single success

A candidate is confirmed only when its PoC produces the effect across repeated independent runs meeting a configurable threshold (e.g. N of M runs). Rationale: one-off and flaky triggers are the dominant false-positive vector; requiring repeated independent reproduction is what makes "PoC-gated" meaningful. Alternative (single successful run) rejected as too weak.

### D2 — Fresh adversarial context, separate from the producing worker

Verification runs in a context separate from the worker that produced the candidate, and starts by trying to *disprove* it. Rationale: the producing worker is biased toward its own hypothesis; an independent adversarial pass mirrors the proven verify-stage pattern used in review and removes confirmation bias. The verifier only accepts what survives the disproof attempt.

### D3 — PoC construction and detonation only inside containment, reusing the snapshot

The PoC is built and run exclusively inside the target's contained instance, and the same containment snapshot that reproduces the effect becomes part of the evidence package. Rationale: safety (no live/out-of-box detonation) and reproducibility come from the same mechanism — the snapshot both proves the finding and lets a human re-run it.

### D4 — Per-candidate budget with graceful give-up

PoC construction is bounded by a per-candidate budget; on exhaustion the verifier returns the candidate to the frontier with whatever partial evidence it gathered, rather than looping. Rationale: without a budget a hard candidate can absorb the whole run; returning partial evidence lets the frontier re-score and a later episode retry.

### D5 — Disposition closes the loop

Confirmed candidates become findings with an evidence package; unconfirmed ones return to the frontier as weakened or refuted hypotheses with the disproof recorded. Rationale: the recorded disproof feeds the frontier's dead-end/novelty handling so the system does not re-chase refuted leads, and near-misses stay inspectable by a human.

## Risks / Trade-offs

- Threshold too low → false positives; too high → misses flaky-but-real bugs → threshold is configurable with a conservative default; recorded disproof (D5) lets a human review near-misses.
- PoC construction cost unbounded → per-candidate budget (D4) caps it; partial evidence is preserved.
- Adversarial pass over-rejects subtle genuine bugs → the disproof reasoning is recorded with the returned candidate so a human can spot a wrongly-refuted lead.

## Open Questions

- The default reproducibility threshold (N of M) and the per-candidate PoC budget — calibrated during implementation; both are configuration and change neither the spec nor the evidence-package contract.
