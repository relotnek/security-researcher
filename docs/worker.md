# Worker episodes

The worker (L3) is the agent that performs the actual analysis. It runs as a
series of **bounded episodes** over durable state, so an ephemeral process can
resume a deep investigation cold — picking up exactly where the previous episode
stopped — without re-deriving what is already established.

## Episode lifecycle

Every episode follows the same five stages regardless of target class. Only the
*pipeline body* (what "work" does) differs by class.

| Stage | What happens |
|-------|--------------|
| **load** | Load durable state and any prior evidence bundle for the task. |
| **plan** | *First episode only.* Seed the obligation ledger — the checklist of what remains to prove — from the selected pipeline. |
| **work** | Run bounded pipeline work: take open obligations in turn, run each one's target-touching action through the action guard, record observations, emit candidate findings, and expand the ledger — until the resource budget is spent or no obligation remains open. |
| **checkpoint** | Export the evidence bundle and obligation ledger. Done incrementally after every obligation, so a dying episode loses at most one obligation's increment. |
| **terminate** | Exit. The next episode resumes from the bundle. |

`autoresearch.worker.STAGES` is the canonical list of these stage names.

### Inputs

An episode is dispatched with:

- `engagement_id` — the engagement the work belongs to.
- `target_id` — the target to analyse (a stored `Target`).
- `task_id` — the investigation task; also keys the evidence bundle for resume.
- `instance_id` — the **already-provisioned** contained instance of the target.
  The worker never provisions or tears down containment; the driver does.
- `budget` — a `Budget`, a bound on the episode's work counted in
  target-touching actions.

### Outputs

- `Observation` records — what each analysis step saw (durable).
- `Candidate` findings — unconfirmed candidates for the verifier (see below).
- An updated `EvidenceBundle` — the resumable checkpoint.
- An `EpisodeResult` summarising the episode, with `reason` either `budget`
  (stopped at the budget, obligations still open) or `complete` (nothing left
  open).

## Pipeline selection by target class

The target's class selects both its containment profile and its analysis
pipeline, so the two stay aligned.

| Target class | Pipeline | Body |
|--------------|----------|------|
| firmware / device | `FirmwarePipeline` | extraction + native/binary analysis of the image |
| mobile | `MobilePipeline` | app / runtime component analysis |
| web | `WebPipeline` | capture + request/endpoint analysis |
| native / software | `NativePipeline` | binary / decompilation analysis |

`network`-type targets are device-class and share the firmware/device pipeline.

## Cross-episode resume

The durable handoff between episodes is the **evidence bundle** plus a
**reconstruction-obligation ledger**:

- The bundle (`eb-<task_id>`) holds reconstitutable `analysis_state`, the ids of
  the observations gathered, and the ledger.
- Each ledger entry records one obligation — what must be established — with a
  status of `open` or `closed`, and which episode opened and closed it.

A resuming episode imports the bundle, **does not re-plan**, and works only the
still-open obligations; closed obligations are never re-derived. An obligation's
`op` tells the pipeline what action to run; analysis_state carries forward the
facts a later step depends on.

## In scope, in containment

Every target-touching action a worker takes goes through
`WorkerContext.action`, which calls `autoresearch.boundary.ActionGuard`. The
action runs only if **both** boundaries hold: the scope gate authorizes the
action class on the target, and the action executes **inside the target's
contained instance**. A denied or uncontained action is not performed, and the
denial is recorded. A pipeline body has no other way to touch the target.

## Candidates, never findings

When analysis suggests a likely vulnerability, the worker emits a `Candidate`
carrying a **hypothesis**, supporting **evidence**, and **reproduction leads**,
always marked `unconfirmed`. A worker never writes a confirmed finding — the
`Candidate` record cannot even hold any status other than `unconfirmed`. Only
the verifier, with a reproducible proof-of-concept in containment, promotes a
candidate to a finding. The candidate records are the verifier's intake queue.
