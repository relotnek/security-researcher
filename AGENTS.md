# AGENTS.md — Operating contract for agents

This file is the authoritative guide for any AI agent (Claude Code or otherwise) working in this repository. Read it before making changes. `README.md` covers the project; this file covers **how to work on it**.

## What this project is

`autoresearch` is an always-on autonomous **security research** system for **authorized** targets only: owned devices, IoT, and public bug-bounty programs. It drives a target toward a reproducible proof-of-concept (directed mode) or continuously surfaces findings within a declared scope (discovery mode). See `README.md` and `openspec/specs/system-overview/` for the architecture.

Security context: this is legitimate, scoped, defensive-leaning research. The scope fence and containment are what keep it legitimate — never weaken them (see Invariants).

## Non-negotiable invariants

When you write or change code, these must hold. They are enforced structurally, not by prompt:

1. **Ephemeral workers, durable state.** Never hold research state only in an agent's context. It goes to the durable store (`state.py`) so a cold agent resumes from disk. Technical analysis state resumes from evidence bundles.
2. **Double safety boundary.** Every target-touching action goes through `ActionGuard` (`boundary.py`) and proceeds only if BOTH scope (`scope.py`) authorizes it AND a contained instance exists (`containment/`). The action executes *inside* that instance. Do not add a code path that touches a target outside this guard.
3. **Default-deny egress.** Contained workloads have no route out except an explicit allowlist via the egress gateway. Do not add host networking, bind mounts of the host, or a direct route for a workload.
4. **PoC-gated findings.** Only the verifier promotes a candidate to a finding, and only with a reproducible PoC detonated in containment. Workers emit *candidates*, never findings.
5. **Containment profile is derived, not chosen.** Target class (`taxonomy.py`) selects the profile; callers cannot override it. Code → Docker sandbox; device/firmware/network → VM on isolated segment.

If a task seems to require breaking one of these, stop and raise it — do not quietly work around a safety boundary.

## Spec-driven workflow (OpenSpec)

The design-of-record is `openspec/specs/` (7 capabilities). Work happens as *changes* under `openspec/changes/`.

- **Design lives in `specs/`, not in changes.** Changes are deltas; they archive. `openspec list --specs` + reading each spec is the current design.
- **Authoring ≠ implementing.** A change's spec deltas can be written without building; `tasks.md` tracks the build.
- `sync` promotes a change's spec deltas into `specs/` (design-of-record) without archiving. `archive` does it at completion. In this project we favor keeping `specs/` as **what is designed**; a capability's spec may be ahead of its code.
- Commands: `/opsx:explore`, `/opsx:propose`, `/opsx:apply`, `/opsx:sync`, `/opsx:archive`. Reorient with `openspec status --change <name>`.

Spec deltas use `## ADDED/MODIFIED/REMOVED Requirements`; scenarios need exactly 4 `#` and WHEN/THEN. Validate with `openspec validate <change> --strict`.

## Multi-agent / branch discipline

**Several agents work this repo in parallel.** The capabilities are mostly disjoint, which keeps it safe — but follow these rules:

- **`main` is the integration branch.** Do not develop directly on it beyond small additive things (docs, proposals). Each capability is implemented on its **own branch** (e.g. `foundation-state-scope-containment`, `frontier-scoring`, `worker-episode-pipeline`) and merged via PR.
- **Never `git add -A` blindly.** Another agent may have uncommitted work in the same tree. Stage only the specific files for your change (`git add openspec/changes/<name> src/autoresearch/<module>` …).
- **Don't modify another capability's spec while its change is mid-apply.** Two in-flight changes editing the same requirement collide at sync/archive (a `MODIFIED` delta's base goes stale). Partition work by capability; touch `system-overview` only when deliberately changing a cross-cutting invariant.
- **Proposals on `main`, implementations on branches.** A new `/opsx:propose` change (planning artifacts only) can land on `main`; its build happens on a branch.
- **Apply order follows dependencies:** foundation → frontier → worker-episode → verifier → driver → reporting. Workers depend on the frontier operations contract; the verifier depends on containment + the worker candidate shape.
- After fetching, use `git log --oneline --graph --all` to see the real state before branching or committing.

## Code conventions

- Python ≥ 3.11, standard library only so far (`pyproject.toml` has no runtime deps). Keep new runtime dependencies to a strong, stated need.
- `from __future__ import annotations`; dataclasses and `StrEnum` for typed records/enums, matching existing modules.
- Durable records are plain JSON, one file per record, human-readable — keep them so.
- Tests are `unittest` under `tests/`. Docker-dependent tests use `tests/docker_support.py` (`@requires_docker`, `ContainmentTestCase`) and must skip cleanly without Docker. Every behavior change lands its tests in the same change.
- Run `python -m unittest discover tests` before finishing.

## Picking this up cold

1. `git fetch --all --prune` then `git log --oneline --graph --all` — see what's merged vs. on branches.
2. `openspec list --specs` and `openspec list` — capabilities and changes in flight.
3. Read `openspec/specs/system-overview/spec.md` — the invariants above, in spec form.
4. `python -m unittest discover tests` — confirm a green baseline.
5. Pick the next capability by the apply order; `openspec status --change <name>` if a change already exists, else `/opsx:propose`.

## Attribution

Commit trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. PR descriptions end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. The user's own instructions take precedence.
