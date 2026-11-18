# Proposal

## Why

`worker-episode` is the agent that performs the actual analysis, but it is a thin skeleton (bounded episode, frontier expansion as output). It does not define how a worker selects and runs a target-appropriate analysis pipeline, how it hands off deep analysis state so a later episode can resume cold, or how it stays inside the scope and containment fences. Without that detail the worker cannot be built, and cross-episode resume — the core of "always on over durable state" — has no concrete mechanism.

## What Changes

- Refine the `worker-episode` capability from skeleton to buildable spec.
- Define **pipeline selection by target class** (firmware/device, mobile, web, native/software) and orchestration of the reverse-engineering toolchain.
- Define the **episode lifecycle**: load durable state and prior analysis, run bounded pipeline work, emit observations/tasks/candidates, checkpoint, terminate.
- Define **cross-episode resume** via an evidence bundle plus a reconstruction-obligation ledger (what remains to be proven).
- Define **in-worker enforcement**: every target-touching action passes the scope gate and executes inside the target's contained instance.
- Define the **candidate-finding emission shape** the verifier consumes.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `worker-episode`: Add target-appropriate pipeline selection, evidence-bundle resume handoff, in-containment/in-scope action enforcement, and candidate-finding emission; extend the bounded-episode requirement to specify the resumable checkpoint as an evidence bundle and obligation ledger.

## Impact

- Refines and builds the `worker-episode` capability (L3).
- Depends on the foundation (`scope-registry`, `containment`, durable-state substrate) from `establish-autonomous-research-architecture`, being applied in parallel, and on the frontier operations contract from `frontier-scoring` (workers enqueue tasks and candidates).
- Uses the reverse-engineering toolchain (REA) as the analysis engine, including its evidence-bundle and reconstruction-ledger facilities for resume.
- Downstream: `verifier` consumes the candidate findings whose shape is defined here.
