# Tasks

<!-- Builds the verifier (L4). Depends on containment (PoC detonation + snapshot)
     and on the worker-episode candidate-finding shape. -->

## 1. Candidate intake

- [ ] 1.1 Implement candidate intake from the worker/frontier queue and a verification ordering, and verify a test that an emitted candidate is taken in and ordered relative to other pending candidates
- [ ] 1.2 Document the candidate contract the verifier consumes and the finding contract it produces, and verify the documented shapes match the worker-episode candidate and the evidence package

## 2. PoC construction in containment

- [ ] 2.1 Implement proof-of-concept construction that triggers the hypothesized vulnerability inside the target's contained instance, and verify a test that a known-vulnerable sample target yields a triggering PoC run in containment
- [ ] 2.2 Enforce a per-candidate construction budget with graceful give-up, and verify a test that budget exhaustion returns the candidate with partial evidence rather than looping

## 3. Reproducibility and disproof

- [ ] 3.1 Implement the adversarial disproof pass in a context separate from the producing worker, and verify a test that a candidate is only advanced if it survives the disproof attempt
- [ ] 3.2 Implement the multi-run reproducibility threshold (configurable N of M independent runs), and verify tests that a flaky trigger below threshold is not confirmed and a stable one at threshold is

## 4. Evidence and disposition

- [ ] 4.1 Assemble the confirmed-finding evidence package (PoC artifact, containment snapshot, observed effect, reproduction steps), and verify a test that a confirmed finding reproduces from the package alone
- [ ] 4.2 Implement disposition — confirmed candidates become findings, unconfirmed return to the frontier as weakened/refuted with the disproof recorded — and verify tests for both paths

## 5. Integration

- [ ] 5.1 Verify end-to-end that a candidate against a known-vulnerable contained target is adversarially verified, confirmed only when it meets the reproducibility threshold, and emitted as a finding with a package a human can reproduce from
