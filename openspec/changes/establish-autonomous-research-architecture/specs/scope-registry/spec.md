# Spec Delta

## Purpose

The authorization boundary of the system: it records which assets and action classes are permitted for an engagement and enforces that boundary deny-by-default before any target-touching action.

## ADDED Requirements

### Requirement: Engagement scope declaration

The system SHALL maintain, per engagement, a registry of in-scope assets, explicitly forbidden assets, and the action classes permitted against them.

#### Scenario: Scope recorded for an engagement

- **WHEN** an engagement is created with a set of in-scope and out-of-scope assets and allowed action classes
- **THEN** the registry stores them and they are retrievable for authorization checks

### Requirement: Deny-by-default action authorization

Before any target-touching action, the system SHALL verify that the target asset is in scope and the action class is permitted, denying the action if either check fails or is indeterminate.

#### Scenario: Out-of-scope target denied

- **WHEN** a worker requests an action on a target that is not in the engagement's in-scope set
- **THEN** the action is denied and the denial is logged

#### Scenario: Forbidden action class denied

- **WHEN** a worker requests an action whose class is not in the engagement's permitted set
- **THEN** the action is denied and the denial is logged
