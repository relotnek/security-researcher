# Tasks

<!-- Foundation only. This change builds the durable-state substrate, the scope
     fence, and containment provisioning. Frontier, worker-episode, verifier,
     and driver are authored as skeleton specs here and implemented by later
     changes (see proposal.md - Scope of this change). -->

## 1. Durable-state substrate

- [ ] 1.1 Define the durable state schema (engagements, targets, findings, frontier tasks, dead-ends) and verify a round-trip write-then-read test returns the stored records intact
- [ ] 1.2 Implement the target-class taxonomy (code/software vs. device/firmware/network) used for containment profile selection and verify a unit test classifies a sample of each target type correctly

## 2. Scope registry (L0)

- [ ] 2.1 Implement the scope registry storing in-scope assets, forbidden assets, and permitted action classes per engagement, and verify a stored engagement's scope reads back exactly
- [ ] 2.2 Implement the deny-by-default authorization gate callable before any target action, and verify tests that an out-of-scope target and a forbidden action class are each denied and logged

## 3. Containment (L0.5)

- [ ] 3.1 Implement Docker sandbox provisioning for code targets with default-deny egress, and verify a container starts and an attempted egress to a non-allowlisted host is blocked
- [ ] 3.2 Implement isolated network/VM provisioning for device/firmware/network targets, and verify an instance boots on an isolated segment with no route to the internet except the allowlist
- [ ] 3.3 Implement snapshot and teardown for contained instances, and verify a snapshot reconstitutes instance state and teardown releases the ephemeral resources while the snapshot persists

## 4. Double-boundary integration

- [ ] 4.1 Wire the scope gate and containment so a target action requires both to pass, and verify end-to-end that a request failing either boundary is blocked and logged

## Workflow follow-up

- Sync the delta specs into `specs/` so the full design-of-record exists before the remaining capabilities are implemented.
- Implement the remaining capabilities (`frontier`, `worker-episode`, `verifier`, `driver`) as subsequent changes, each refining its skeleton spec.
- Archive this change once the foundation tasks are complete and verified.
