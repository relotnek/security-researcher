# autoresearch — Autonomous Security Research System

An always-on autonomous security researcher. Given a **CVE or target model spec**, it works a target toward a reproducible proof-of-concept inside a contained environment (directed mode). Given a **bounty program and scope**, it continuously surfaces findings (discovery mode). It is built for authorized work only: owned devices, IoT, and public bug-bounty programs.

## The core idea

LLM agents are episodic — bounded context, they terminate. So the thing that is "always on" is **not an agent; it is the research state.** Disposable worker episodes read durable state, do a bounded chunk of analysis, write state back, and die. A driver keeps spawning them.

```
  +---------------------+
  |  DURABLE STATE      |  <- always on (JSON on disk + analysis bundles)
  |  engagements,       |
  |  findings, frontier |
  +----------+----------+
        ^          |
     (write)    (read)
        |          v
  +-----+----------+----+
  | ephemeral worker    |  <- disposable, spawned by the driver
  | episode (bounded)   |
  +---------------------+
```

## Architecture (layers / capabilities)

```
  L6 reporting        findings out (Linear / Slack / bounty drafts)   [not yet spec'd]
  L5 driver           always-on wake/dispatch + budget governor       [spec skeleton]
  L4 verifier         PoC-gated: no PoC, no finding                   [proposal]
  L3 worker-episode   ephemeral agents driving analysis (REA)         [implemented on branch]
  L2 frontier         best-first scored investigation queue           [implemented on branch]
  L1 durable state    the always-on substrate                         [implemented on main]
  L0.5 containment    isolation: Docker sandbox / isolated-net+VMs     [implemented on main]
  L0 scope-registry   authorization: deny-by-default fence            [implemented on main]
```

**Four invariants** every capability upholds (see `openspec/specs/system-overview/`):
1. **Ephemeral workers, durable state** — work survives episode boundaries; a cold agent resumes from disk.
2. **Double safety boundary** — every target-touching action passes BOTH scope authorization (what) AND containment isolation (where). Structural, not a prompt rule. All actions go through `ActionGuard`.
3. **PoC-gated findings** — nothing is reported as a finding without a reproducible proof-of-concept, detonated inside containment.
4. **Two modes on one substrate** — directed (CVE/target → PoC) and discovery (scope → stream of findings).

## Repository layout

```
  src/autoresearch/
    state.py            durable JSON state store (L1); one record per file, human-readable
    taxonomy.py         target classification -> containment profile
    scope.py            scope registry (L0): ActionClass, ScopeRegistry, ScopeGate
    audit.py            append-only JSONL audit log of boundary decisions
    boundary.py         ActionGuard -- the double safety boundary (scope AND containment)
    containment/
      manager.py        provisioning, snapshot, teardown; internal net + egress gateway
      docker.py         docker CLI helper
      images/           egress-gateway (default-deny proxy), vm-runner
  tests/                unittest; Docker-dependent tests gated by tests/docker_support.py
  openspec/
    specs/              the design-of-record: 7 capability specs
    changes/            active changes (proposals + applied deltas)
```

## Containment model

Every contained instance has the same network shape regardless of profile:

```
  workload --(internal net: no route out)-- egress gateway --(egress net)-- allowlisted hosts only
```

- **Code / software** targets → **Docker sandbox**.
- **Device / firmware / network** targets → **VM on an isolated segment**.
- Egress is **default-deny**; the allowlist is the only exception. The profile is chosen from the target's class and cannot be overridden by the caller.

## Getting started

Requires Python ≥ 3.11.

```bash
pip install -e .                      # editable install
python -m unittest discover tests     # run the test suite
```

Some containment/boundary tests require a working Docker daemon; they are skipped automatically when Docker is unavailable (see `tests/docker_support.py`).

## How the work is organized (OpenSpec)

This project is spec-driven with [OpenSpec](https://github.com/). The durable design lives in `openspec/specs/`; each unit of work is a *change* under `openspec/changes/` carrying a proposal, design, spec deltas, and tasks.

```bash
openspec list --specs                 # the 7 capabilities (design-of-record)
openspec list                         # active changes (work in flight)
openspec status --change <name>       # a change's artifacts + task progress
openspec show system-overview --type spec   # the cross-cutting invariants
```

Workflow commands (Claude Code skills): `/opsx:explore` (think), `/opsx:propose` (create a change + artifacts), `/opsx:apply` (implement tasks), `/opsx:sync` (promote spec deltas into `specs/`), `/opsx:archive` (finalize).

See **AGENTS.md** for the full operating contract (branch discipline, multi-agent rules, safety invariants to respect while coding).

## Current status

| Capability | Layer | State |
|---|---|---|
| durable state | L1 | implemented on `main` |
| scope-registry | L0 | implemented on `main` |
| containment | L0.5 | implemented on `main` |
| frontier | L2 | implemented on branch `frontier-scoring` (pending merge to `main`) |
| worker-episode | L3 | implemented on branch `worker-episode-pipeline` (pending merge) |
| verifier | L4 | proposal `verifier-impl` (not yet implemented) |
| driver | L5 | skeleton spec only |
| reporting | L6 | not yet spec'd (currently folded into the driver) |

`git log --oneline --graph --all` shows the live branch/merge state. `main` is the integration branch; each capability is implemented on its own branch and merged via PR.
