# worker-episode Specification

## Purpose

The ephemeral, bounded research agents that do the actual analysis: each reads durable state, performs one bounded chunk of investigation, writes results back, and terminates, expanding the frontier rather than running forever.

<!-- SKELETON: the concrete per-target analysis pipelines (firmware, mobile, web,
     native) and their REA tool orchestration are to be detailed in the
     worker-episode implementation change. -->

## Requirements

### Requirement: Bounded, resumable episode

A worker episode SHALL load durable research state and any prior analysis bundle, perform work within a defined resource budget, persist its results and a resumable checkpoint consisting of an evidence bundle and a reconstruction-obligation ledger, and terminate.

#### Scenario: Worker runs within budget and checkpoints

- **WHEN** a worker episode is dispatched for a task
- **THEN** it loads durable state, performs work up to its budget, persists results and a checkpoint from which a later episode can resume, and exits

#### Scenario: Checkpoint captures resumable analysis state

- **WHEN** a worker episode reaches its budget mid-investigation
- **THEN** it exports an evidence bundle and an obligation ledger recording what has been established and what remains to prove, then terminates

### Requirement: Frontier expansion as output

A worker episode's output SHALL consist of observations plus new scored investigation tasks and/or candidate findings, rather than a terminal verdict on the whole goal.

#### Scenario: Completed task yields follow-up tasks

- **WHEN** a worker completes its assigned investigation task
- **THEN** it emits observations and enqueues new scored tasks and/or candidate findings onto the frontier

### Requirement: Target-appropriate pipeline selection

A worker SHALL select an analysis pipeline by target class — firmware/device, mobile, web, or native/software — and drive it using the reverse-engineering toolchain appropriate to that class.

#### Scenario: Firmware target drives the firmware pipeline

- **WHEN** a worker is dispatched against a firmware or device target
- **THEN** it runs the firmware analysis pipeline (extraction and native/binary analysis) rather than a web or mobile pipeline

#### Scenario: Web target drives the web pipeline

- **WHEN** a worker is dispatched against a web target
- **THEN** it runs the web analysis pipeline (capture and request/endpoint analysis)

### Requirement: Evidence-bundle resume handoff

A worker SHALL resume prior work by importing the previous episode's evidence bundle and continuing from its obligation ledger, rather than re-deriving established results.

#### Scenario: Cold episode resumes from a bundle

- **WHEN** a worker starts on a task that has a prior evidence bundle and obligation ledger
- **THEN** it imports the bundle, reads the ledger, and continues with the still-open obligations instead of restarting the analysis

### Requirement: In-scope, in-containment action

Every target-touching action a worker takes SHALL first pass the scope authorization gate and SHALL execute inside the target's contained instance; a denied or uncontained action is not performed.

#### Scenario: Out-of-scope action not performed

- **WHEN** a worker would act on a target or action class the scope registry does not authorize
- **THEN** the worker does not perform the action and records the denial

#### Scenario: Action executes inside containment

- **WHEN** a worker performs an authorized target-touching action
- **THEN** it executes inside the target's contained instance, never against a live or out-of-box asset

### Requirement: Candidate-finding emission

When a worker observes a likely vulnerability, it SHALL emit a candidate finding carrying the hypothesis, supporting evidence, and reproduction leads, marked as unconfirmed for the verifier rather than asserted as a finding.

#### Scenario: Candidate emitted unconfirmed

- **WHEN** a worker's analysis suggests a likely vulnerability
- **THEN** it emits a candidate finding with hypothesis, evidence, and reproduction leads, marked unconfirmed, and does not report it as a confirmed finding
