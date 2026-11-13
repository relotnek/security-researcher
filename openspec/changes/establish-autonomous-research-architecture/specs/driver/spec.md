# Spec Delta

## Purpose

The always-on orchestration layer: a scheduled process that wakes, dispatches worker episodes against the frontier, checkpoints state, governs spend, and applies mode-specific stop conditions.

<!-- SKELETON: the concrete scheduling substrate (scheduled cloud agent vs. loop)
     and the worker fan-out mechanism are to be detailed in the driver
     implementation change. -->

## ADDED Requirements

### Requirement: Scheduled wake and dispatch

The driver SHALL periodically wake, dispatch the highest-priority frontier tasks to worker episodes, integrate their results into durable state, and checkpoint.

#### Scenario: Driver wake cycle

- **WHEN** the driver wakes on its schedule
- **THEN** it dispatches top frontier tasks to workers, integrates returned results into durable state, and checkpoints before sleeping

### Requirement: Budget governance

The driver SHALL enforce a per-wake and a global budget cap on compute and token spend, and SHALL halt dispatch and alert when a cap is reached.

#### Scenario: Budget cap halts dispatch

- **WHEN** the global budget cap is reached
- **THEN** the driver halts further worker dispatch and raises an alert

### Requirement: Mode-specific stop conditions

The driver SHALL stop a directed-mode goal when a confirmed proof-of-concept is produced, and SHALL continue a discovery-mode engagement until its budget or scope is exhausted.

#### Scenario: Directed mode stops on confirmed PoC

- **WHEN** a directed-mode goal produces a verifier-confirmed proof-of-concept
- **THEN** the driver stops dispatching work toward that goal

#### Scenario: Discovery mode runs until exhausted

- **WHEN** a discovery-mode engagement has remaining budget and in-scope surface
- **THEN** the driver continues dispatching investigations and streaming confirmed findings
