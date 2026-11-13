# containment Specification

## Purpose

The isolation substrate of the system: it provisions an isolated instance of the target appropriate to its class and confines all worker and verifier action inside it, so nothing ever touches a live or out-of-box asset.

## Requirements

### Requirement: Containment profile selection by target class

The system SHALL select a containment profile by target class: a Docker sandbox for code or software targets, and an isolated network segment with VMs (emulated firmware or a physical unit on the segment) for device, firmware, or network targets.

#### Scenario: Code target provisioned in a Docker sandbox

- **WHEN** the target is code or software
- **THEN** the system provisions a Docker sandbox instance for it

#### Scenario: Device target provisioned in an isolated segment

- **WHEN** the target is a device, firmware, or network target
- **THEN** the system provisions the target on an isolated network segment with VMs and no route to production or the internet except an explicit allowlist

### Requirement: Default-deny egress

A contained instance SHALL deny all outbound network traffic except to hosts on an explicit allowlist.

#### Scenario: Non-allowlisted egress blocked

- **WHEN** code inside a contained instance attempts to reach a host that is not on the allowlist
- **THEN** the outbound connection is blocked

### Requirement: Snapshot and teardown

Containment SHALL be able to snapshot an instance's state for reproducibility and tear down ephemeral instances when work completes.

#### Scenario: Snapshot reproduces a confirmed finding

- **WHEN** a finding is confirmed against a contained instance
- **THEN** a retained snapshot can reconstitute the instance state that reproduces the finding

#### Scenario: Ephemeral instance torn down

- **WHEN** work against an ephemeral contained instance completes
- **THEN** the instance's transient resources are released while any retained snapshot persists
