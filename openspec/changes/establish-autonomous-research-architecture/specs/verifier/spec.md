# Spec Delta

## Purpose

The anti-hallucination spine of the system: an adversarial step that tries to disprove each candidate finding and only confirms it when a reproducible proof-of-concept can be built and detonated inside containment.

## ADDED Requirements

### Requirement: Adversarial confirmation

The verifier SHALL attempt to disprove each candidate finding and SHALL confirm it only when a reproducible proof-of-concept demonstrates it; candidates that cannot be reproduced are returned to the frontier rather than reported.

#### Scenario: Unreproducible candidate returned, not reported

- **WHEN** the verifier cannot produce a reproducible proof-of-concept for a candidate
- **THEN** the candidate is returned to the frontier as a weakened or refuted hypothesis and is not reported as a finding

#### Scenario: Reproducible candidate confirmed

- **WHEN** the verifier builds a proof-of-concept that reproducibly demonstrates a candidate
- **THEN** the candidate is confirmed as a finding with its proof-of-concept and evidence attached

### Requirement: Proof-of-concept detonation inside containment

The verifier SHALL execute every proof-of-concept inside the target's contained instance, never against a live or out-of-box asset.

#### Scenario: PoC runs inside containment

- **WHEN** the verifier executes a proof-of-concept
- **THEN** it runs inside the contained instance of the target
