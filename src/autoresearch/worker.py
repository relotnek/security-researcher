"""The worker (L3): the agent that performs the actual analysis.

A worker runs as a sequence of **bounded episodes** over durable state, so an
ephemeral process with no prior context can pick up exactly where the last one
stopped. Every episode follows the same fixed lifecycle regardless of target
class; only the *pipeline body* differs by class::

    load  ->  plan  ->  work  ->  checkpoint  ->  terminate

* **load**       load durable state and any prior evidence bundle for the task.
* **plan**       (first episode only) seed the obligation ledger - the checklist
                 of what remains to prove - for this target's pipeline.
* **work**       run bounded pipeline work: take open obligations in turn, run
                 each one's target-touching action *through the action guard*,
                 record observations, emit candidate findings, and expand the
                 ledger - until the resource budget is spent or no obligation
                 remains open.
* **checkpoint** export the evidence bundle and obligation ledger (done
                 incrementally after every obligation, so a dying episode loses
                 at most one obligation's increment).
* **terminate**  exit; the next episode resumes from the bundle.

Inputs:  an engagement, a target, a task id, a contained instance id, a budget.
Outputs: durable :class:`Observation` records, :class:`Candidate` findings
         (unconfirmed, for the verifier), and an updated :class:`EvidenceBundle`.

Two invariants are structural here, not advisory:

* **In scope, in containment** (:class:`WorkerContext.action`): every
  target-touching action passes through :class:`autoresearch.boundary.ActionGuard`,
  so it runs only if the scope gate authorizes it *and* it executes inside the
  target's contained instance. A denied or uncontained action is not performed.
* **Candidates, never findings** (:class:`WorkerContext.emit_candidate`): a
  worker emits *candidates* (hypothesis + evidence + reproduction leads), always
  unconfirmed. Only the verifier, with a reproducible PoC in containment,
  promotes one to a finding. A worker never writes a confirmed finding.

See docs/worker.md for the task shape and the per-class pipeline summaries.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from .audit import AuditLog
from .boundary import ActionGuard, ActionResult
from .scope import ActionClass
from .state import FrontierTask, Record, StateStore, Target, new_id, now
from .taxonomy import TargetType

# The fixed episode lifecycle. docs/worker.md and the module docstring above
# both enumerate these; a test holds the three in sync.
STAGES = ("load", "plan", "work", "checkpoint", "terminate")

CANDIDATE_UNCONFIRMED = "unconfirmed"


class WorkerError(RuntimeError):
    """A worker episode cannot run (bad dispatch, missing target)."""


# -- durable records -------------------------------------------------------


@dataclass
class Observation(Record):
    """Something an analysis step saw. The raw material candidates are built
    from; persisted so a later episode has it without re-deriving it."""

    kind: ClassVar[str] = "observations"

    id: str
    engagement_id: str
    target_id: str
    task_id: str
    episode_id: str
    pipeline: str
    category: str  # extraction | strings | secret | endpoint | ...
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    regions: list[str] = field(default_factory=list)
    likely_vuln: bool = False
    created_at: str = field(default_factory=now)


@dataclass
class Candidate(Record):
    """An unconfirmed candidate finding emitted for the verifier. A worker
    never produces a confirmed finding; this is the whole of its finding-side
    output, and the verifier's intake queue."""

    kind: ClassVar[str] = "candidates"

    id: str
    engagement_id: str
    target_id: str
    task_id: str
    hypothesis: str
    evidence: list[str] = field(default_factory=list)
    reproduction_leads: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    source_episode: str = ""
    status: str = CANDIDATE_UNCONFIRMED  # always unconfirmed; the verifier decides
    created_at: str = field(default_factory=now)

    def __post_init__(self) -> None:
        super().__post_init__()
        # A worker cannot assert a finding: the only state it may emit is
        # "unconfirmed". This is the structural half of "candidates, never findings".
        if self.status != CANDIDATE_UNCONFIRMED:
            raise ValueError("a worker emits only unconfirmed candidates")


@dataclass
class EvidenceBundle(Record):
    """The resumable checkpoint: reconstitutable analysis state plus a
    reconstruction-obligation ledger. One per task (id ``eb-<task_id>``), so a
    cold episode finds it by the task it was dispatched on.

    Each ledger entry is a mapping::

        {"id", "op", "statement", "status": "open"|"closed",
         "opened_in_episode", "closed_in_episode", "note", ...}
    """

    kind: ClassVar[str] = "evidence_bundles"

    id: str
    engagement_id: str
    target_id: str
    task_id: str
    pipeline: str = ""
    episode_count: int = 0
    analysis_state: dict[str, Any] = field(default_factory=dict)
    observation_ids: list[str] = field(default_factory=list)
    obligations: list[dict[str, Any]] = field(default_factory=list)  # the ledger
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    def open_obligations(self) -> list[dict[str, Any]]:
        return [o for o in self.obligations if o["status"] == "open"]

    def closed_obligations(self) -> list[dict[str, Any]]:
        return [o for o in self.obligations if o["status"] == "closed"]


def bundle_id(task_id: str) -> str:
    return f"eb-{task_id}"


# -- resource budget -------------------------------------------------------


@dataclass
class Budget:
    """A bound on the work one episode may do, counted in target-touching
    actions. When it is spent, the episode checkpoints and terminates."""

    max_actions: int
    spent: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.max_actions, int) or self.max_actions < 1:
            raise WorkerError("budget max_actions must be a positive integer")

    def can_spend(self) -> bool:
        return self.spent < self.max_actions

    def remaining(self) -> int:
        return max(0, self.max_actions - self.spent)

    def spend(self) -> None:
        if not self.can_spend():
            raise WorkerError("budget exhausted")
        self.spent += 1


# -- episode context -------------------------------------------------------


class WorkerContext:
    """Everything a pipeline body is allowed to do, and the only way it can do
    it. A pipeline never touches Docker, the store, or the target directly - it
    goes through this context, so the fences and the ledger are enforced in one
    place."""

    def __init__(
        self,
        *,
        worker: "Worker",
        target: Target,
        task_id: str,
        instance_id: str | None,
        bundle: EvidenceBundle,
        budget: Budget,
        episode_id: str,
    ) -> None:
        self._worker = worker
        self.target = target
        self.engagement_id = target.engagement_id
        self.task_id = task_id
        self.instance_id = instance_id
        self.bundle = bundle
        self.budget = budget
        self.episode_id = episode_id
        self.observations: list[Observation] = []
        self.candidates: list[Candidate] = []

    # -- target-touching action (the fence) --------------------------------

    def action(self, action_class: ActionClass | str, argv: list[str]) -> ActionResult:
        """Run a target-touching action. Routed through the action guard, so it
        happens only if scope authorizes it and it executes inside the target's
        contained instance; otherwise it is blocked and not performed. Costs one
        unit of budget whether or not it is allowed (the attempt is the work)."""
        self.budget.spend()
        result = self._worker.guard.run(
            engagement_id=self.engagement_id,
            target_id=self.target.id,
            action_class=action_class,
            instance_id=self.instance_id,
            argv=list(argv),
        )
        if not result.allowed:
            self._worker.audit.record(
                "worker.action_blocked",
                task_id=self.task_id,
                target_id=self.target.id,
                action_class=str(action_class),
                blocked_by=list(result.blocked_by),
            )
        return result

    # -- outputs -----------------------------------------------------------

    def observe(
        self,
        category: str,
        summary: str,
        *,
        data: dict[str, Any] | None = None,
        regions: list[str] | None = None,
        likely_vuln: bool = False,
    ) -> Observation:
        obs = Observation(
            id=new_id("obs"),
            engagement_id=self.engagement_id,
            target_id=self.target.id,
            task_id=self.task_id,
            episode_id=self.episode_id,
            pipeline=self.bundle.pipeline,
            category=category,
            summary=summary,
            data=data or {},
            regions=list(regions or []),
            likely_vuln=likely_vuln,
        )
        self._worker.store.put(obs)
        self.bundle.observation_ids.append(obs.id)
        self.observations.append(obs)
        self._worker.audit.record(
            "worker.observation", task_id=self.task_id, observation_id=obs.id,
            category=category, likely_vuln=likely_vuln,
        )  # fmt: skip
        return obs

    def emit_candidate(
        self,
        hypothesis: str,
        *,
        evidence: list[str],
        reproduction_leads: list[str],
        regions: list[str] | None = None,
    ) -> Candidate:
        """Emit an unconfirmed candidate finding for the verifier."""
        candidate = Candidate(
            id=new_id("cnd"),
            engagement_id=self.engagement_id,
            target_id=self.target.id,
            task_id=self.task_id,
            hypothesis=hypothesis,
            evidence=list(evidence),
            reproduction_leads=list(reproduction_leads),
            regions=list(regions or []),
            source_episode=self.episode_id,
        )
        self._worker.store.put(candidate)
        self.candidates.append(candidate)
        self._worker.audit.record(
            "worker.candidate", task_id=self.task_id, candidate_id=candidate.id,
            hypothesis=hypothesis,
        )  # fmt: skip
        return candidate

    # -- obligation ledger -------------------------------------------------

    def open_obligation(self, op: str, statement: str, **extra: Any) -> dict[str, Any]:
        obligation = {
            "id": new_id("obl"),
            "op": op,
            "statement": statement,
            "status": "open",
            "opened_in_episode": self.episode_id,
            "closed_in_episode": None,
            "note": "",
            **extra,
        }
        self.bundle.obligations.append(obligation)
        return obligation

    def next_open_obligation(self) -> dict[str, Any] | None:
        for obligation in self.bundle.obligations:
            if obligation["status"] == "open":
                return obligation
        return None

    def open_obligations(self) -> list[dict[str, Any]]:
        return self.bundle.open_obligations()

    def close_obligation(self, obligation: dict[str, Any], *, note: str = "") -> None:
        obligation["status"] = "closed"
        obligation["closed_in_episode"] = self.episode_id
        if note:
            obligation["note"] = note
        self.checkpoint()  # persist progress obligation-by-obligation

    def remember(self, key: str, value: Any) -> None:
        """Record a derived fact in analysis state, so a later episode has it
        without re-deriving it."""
        self.bundle.analysis_state[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        return self.bundle.analysis_state.get(key, default)

    def checkpoint(self) -> None:
        self.bundle.updated_at = now()
        self._worker.store.put(self.bundle)


# -- pipelines -------------------------------------------------------------


class PipelineKind(StrEnum):
    FIRMWARE = "firmware"  # firmware / device
    MOBILE = "mobile"
    WEB = "web"
    NATIVE = "native"  # native / software


class Pipeline:
    """A target-class analysis strategy. ``plan`` seeds the obligation ledger
    once; ``step`` works one obligation. The worker drives the loop and owns the
    budget and lifecycle, so a pipeline is just these two methods."""

    kind: ClassVar[PipelineKind]

    def plan(self, ctx: WorkerContext) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def step(self, ctx: WorkerContext, obligation: dict[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError


_SECRET_RE = r"password|passwd|api[_-]?key|secret|private key|BEGIN [A-Z ]*PRIVATE KEY"
_WEB_VULN_RE = re.compile(r"debug|admin|\.\./|' or |<script|cmd=|;\s*\w|%27", re.IGNORECASE)


class FirmwarePipeline(Pipeline):
    """Firmware / device: extraction + native/binary analysis of the image.

    Orchestrates contained extraction and binary inspection, then a credential
    scan that turns a hit into a candidate finding.
    """

    kind: ClassVar[PipelineKind] = PipelineKind.FIRMWARE
    IMAGE = "/target"
    ACTION = ActionClass.STATIC_ANALYSIS

    def plan(self, ctx: WorkerContext) -> None:
        ctx.open_obligation("extract", "Extract and enumerate the firmware image's contents")
        ctx.open_obligation("strings", "Enumerate identifying strings in the firmware")
        ctx.open_obligation("secret_scan", "Rule out hardcoded credentials in the firmware")

    def step(self, ctx: WorkerContext, obligation: dict[str, Any]) -> None:
        op = obligation["op"]
        if op == "extract":
            result = ctx.action(self.ACTION, ["sh", "-c", f"ls -1 {self.IMAGE}"])
            files = result.stdout.split() if result.allowed else []
            ctx.remember("extracted_files", files)
            ctx.observe("extraction", f"extracted {len(files)} top-level artifact(s)",
                        data={"files": files}, regions=["firmware/filesystem"])  # fmt: skip
        elif op == "strings":
            result = ctx.action(
                self.ACTION, ["sh", "-c", f"grep -i -E 'version|ssid|http|model' {self.IMAGE}/* 2>/dev/null || true"]
            )
            lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
            ctx.observe("strings", f"{len(lines)} identifying string(s)",
                        data={"strings": lines[:50]}, regions=["firmware/strings"])  # fmt: skip
        elif op == "secret_scan":
            result = ctx.action(
                self.ACTION, ["sh", "-c", f"grep -i -n -E '{_SECRET_RE}' {self.IMAGE}/* 2>/dev/null || true"]
            )
            hits = [ln for ln in result.stdout.splitlines() if ln.strip()]
            if hits:
                ctx.observe("secret", f"{len(hits)} possible hardcoded credential(s)",
                            data={"matches": hits}, regions=["firmware/credentials"], likely_vuln=True)  # fmt: skip
                ctx.emit_candidate(
                    "Hardcoded credential or key embedded in firmware image",
                    evidence=hits,
                    reproduction_leads=[f"grep -i -E '{_SECRET_RE}' over the extracted firmware"],
                    regions=["firmware/credentials"],
                )
            else:
                ctx.observe("secret", "no hardcoded credentials matched",
                            regions=["firmware/credentials"])  # fmt: skip


class WebPipeline(Pipeline):
    """Web: capture + request/endpoint analysis.

    Captures the app's endpoints, then analyses each one, raising a candidate
    for an endpoint whose shape suggests an injection or exposed-debug surface.
    """

    kind: ClassVar[PipelineKind] = PipelineKind.WEB
    MANIFEST = "/target/endpoints.txt"
    CAPTURE = ActionClass.DYNAMIC_ANALYSIS
    ANALYZE = ActionClass.DYNAMIC_ANALYSIS

    def plan(self, ctx: WorkerContext) -> None:
        ctx.open_obligation("capture", "Capture the application's reachable endpoints")

    def step(self, ctx: WorkerContext, obligation: dict[str, Any]) -> None:
        op = obligation["op"]
        if op == "capture":
            result = ctx.action(self.CAPTURE, ["sh", "-c", f"cat {self.MANIFEST} 2>/dev/null || true"])
            endpoints = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
            ctx.remember("endpoints", endpoints)
            ctx.observe("endpoints", f"captured {len(endpoints)} endpoint(s)",
                        data={"endpoints": endpoints}, regions=["web/surface"])  # fmt: skip
            for endpoint in endpoints:
                ctx.open_obligation("analyze_endpoint", f"Analyze endpoint {endpoint}", endpoint=endpoint)
        elif op == "analyze_endpoint":
            endpoint = obligation["endpoint"]
            region = f"web/endpoint{endpoint.split('?')[0]}"
            result = ctx.action(self.ANALYZE, ["sh", "-c", f"printf '%s' {_sh_quote(endpoint)}"])
            suspicious = bool(_WEB_VULN_RE.search(endpoint))
            ctx.observe("endpoint", f"analyzed {endpoint}",
                        data={"endpoint": endpoint, "echoed": result.stdout}, regions=[region],
                        likely_vuln=suspicious)  # fmt: skip
            if suspicious:
                ctx.emit_candidate(
                    f"Endpoint {endpoint} exposes an injectable or debug parameter",
                    evidence=[f"endpoint shape: {endpoint}"],
                    reproduction_leads=[f"issue a request to {endpoint} against the contained app"],
                    regions=[region],
                )


class NativePipeline(Pipeline):
    """Native / software: binary / decompilation analysis of a sample artifact."""

    kind: ClassVar[PipelineKind] = PipelineKind.NATIVE
    ARTIFACT = "/target"
    ACTION = ActionClass.STATIC_ANALYSIS

    def plan(self, ctx: WorkerContext) -> None:
        ctx.open_obligation("inventory", "Inventory the artifact's files and entry points")
        ctx.open_obligation("unsafe_calls", "Rule out obviously unsafe native calls")

    def step(self, ctx: WorkerContext, obligation: dict[str, Any]) -> None:
        op = obligation["op"]
        if op == "inventory":
            result = ctx.action(self.ACTION, ["sh", "-c", f"ls -1 {self.ARTIFACT}"])
            files = result.stdout.split() if result.allowed else []
            ctx.remember("files", files)
            ctx.observe("inventory", f"{len(files)} artifact file(s)",
                        data={"files": files}, regions=["native/files"])  # fmt: skip
        elif op == "unsafe_calls":
            result = ctx.action(
                self.ACTION,
                ["sh", "-c", f"grep -n -E 'system\\(|exec[lv]|strcpy|gets\\(|sprintf\\(' {self.ARTIFACT}/* 2>/dev/null || true"],
            )
            hits = [ln for ln in result.stdout.splitlines() if ln.strip()]
            if hits:
                ctx.observe("unsafe_call", f"{len(hits)} unsafe call site(s)",
                            data={"matches": hits}, regions=["native/unsafe"], likely_vuln=True)  # fmt: skip
                ctx.emit_candidate(
                    "Use of an unsafe native call on attacker-influenced input",
                    evidence=hits,
                    reproduction_leads=["review the flagged call sites for tainted arguments"],
                    regions=["native/unsafe"],
                )
            else:
                ctx.observe("unsafe_call", "no unsafe call sites matched", regions=["native/unsafe"])


class MobilePipeline(Pipeline):
    """Mobile: app / runtime analysis of an unpacked app."""

    kind: ClassVar[PipelineKind] = PipelineKind.MOBILE
    APP = "/target"
    ACTION = ActionClass.STATIC_ANALYSIS

    def plan(self, ctx: WorkerContext) -> None:
        ctx.open_obligation("components", "Inventory the app's components")
        ctx.open_obligation("exported", "Rule out improperly exported components")

    def step(self, ctx: WorkerContext, obligation: dict[str, Any]) -> None:
        op = obligation["op"]
        if op == "components":
            result = ctx.action(self.ACTION, ["sh", "-c", f"ls -1 {self.APP}"])
            files = result.stdout.split() if result.allowed else []
            ctx.remember("components", files)
            ctx.observe("components", f"{len(files)} component file(s)",
                        data={"files": files}, regions=["mobile/components"])  # fmt: skip
        elif op == "exported":
            result = ctx.action(
                self.ACTION,
                ["sh", "-c", f"grep -i -n -E 'exported=.?true|android:permission' {self.APP}/* 2>/dev/null || true"],
            )
            hits = [ln for ln in result.stdout.splitlines() if ln.strip()]
            if any("exported" in h.lower() and "true" in h.lower() for h in hits):
                ctx.observe("exported", "exported component without permission guard",
                            data={"matches": hits}, regions=["mobile/exported"], likely_vuln=True)  # fmt: skip
                ctx.emit_candidate(
                    "Exported mobile component reachable without a permission guard",
                    evidence=hits,
                    reproduction_leads=["invoke the exported component from an unprivileged context"],
                    regions=["mobile/exported"],
                )
            else:
                ctx.observe("exported", "no improperly exported components matched",
                            regions=["mobile/exported"])  # fmt: skip


_PIPELINE_BY_TYPE: dict[TargetType, type[Pipeline]] = {
    TargetType.FIRMWARE: FirmwarePipeline,
    TargetType.DEVICE: FirmwarePipeline,
    TargetType.NETWORK: FirmwarePipeline,  # device-class: shares the firmware/device pipeline
    TargetType.MOBILE_APP: MobilePipeline,
    TargetType.WEB_APP: WebPipeline,
    TargetType.BINARY: NativePipeline,
    TargetType.SOURCE_CODE: NativePipeline,
}


def select_pipeline(target: Target) -> Pipeline:
    """Select the analysis pipeline for a target from its class. Unknown types
    cannot be routed (the taxonomy would already have rejected one)."""
    return _PIPELINE_BY_TYPE[TargetType(target.target_type)]()


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


# -- the worker ------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeResult:
    bundle: EvidenceBundle
    episode_id: str
    pipeline: str
    observations: list[Observation]
    candidates: list[Candidate]
    reason: str  # "budget" | "complete"
    budget_spent: int


class Worker:
    """Runs bounded episodes against a contained target. The driver provisions
    containment and dispatches the worker with the instance id; the worker never
    provisions or tears down - it only works inside the instance it is given."""

    STAGES: ClassVar[tuple[str, ...]] = STAGES

    def __init__(self, store: StateStore, guard: ActionGuard, audit: AuditLog) -> None:
        self.store = store
        self.guard = guard
        self.audit = audit

    def run_episode(
        self,
        *,
        engagement_id: str,
        target_id: str,
        task_id: str,
        instance_id: str | None,
        budget: Budget,
    ) -> EpisodeResult:
        """Run one episode: select the pipeline by target class and drive it
        through the fixed lifecycle within ``budget``."""
        target = self._require_target(engagement_id, target_id)
        return self.run_pipeline(
            select_pipeline(target), target=target, task_id=task_id, instance_id=instance_id, budget=budget
        )

    def run_pipeline(
        self,
        pipeline: Pipeline,
        *,
        target: Target,
        task_id: str,
        instance_id: str | None,
        budget: Budget,
    ) -> EpisodeResult:
        """Drive ``pipeline`` through the lifecycle against ``target``. Used
        directly to exercise a specific pipeline body; :meth:`run_episode`
        selects the pipeline from the target class and calls through here."""
        episode_id = new_id("ep")
        self._stage("load", task_id, episode_id)
        bundle = self._load_bundle(target, task_id, str(pipeline.kind))
        bundle.episode_count += 1
        ctx = WorkerContext(
            worker=self, target=target, task_id=task_id, instance_id=instance_id,
            bundle=bundle, budget=budget, episode_id=episode_id,
        )  # fmt: skip
        self.audit.record(
            "worker.episode_start", task_id=task_id, episode_id=episode_id,
            target_id=target.id, pipeline=str(pipeline.kind), episode_count=bundle.episode_count,
            budget=budget.max_actions, resuming=bool(bundle.obligations),
        )  # fmt: skip

        if not bundle.obligations:  # first episode on this task plans the ledger
            self._stage("plan", task_id, episode_id)
            pipeline.plan(ctx)
            ctx.checkpoint()

        self._stage("work", task_id, episode_id)
        reason = self._work(pipeline, ctx)

        self._stage("checkpoint", task_id, episode_id)
        ctx.checkpoint()
        self._link_checkpoint(task_id, bundle)

        self._stage("terminate", task_id, episode_id)
        self.audit.record(
            "worker.episode_end", task_id=task_id, episode_id=episode_id, reason=reason,
            budget_spent=budget.spent, observations=len(ctx.observations), candidates=len(ctx.candidates),
            open_obligations=len(ctx.open_obligations()),
        )  # fmt: skip
        return EpisodeResult(
            bundle=bundle, episode_id=episode_id, pipeline=str(pipeline.kind),
            observations=ctx.observations, candidates=ctx.candidates,
            reason=reason, budget_spent=budget.spent,
        )  # fmt: skip

    # -- internals ---------------------------------------------------------

    def _work(self, pipeline: Pipeline, ctx: WorkerContext) -> str:
        """The bounded work loop: take open obligations in turn until the budget
        is spent or nothing remains open."""
        while ctx.budget.can_spend():
            obligation = ctx.next_open_obligation()
            if obligation is None:
                return "complete"
            pipeline.step(ctx, obligation)
            ctx.close_obligation(obligation)
        return "budget" if ctx.open_obligations() else "complete"

    def _load_bundle(self, target: Target, task_id: str, pipeline: str) -> EvidenceBundle:
        existing = self.store.get(EvidenceBundle, bundle_id(task_id))
        if existing is not None:
            return existing
        return EvidenceBundle(
            id=bundle_id(task_id),
            engagement_id=target.engagement_id,
            target_id=target.id,
            task_id=task_id,
            pipeline=pipeline,
        )

    def _link_checkpoint(self, task_id: str, bundle: EvidenceBundle) -> None:
        """Point the dispatching frontier task at its resume bundle, if one
        exists. Touches only ``checkpoint_ref`` - never the task's priority."""
        task = self.store.get(FrontierTask, task_id)
        if task is not None and task.checkpoint_ref != bundle.id:
            task.checkpoint_ref = bundle.id
            task.updated_at = now()
            self.store.put(task)

    def _require_target(self, engagement_id: str, target_id: str) -> Target:
        target = self.store.get(Target, target_id)
        if target is None:
            raise WorkerError(f"unknown target {target_id!r}")
        if target.engagement_id != engagement_id:
            raise WorkerError(f"target {target_id!r} does not belong to engagement {engagement_id!r}")
        return target

    def _stage(self, stage: str, task_id: str, episode_id: str) -> None:
        self.audit.record("worker.stage", stage=stage, task_id=task_id, episode_id=episode_id)
