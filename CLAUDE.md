# CLAUDE.md

Guidance for Claude Code in this repository.

**Read `AGENTS.md` first — it is the authoritative operating contract** (safety invariants, OpenSpec workflow, branch discipline, code conventions). This file adds only Claude Code specifics. `README.md` covers the project itself.

## TL;DR

`autoresearch` is an always-on autonomous **security research** system for **authorized** targets only (owned devices, IoT, public bounty programs). It is spec-driven with OpenSpec: the design-of-record is `openspec/specs/`; work happens as *changes* under `openspec/changes/`.

## The five invariants you must never break

1. Ephemeral workers, **durable state** (`state.py`).
2. **Double safety boundary** — every target action via `ActionGuard` (`boundary.py`): scope AND containment.
3. **Default-deny egress** from contained workloads.
4. **PoC-gated findings** — only the verifier confirms, with a PoC in containment.
5. **Containment profile is derived** from target class, never caller-chosen.

Full rationale in `AGENTS.md` → Non-negotiable invariants. If a task seems to need breaking one, stop and raise it.

## Working here with Claude Code

- **OpenSpec skills:** `/opsx:explore` (think, no writes), `/opsx:propose` (new change + artifacts), `/opsx:apply` (implement tasks), `/opsx:sync` (promote spec deltas into `specs/`), `/opsx:archive`. Reorient any time with `openspec status --change <name>`.
- **Explore mode does not implement.** `/opsx:explore` is for thinking and capturing spec/design artifacts only — it never writes code.
- **This is a multi-agent repo.** Others may be applying changes on their own branches in the same tree. Stage only your change's files — never `git add -A`. Don't edit another capability's spec while its change is mid-apply. See `AGENTS.md` → Multi-agent / branch discipline.
- **Branches:** `main` integrates; each capability is built on its own branch and merged via PR. Apply order: foundation → frontier → worker-episode → verifier → driver → reporting.
- **REA MCP** (reverse-engineering tools) is the intended analysis engine for the `worker-episode` pipelines (firmware extraction, Frida/GDB, native/web/mobile). Prefer it over ad-hoc shell for target analysis.

## Build & test

```bash
pip install -e .                      # Python >= 3.11, stdlib-only so far
python -m unittest discover tests     # Docker-gated tests skip without a daemon
```
Run the tests before finishing any code change.

## Attribution

Commits end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`; PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
