# Tasks

<!-- Builds worker-episode (L3). Depends on the foundation (scope-registry,
     containment, durable-state substrate) and the frontier operations contract
     from frontier-scoring. Uses the reverse-engineering toolchain as the
     analysis engine. -->

## 1. Episode lifecycle

- [ ] 1.1 Implement the uniform episode lifecycle (load durable state + prior bundle, run bounded work, emit outputs, export checkpoint, terminate) with a resource-budget guard, and verify a test that an episode exits at its budget having persisted a checkpoint
- [ ] 1.2 Document the lifecycle and the episode's inputs/outputs in the worker module docs and verify the documented flow matches the implemented stages

## 2. Resume handoff

- [ ] 2.1 Implement evidence-bundle export (analysis state + reconstruction-obligation ledger) at episode end, and verify a test that the exported bundle lists open and closed obligations
- [ ] 2.2 Implement bundle import and resume-from-ledger at episode start, and verify a test that a second episode continues open obligations without re-deriving closed ones

## 3. Pipeline selection

- [ ] 3.1 Implement pipeline selection from target class (firmware/device, mobile, web, native/software), and verify tests that each class routes to its pipeline
- [ ] 3.2 Implement the firmware/device pipeline body (extraction + native/binary analysis orchestration) and verify it produces observations against a sample contained firmware target
- [ ] 3.3 Implement the web pipeline body (capture + endpoint analysis orchestration) and verify it produces observations against a sample contained web target

## 4. Fence enforcement

- [ ] 4.1 Route every target-touching action through the scope gate and the contained instance, and verify tests that an out-of-scope action is not performed and an authorized action executes inside containment

## 5. Candidate emission

- [ ] 5.1 Implement candidate-finding emission (hypothesis, evidence, reproduction leads, marked unconfirmed) onto the frontier/verifier queue, and verify a test that a likely-vulnerability observation yields an unconfirmed candidate and never a confirmed finding

## 6. Integration

- [ ] 6.1 Verify end-to-end that a worker dispatched on a contained sample target runs its pipeline within budget, emits observations and at least one candidate, checkpoints a resumable bundle, and a follow-up episode resumes from it
