# Spec Delta

## MODIFIED Requirements

### Requirement: Adversarial confirmation

The verifier SHALL attempt to disprove each candidate finding and SHALL confirm it only when a reproducible proof-of-concept that meets the reproducibility threshold demonstrates it; candidates that cannot be reproduced are returned to the frontier rather than reported, with the disproof recorded.

#### Scenario: Unreproducible candidate returned, not reported

- **WHEN** the verifier cannot produce a reproducible proof-of-concept for a candidate
- **THEN** the candidate is returned to the frontier as a weakened or refuted hypothesis and is not reported as a finding

#### Scenario: Reproducible candidate confirmed

- **WHEN** the verifier builds a proof-of-concept that reproducibly demonstrates a candidate
- **THEN** the candidate is confirmed as a finding with its proof-of-concept and evidence attached

## ADDED Requirements

### Requirement: Candidate intake and triage

The verifier SHALL consume unconfirmed candidate findings (hypothesis, evidence, reproduction leads) and order them for verification, so higher-value or more-complete candidates are attempted first.

#### Scenario: Candidate taken in and queued

- **WHEN** a worker emits an unconfirmed candidate finding
- **THEN** the verifier takes it in and places it in its verification queue ordered relative to other pending candidates

### Requirement: Proof-of-concept construction

The verifier SHALL attempt to construct a proof-of-concept that triggers the hypothesized vulnerability, working within a per-candidate budget and giving up gracefully when the budget is exhausted.

#### Scenario: PoC construction attempted within budget

- **WHEN** the verifier begins verifying a candidate
- **THEN** it attempts to construct a triggering proof-of-concept and, if its per-candidate budget is exhausted without success, stops and returns the candidate with the partial evidence gathered

### Requirement: Reproducibility threshold

The verifier SHALL treat a candidate as reproducible only when its proof-of-concept produces the vulnerable effect across repeated independent runs meeting a defined threshold; a one-off or flaky trigger does not qualify.

#### Scenario: Flaky trigger not confirmed

- **WHEN** a proof-of-concept produces the effect on some runs but fails to meet the reproducibility threshold across repeated independent runs
- **THEN** the verifier does not confirm the candidate and returns it to the frontier

### Requirement: Confirmed-finding evidence package

On confirmation, the verifier SHALL assemble an evidence package containing the proof-of-concept artifact, a containment snapshot that reproduces the effect, the observed effect, and reproduction steps.

#### Scenario: Confirmed finding carries reproducible evidence

- **WHEN** the verifier confirms a candidate
- **THEN** the resulting finding includes the proof-of-concept, a containment snapshot reproducing it, the observed effect, and reproduction steps
