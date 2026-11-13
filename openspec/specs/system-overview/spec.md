# system-overview Specification

## Purpose

Defines the cross-cutting architecture of the autonomous security researcher and the invariants every other capability must uphold, so the design stays coherent as capabilities are built incrementally.

## Requirements

### Requirement: Ephemeral workers, durable state

The system SHALL persist research state outside any agent, such that a freshly started agent with no prior context can resume in-progress work from that state.

#### Scenario: Cold resume after an episode ends

- **WHEN** a worker episode terminates and a new episode later starts for the same goal
- **THEN** the new episode loads the persisted research state and continues from where the previous one stopped, without re-deriving prior results

### Requirement: Double safety boundary on every action

Every target-touching action SHALL pass both scope authorization and containment isolation before it proceeds; failing either boundary blocks the action.

#### Scenario: Action blocked by either boundary

- **WHEN** a worker attempts an action on a target
- **THEN** the action proceeds only if the scope registry authorizes it AND it occurs inside containment, and is otherwise blocked and logged

### Requirement: PoC-gated findings

A candidate SHALL NOT be reported as a finding unless a reproducible proof-of-concept for it exists.

#### Scenario: Candidate without a PoC is not a finding

- **WHEN** a candidate finding has no reproducible proof-of-concept
- **THEN** the system does not report it as a finding and returns it for further investigation

### Requirement: Two operating modes on one substrate

The system SHALL support a directed mode (seeded with a CVE or target model spec, working toward a PoC) and a discovery mode (seeded with a bounty program and scope, streaming findings), using the same underlying capabilities.

#### Scenario: Mode selected by seed input

- **WHEN** the system is seeded with a CVE or target model spec
- **THEN** it runs in directed mode toward a proof-of-concept
- **WHEN** the system is seeded with a bounty program and scope
- **THEN** it runs in discovery mode, continuously surfacing candidate findings
