# frontier Specification

## Purpose

The prioritized investigation backlog that makes continuous research tractable: it drives best-first search by always surfacing the highest-value next investigation and pruning explored dead-ends.

<!-- SKELETON: scoring factors and weights are deliberately left thin here; the
     calibrated scoring model is to be detailed in the frontier implementation
     change (see the establish-autonomous-research-architecture design Open Questions). -->

## Requirements

### Requirement: Scored investigation queue

The frontier SHALL maintain investigation tasks each carrying a priority score derived from estimated vulnerability likelihood, impact, engagement value, cost, and novelty, and SHALL surface the highest-scored task for dispatch.

#### Scenario: Highest-scored task selected next

- **WHEN** multiple investigation tasks are enqueued with differing scores
- **THEN** the frontier surfaces the highest-scored task as the next one to dispatch

#### Scenario: Novelty breaks a tie

- **WHEN** two tasks have equal likelihood, impact, value, and cost but one explores a region not yet investigated
- **THEN** the frontier ranks the more novel task higher

### Requirement: Dead-end pruning

The frontier SHALL record investigations that reached a dead-end and deprioritize re-exploring equivalent tasks.

#### Scenario: Equivalent task deprioritized after a dead-end

- **WHEN** an investigation is marked a dead-end
- **THEN** subsequently enqueued tasks equivalent to it are deprioritized relative to novel tasks

### Requirement: Deterministic score combination

The frontier SHALL combine a task's factors into a single comparable priority using a defined function that normalizes each factor to a common range, so tasks from different targets and engagements are comparable on one queue.

#### Scenario: Cross-target tasks are comparable

- **WHEN** tasks from two different targets are scored with the same factor function
- **THEN** their priorities are directly comparable and order the single queue deterministically

#### Scenario: Same inputs yield the same score

- **WHEN** a task is scored twice from identical factor estimates
- **THEN** the computed priority is identical both times

### Requirement: Investigation task shape

The frontier SHALL represent each investigation task with a defined structure that includes a target reference, a hypothesis or objective, an intended action class, per-factor estimates, and provenance (what produced it).

#### Scenario: Well-formed task accepted

- **WHEN** a task carrying a target reference, objective, action class, factor estimates, and provenance is enqueued
- **THEN** the frontier accepts it, scores it, and makes it available for dispatch

#### Scenario: Malformed task rejected

- **WHEN** a task missing a required field is submitted
- **THEN** the frontier rejects it rather than enqueuing an unscoreable task

### Requirement: Task equivalence and de-duplication

The frontier SHALL detect when a submitted task is equivalent to an existing open task or a recorded dead-end, and SHALL merge or deprioritize it rather than enqueue a duplicate.

#### Scenario: Duplicate of an open task merged

- **WHEN** a task equivalent to one already open is submitted
- **THEN** the frontier merges it into the existing task instead of creating a duplicate

#### Scenario: Equivalent to a dead-end deprioritized

- **WHEN** a task equivalent to a recorded dead-end is submitted
- **THEN** the frontier deprioritizes it below novel tasks

### Requirement: Re-scoring as evidence accrues

The frontier SHALL support updating a task's factor estimates when new evidence arrives and recomputing its priority so its queue position reflects current knowledge.

#### Scenario: New evidence raises priority

- **WHEN** evidence raises the estimated likelihood of a queued task
- **THEN** the frontier recomputes its priority and moves it up in the queue

### Requirement: Queue operations contract

The frontier SHALL expose a defined set of operations — enqueue, pop-highest, peek, mark-dead-end, and re-score — with stable semantics that workers and the driver depend on.

#### Scenario: Pop-highest returns and removes the top task

- **WHEN** the driver calls pop-highest
- **THEN** the frontier returns the highest-priority ready task and removes it from the ready set

#### Scenario: Mark-dead-end records and prunes

- **WHEN** a worker marks a task a dead-end
- **THEN** the frontier records the dead-end and removes the task from the ready set so it is not dispatched again
