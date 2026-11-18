# Spec Delta

## Purpose

The prioritized investigation backlog that makes continuous research tractable: it drives best-first search by always surfacing the highest-value next investigation and pruning explored dead-ends.

<!-- SKELETON: scoring factors and weights are deliberately left thin here; the
     calibrated scoring model is to be detailed in the frontier implementation
     change (see design.md Open Questions). -->

## ADDED Requirements

### Requirement: Scored investigation queue

The frontier SHALL maintain investigation tasks each carrying a priority score derived from estimated vulnerability likelihood, impact, engagement value, and cost, and SHALL surface the highest-scored task for dispatch.

#### Scenario: Highest-scored task selected next

- **WHEN** multiple investigation tasks are enqueued with differing scores
- **THEN** the frontier surfaces the highest-scored task as the next one to dispatch

### Requirement: Dead-end pruning

The frontier SHALL record investigations that reached a dead-end and deprioritize re-exploring equivalent tasks.

#### Scenario: Equivalent task deprioritized after a dead-end

- **WHEN** an investigation is marked a dead-end
- **THEN** subsequently enqueued tasks equivalent to it are deprioritized relative to novel tasks
