# Proposal

## Why

Security research on owned devices, IoT, and public bounty targets is bounded by researcher time and attention. An always-on autonomous researcher can continuously drive a target toward a proof-of-concept — but only if the work survives the episodic nature of LLM agents and stays rigorously inside authorization and containment boundaries. This change establishes the architecture-of-record for that system before any of it is built.

## What Changes

- Establish the **architecture-of-record** for an autonomous security research system as a set of capability specs.
- Adopt the core inversion: **ephemeral worker agents, durable research state** — the system is "always on" because its state persists, not because any agent is long-lived.
- Define **two operating modes on one substrate**: directed (given a CVE or target model spec, work toward a PoC) and discovery (given a bounty program and scope, continuously surface findings).
- Define a **double safety boundary**: a logical scope fence (what may be touched) and physical/network containment (where action may happen), both structural rather than prompt-level.
- Adopt **PoC-gated findings**: nothing is reported as a finding without a reproducible proof-of-concept, detonated inside containment.
- **Scope of this change (foundation only):** author the full design-of-record (seven capability specs) but implement only the foundation — the durable-state substrate, the scope fence, and containment provisioning. Frontier scoring, worker episodes, the verifier, and the driver are authored as skeleton contracts here and implemented by later changes.

## Capabilities

### New Capabilities
- `system-overview`: The cross-cutting architecture map and the invariants every other capability upholds (ephemeral/durable inversion, double safety boundary, PoC-gated findings, two modes).
- `scope-registry`: The authorization boundary — in-scope and forbidden assets and allowed action classes per engagement, enforced deny-by-default before any target action.
- `containment`: The isolation substrate — a Docker sandbox for code targets, an isolated network segment and VMs for device/firmware/network targets; default-deny egress, snapshot, teardown.
- `frontier`: The prioritized investigation backlog that drives best-first search, with scoring and dead-end pruning.
- `worker-episode`: The ephemeral, bounded research agents that read durable state, drive analysis (via REA), and expand the frontier.
- `verifier`: Adversarial confirmation that turns candidates into PoC-backed findings, with the PoC detonated inside containment.
- `driver`: The always-on orchestration layer — scheduled wake, worker dispatch, checkpointing, budget governance, and mode-specific stop conditions.

### Modified Capabilities
<!-- None. Greenfield system. -->

## Impact

- Greenfield system; no existing code or specs are affected.
- Depends on: the REA reverse-engineering toolkit, a container/VM substrate (Docker, isolated network segment, VMs), a durable state store (files and/or issue/knowledge connectors), and scheduled-agent orchestration for the always-on driver.
- Establishes the capability boundaries that all subsequent implementation changes will slot into.
