# Proposal

## Why

The frontier is the system's prioritization brain — best-first search over a combinatorial space is what keeps continuous research from degrading into an unbounded random walk. But the `frontier` capability is currently a thin skeleton (two requirements) that does not define how tasks are scored, generated, compared, de-duplicated, or re-scored as evidence accrues. Without that detail it cannot be built or calibrated.

## What Changes

- Refine the `frontier` capability from skeleton to buildable spec.
- Define the **scoring model**: the factors (likelihood, impact, engagement value, cost, novelty) and how they combine into a single comparable, normalized priority.
- Define **task generation**: the shape of an investigation task and how workers and the driver enqueue them.
- Define **equivalence and de-duplication**: detecting tasks equivalent to open or dead-end tasks.
- Define **re-scoring**: updating factor estimates and recomputing priority when new evidence arrives.
- Define the **queue operations contract** the driver and workers rely on (enqueue, pop-highest, peek, mark-dead-end, re-score).

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `frontier`: Add the scoring model, task-generation shape, equivalence/de-duplication, re-scoring, and the queue operations contract; extend the existing scored-queue requirement with a novelty factor and normalized combination.

## Impact

- Refines and builds the `frontier` capability (L2).
- Depends on the durable-state substrate from `establish-autonomous-research-architecture` (frontier tasks and dead-ends are persisted there); that foundation is being applied in parallel. No `scope-registry` or `containment` behavior is touched.
- Downstream: `worker-episode` (emits tasks onto the frontier) and `driver` (pops tasks) depend on the operations contract defined here.
