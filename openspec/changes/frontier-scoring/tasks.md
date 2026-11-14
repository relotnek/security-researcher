# Tasks

<!-- Builds the frontier (L2). Depends on the durable-state substrate from
     establish-autonomous-research-architecture being in place. -->

## 1. Task model

- [ ] 1.1 Implement the investigation-task structure (target reference, objective, action class, per-factor estimates, provenance) with validation, and verify that a well-formed task is accepted and a task missing a required field is rejected
- [ ] 1.2 Document the task shape and its fields in the frontier module docs and verify the documented example validates as written

## 2. Scoring model

- [ ] 2.1 Implement per-factor normalization to [0,1] for likelihood, impact, engagement value, cost, and novelty, and verify unit tests that out-of-range and boundary inputs normalize correctly
- [ ] 2.2 Implement the weighted combination function (configurable weights, cost in denominator) and verify tests that identical inputs yield identical scores and that two targets' tasks are comparable and order deterministically
- [ ] 2.3 Implement the novelty factor from a per-task coverage footprint of explored regions, and verify a test that a task exploring an uninvestigated region outscores an equivalent-but-explored one

## 3. Equivalence and de-duplication

- [ ] 3.1 Implement the canonical task key (target reference, normalized objective, action class) and verify a test that reworded duplicates produce the same key
- [ ] 3.2 Implement enqueue-time equivalence checks against open tasks and recorded dead-ends, and verify tests that a duplicate of an open task is merged and an equivalent of a dead-end is deprioritized

## 4. Queue operations

- [ ] 4.1 Implement enqueue, pop-highest, peek, mark-dead-end, and re-score against the durable-state substrate, and verify tests that pop-highest returns and removes the top ready task and mark-dead-end removes a task from the ready set
- [ ] 4.2 Implement re-score (update factor estimates from new evidence, recompute priority) and verify a test that raising likelihood moves a queued task up

## 5. Integration

- [ ] 5.1 Verify end-to-end that a batch of enqueued tasks is dispatched in priority order, dead-ends are not re-dispatched, and a re-scored task changes position accordingly
