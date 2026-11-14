# Proposal

## Why

The verifier is the anti-hallucination spine — the single gate that keeps the system from reporting bugs that aren't real, which at scale destroys signal and, on bounty programs, reputation. But the `verifier` capability is a skeleton (adversarial confirmation, PoC-in-containment) that does not define how candidates are taken in, how a proof-of-concept is constructed, what "reproducible" concretely means, or what evidence a confirmed finding carries. Without that detail the gate cannot be built.

## What Changes

- Refine the `verifier` capability from skeleton to buildable spec.
- Define **candidate intake and triage**: consuming the unconfirmed candidates workers emit and ordering them for verification.
- Define **proof-of-concept construction** inside containment.
- Define the **reproducibility threshold**: confirmation requires the PoC to reproduce the effect across repeated independent runs, not a single success.
- Define the **confirmed-finding evidence package**: PoC artifact, containment snapshot, observed effect, and reproduction steps.
- Extend adversarial confirmation to require a PoC that meets the reproducibility threshold.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `verifier`: Add candidate intake/triage, PoC construction, an explicit reproducibility threshold, and the confirmed-finding evidence package; extend adversarial confirmation to require a threshold-meeting PoC.

## Impact

- Refines and builds the `verifier` capability (L4).
- Depends on `containment` (PoC detonation and the snapshot captured for evidence) and on `worker-episode` (the candidate-finding shape it consumes), both from changes being prepared/applied in parallel.
- Downstream: confirmed findings feed reporting/output; unconfirmed candidates return to the `frontier` as weakened or refuted hypotheses with the disproof recorded.
