# worker-episode Specification

## Purpose

The ephemeral, bounded research agents that do the actual analysis: each reads durable state, performs one bounded chunk of investigation, writes results back, and terminates, expanding the frontier rather than running forever.

<!-- SKELETON: the concrete per-target analysis pipelines (firmware, mobile, web,
     native) and their REA tool orchestration are to be detailed in the
     worker-episode implementation change. -->

## Requirements

### Requirement: Bounded, resumable episode

A worker episode SHALL load durable research state, perform work within a defined resource budget, persist its results and a resumable checkpoint, and terminate.

#### Scenario: Worker runs within budget and checkpoints

- **WHEN** a worker episode is dispatched for a task
- **THEN** it loads durable state, performs work up to its budget, persists results and a checkpoint from which a later episode can resume, and exits

### Requirement: Frontier expansion as output

A worker episode's output SHALL consist of observations plus new scored investigation tasks and/or candidate findings, rather than a terminal verdict on the whole goal.

#### Scenario: Completed task yields follow-up tasks

- **WHEN** a worker completes its assigned investigation task
- **THEN** it emits observations and enqueues new scored tasks and/or candidate findings onto the frontier
