"""The frontier (L2): a scored, de-duplicated queue of investigation tasks.

The frontier is what makes continuous research a best-first search instead of
a random walk. Workers and the driver touch it only through five operations
on :class:`Frontier`: ``enqueue``, ``pop_highest``, ``peek``,
``mark_dead_end`` and ``rescore``. State lives in the durable-state substrate,
so any fresh process can pick the queue up where the last one left it.

Task shape
----------
A task is submitted as a mapping (see docs/frontier.md for a worked example):

``target_id``     target reference; must name a stored :class:`Target`
``objective``     the hypothesis or objective to investigate
``action_class``  intended action class (:class:`autoresearch.scope.ActionClass`)
``estimates``     raw per-factor estimates, all four required:
                  ``likelihood`` probability the hypothesis holds, 0..1
                  ``impact``     severity if it does, 0..10
                  ``value``      how much the engagement cares, 0..10
                  ``cost``       expected effort in worker episodes, >= 0
``provenance``    what produced the task; requires ``source``. An optional
                  ``distinguisher`` forces a task to be treated as distinct
                  from others that would otherwise share its canonical key.
``regions``       optional coverage footprint: the regions (code regions,
                  endpoints, hypothesis classes) the task would explore

Scoring
-------
Each factor is normalized to [0, 1], then combined::

    priority = (w_l*likelihood + w_i*impact + w_v*value + w_n*novelty)
               / (w_c*cost + epsilon)

Novelty is derived, not estimated: it is the fraction of the task's regions
that no dispatched task on the same target has covered yet.

A task's priority changes only on a recorded event: an explicit ``rescore``,
a merge that widens its footprint, or another task being dispatched over
regions it shares (which lowers its novelty). Every such event is logged.
"""

from __future__ import annotations

import contextlib
import fcntl
import math
import re
import unicodedata
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

from .audit import AuditLog
from .scope import ActionClass
from .state import DeadEnd, FrontierTask, StateStore, Target, TaskStatus, new_id, now

ESTIMATED_FACTORS = ("likelihood", "impact", "value", "cost")
FACTORS = (*ESTIMATED_FACTORS, "novelty")
REQUIRED_FIELDS = ("target_id", "objective", "action_class", "estimates", "provenance")
OPTIONAL_FIELDS = ("regions",)


class FrontierError(ValueError):
    """A submission or operation the frontier rejects."""


# -- scoring ---------------------------------------------------------------


@dataclass(frozen=True)
class ScoringConfig:
    """Weights and scales. Configuration, not contract: tune freely."""

    w_likelihood: float = 0.35
    w_impact: float = 0.25
    w_value: float = 0.20
    w_novelty: float = 0.20
    w_cost: float = 1.0
    epsilon: float = 0.25  # keeps zero-cost tasks finite
    impact_max: float = 10.0  # raw impact scale
    value_max: float = 10.0  # raw engagement-value scale
    cost_half: float = 4.0  # episodes at which normalized cost reaches 0.5
    unknown_novelty: float = 0.5  # novelty of a task that declares no footprint
    dead_end_penalty: float = 0.1  # priority multiplier for dead-end equivalents

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise FrontierError(f"scoring config {f.name} must be a finite number")
            if value < 0:
                raise FrontierError(f"scoring config {f.name} must not be negative")
        for name in ("epsilon", "impact_max", "value_max", "cost_half"):
            if getattr(self, name) <= 0:
                raise FrontierError(f"scoring config {name} must be positive")
        if not 0 <= self.unknown_novelty <= 1 or not 0 <= self.dead_end_penalty <= 1:
            raise FrontierError("unknown_novelty and dead_end_penalty must be within [0, 1]")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScoringConfig":
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise FrontierError(f"unknown scoring config keys: {sorted(unknown)}")
        return cls(**data)


def _number(factor: str, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or math.isnan(raw):
        raise FrontierError(f"{factor} estimate must be a number, got {raw!r}")
    return float(raw)


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


def normalize(factor: str, raw: Any, config: ScoringConfig = ScoringConfig()) -> float:
    """Normalize one raw factor estimate to [0, 1]. Out-of-range inputs are
    clamped; non-numeric inputs (including NaN) are rejected."""
    x = _number(factor, raw)
    if factor in ("likelihood", "novelty"):
        return _clamp(x)
    if factor == "impact":
        return _clamp(x / config.impact_max)
    if factor == "value":
        return _clamp(x / config.value_max)
    if factor == "cost":
        # Saturating: effort is unbounded above, so it approaches 1 rather than
        # being cut off at an arbitrary maximum.
        if x <= 0:
            return 0.0
        if math.isinf(x):
            return 1.0
        return x / (x + config.cost_half)
    raise FrontierError(f"unknown factor {factor!r}")


def combine(normalized: Mapping[str, float], config: ScoringConfig = ScoringConfig()) -> float:
    """Combine normalized factors into one priority. Pure and deterministic:
    the same inputs always give the same score, whatever the target."""
    missing = [f for f in FACTORS if f not in normalized]
    if missing:
        raise FrontierError(f"cannot score without factors: {missing}")
    benefit = (
        config.w_likelihood * normalized["likelihood"]
        + config.w_impact * normalized["impact"]
        + config.w_value * normalized["value"]
        + config.w_novelty * normalized["novelty"]
    )
    return benefit / (config.w_cost * normalized["cost"] + config.epsilon)


def score(estimates: Mapping[str, Any], novelty: float, config: ScoringConfig = ScoringConfig()) -> float:
    """Priority of a task from its raw estimates and its novelty."""
    normalized = {f: normalize(f, estimates.get(f), config) for f in ESTIMATED_FACTORS}
    normalized["novelty"] = normalize("novelty", novelty, config)
    return combine(normalized, config)


def normalize_region(region: str) -> str:
    return " ".join(str(region).lower().split())


def novelty_of(
    regions: list[str] | set[str], explored: set[str], config: ScoringConfig = ScoringConfig()
) -> float:
    """Fraction of a task's footprint that has not been explored yet."""
    footprint = {normalize_region(r) for r in regions}
    if not footprint:
        return config.unknown_novelty
    return len(footprint - explored) / len(footprint)


# -- equivalence -----------------------------------------------------------

# Words that say "go and look" or merely glue a sentence together carry no
# information about *what* is being investigated, so they are not part of a
# task's identity.
_NOISE = frozenset(
    """
    a an the this that these those and or but of in on at to for from by with within into via as is are be
    was were it its there any some all each every whether if can could may might would should do does
    has have had contain contains
    possible possibly potential potentially maybe
    audit check look see find search hunt investigate examine review analyze analyse inspect test verify
    probe explore determine identify assess evaluate confirm try study scan
    """.split()
)


def _stem(token: str) -> str:
    for suffix, replacement in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if token.endswith(suffix) and len(token) - len(suffix) + len(replacement) >= 3:
            if suffix == "s" and token.endswith(("ss", "us", "is")):
                break
            return token[: len(token) - len(suffix)] + replacement
    return token


def normalize_objective(objective: str) -> str:
    """Reduce an objective to the sorted set of its meaningful word stems, so
    rewordings of the same hypothesis normalize identically."""
    text = unicodedata.normalize("NFKC", objective).lower()
    tokens = re.findall(r"[a-z0-9_]+", text)
    stems = {_stem(t) for t in tokens if t not in _NOISE}
    stems = {s for s in stems if s and s not in _NOISE}
    return " ".join(sorted(stems))


def canonical_key(target_id: str, objective: str, action_class: str, distinguisher: str = "") -> str:
    """Canonical task key: (target reference, normalized objective, action class)."""
    key = f"{target_id}|{action_class}|{normalize_objective(objective)}"
    return f"{key}|{normalize_region(distinguisher)}" if distinguisher else key


# -- task shape ------------------------------------------------------------


def validate_task(submission: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a submitted task and return it in canonical form. Raises
    :class:`FrontierError` naming the problem if it is malformed."""
    if not isinstance(submission, Mapping):
        raise FrontierError("a task must be a mapping of fields")
    unknown = set(submission) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
    if unknown:
        raise FrontierError(f"unknown task fields: {sorted(unknown)}")
    missing = [f for f in REQUIRED_FIELDS if submission.get(f) in (None, "", {}, [])]
    if missing:
        raise FrontierError(f"task is missing required fields: {missing}")

    target_id, objective = submission["target_id"], submission["objective"]
    if not isinstance(target_id, str) or not target_id.strip():
        raise FrontierError("target_id must be a non-empty string")
    if not isinstance(objective, str) or not normalize_objective(objective):
        raise FrontierError("objective must say what is to be investigated")
    try:
        action_class = str(ActionClass(submission["action_class"]))
    except ValueError:
        raise FrontierError(f"unknown action class {submission['action_class']!r}") from None

    estimates = submission["estimates"]
    if not isinstance(estimates, Mapping):
        raise FrontierError("estimates must be a mapping of factor to number")
    absent = [f for f in ESTIMATED_FACTORS if f not in estimates]
    if absent:
        raise FrontierError(f"task is missing required estimates: {absent}")
    extra = set(estimates) - set(ESTIMATED_FACTORS)
    if extra:
        raise FrontierError(f"unknown estimates: {sorted(extra)} (novelty is derived, not estimated)")
    estimates = {f: _number(f, estimates[f]) for f in ESTIMATED_FACTORS}

    provenance = submission["provenance"]
    if not isinstance(provenance, Mapping) or not str(provenance.get("source", "")).strip():
        raise FrontierError("provenance must be a mapping with a non-empty 'source'")

    regions = submission.get("regions") or []
    if isinstance(regions, str) or not all(isinstance(r, str) and r.strip() for r in regions):
        raise FrontierError("regions must be a list of non-empty strings")
    regions = sorted({normalize_region(r) for r in regions})

    return {
        "target_id": target_id.strip(),
        "objective": objective.strip(),
        "action_class": action_class,
        "estimates": estimates,
        "provenance": dict(provenance),
        "regions": regions,
    }


# -- the queue -------------------------------------------------------------

_OPEN = (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS)
_EXPLORED = (TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.DEAD_END)


@dataclass(frozen=True)
class EnqueueResult:
    task: FrontierTask
    outcome: str  # "enqueued" | "merged" | "deprioritized"


def rank(task: FrontierTask) -> tuple:
    """Dispatch order. Dead-end equivalents always sort below everything
    else; ties on priority fall back to age, then id, so order is total."""
    return (task.dead_end_equivalent, -task.priority, task.created_at, task.id)


class Frontier:
    def __init__(
        self, store: StateStore, audit: AuditLog | None = None, config: ScoringConfig = ScoringConfig()
    ) -> None:
        self._store = store
        self._audit = audit
        self._config = config

    # -- operations --------------------------------------------------------

    def enqueue(self, submission: Mapping[str, Any]) -> EnqueueResult:
        """Validate, de-duplicate, score, and queue a task.

        * malformed -> rejected (:class:`FrontierError`), nothing stored
        * equivalent to an open task -> merged into it, no new task
        * equivalent to a recorded dead-end -> queued, but below all novel tasks
        """
        fields_ = validate_task(submission)
        with self._locked():
            target = self._store.get(Target, fields_["target_id"])
            if target is None:
                raise FrontierError(f"unknown target {fields_['target_id']!r}")
            key = canonical_key(
                target.id,
                fields_["objective"],
                fields_["action_class"],
                str(fields_["provenance"].get("distinguisher", "")),
            )
            tasks = self._store.list(FrontierTask, target_id=target.id)

            existing = next((t for t in tasks if t.equivalence_key == key and t.status in _OPEN), None)
            if existing is not None:
                existing.merged_provenance.append({**fields_["provenance"], "objective": fields_["objective"]})
                widened = sorted(set(existing.regions) | set(fields_["regions"]))
                if widened != existing.regions:
                    existing.regions = widened
                    self._rescore(existing, tasks)
                self._save(existing)
                self._log("frontier.merge", existing, merged=fields_["provenance"])
                return EnqueueResult(existing, "merged")

            dead_end = bool(self._store.list(DeadEnd, equivalence_key=key))
            task = FrontierTask(
                id=new_id("tsk"),
                engagement_id=target.engagement_id,
                equivalence_key=key,
                dead_end_equivalent=dead_end,
                # Microsecond resolution: age is the tie-break between equal priorities.
                created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                **fields_,
            )
            self._rescore(task, tasks)
            self._save(task)
            outcome = "deprioritized" if dead_end else "enqueued"
            self._log("frontier.enqueue", task, outcome=outcome)
            return EnqueueResult(task, outcome)

    def peek(self, n: int = 1, *, engagement_id: str | None = None) -> list[FrontierTask]:
        """The next ``n`` ready tasks in dispatch order, without removing them."""
        return self._ready(engagement_id)[: max(0, n)]

    def pop_highest(self, *, engagement_id: str | None = None) -> FrontierTask | None:
        """Return the highest-priority ready task and remove it from the ready
        set (it becomes in-progress). ``None`` if nothing is ready."""
        with self._locked():
            ready = self._ready(engagement_id)
            if not ready:
                return None
            task = ready[0]
            task.status = TaskStatus.IN_PROGRESS
            self._save(task)
            self._log("frontier.pop", task)
            self._coverage_changed(task)
            return task

    def mark_dead_end(self, task_id: str, reason: str) -> DeadEnd:
        """Record a task as a dead-end and remove it from the ready set, so it
        is not dispatched again and later equivalents are deprioritized."""
        if not str(reason).strip():
            raise FrontierError("a dead-end needs a reason")
        with self._locked():
            task = self._get(task_id)
            if task.status not in _OPEN:
                raise FrontierError(f"task {task_id} is {task.status}, not open")
            was_queued = task.status is TaskStatus.QUEUED
            task.status = TaskStatus.DEAD_END
            self._save(task)
            dead_end = self._store.put(
                DeadEnd(
                    id=new_id("ded"),
                    engagement_id=task.engagement_id,
                    task_id=task.id,
                    equivalence_key=task.equivalence_key,
                    reason=reason,
                )
            )
            self._log("frontier.dead_end", task, reason=reason)
            if was_queued:  # never dispatched, so its coverage is new
                self._coverage_changed(task)
            return dead_end

    def rescore(self, task_id: str, *, evidence: str, **estimates: Any) -> FrontierTask:
        """Update a task's factor estimates from new evidence and recompute its
        priority. The only way estimates change."""
        if not str(evidence).strip():
            raise FrontierError("re-scoring needs the evidence that justifies it")
        unknown = set(estimates) - set(ESTIMATED_FACTORS)
        if unknown or not estimates:
            raise FrontierError(f"re-score takes estimates for {list(ESTIMATED_FACTORS)}, got {sorted(estimates)}")
        updates = {f: _number(f, v) for f, v in estimates.items()}
        with self._locked():
            task = self._get(task_id)
            if task.status not in _OPEN:
                raise FrontierError(f"task {task_id} is {task.status}, not open")
            before = {"estimates": dict(task.estimates), "priority": task.priority}
            task.estimates = {**task.estimates, **updates}
            self._rescore(task, self._store.list(FrontierTask, target_id=task.target_id))
            self._save(task)
            self._log("frontier.rescore", task, evidence=evidence, before=before)
            return task

    # -- internals ---------------------------------------------------------

    def _ready(self, engagement_id: str | None) -> list[FrontierTask]:
        where = {"status": TaskStatus.QUEUED}
        if engagement_id is not None:
            where["engagement_id"] = engagement_id
        return sorted(self._store.list(FrontierTask, **where), key=rank)

    def _get(self, task_id: str) -> FrontierTask:
        task = self._store.get(FrontierTask, task_id)
        if task is None:
            raise FrontierError(f"unknown task {task_id!r}")
        return task

    def _rescore(self, task: FrontierTask, target_tasks: list[FrontierTask]) -> None:
        explored = {r for t in target_tasks if t.id != task.id and t.status in _EXPLORED for r in t.regions}
        task.novelty = novelty_of(task.regions, explored, self._config)
        task.priority = score(task.estimates, task.novelty, self._config)
        if task.dead_end_equivalent:
            task.priority *= self._config.dead_end_penalty

    def _coverage_changed(self, explored_task: FrontierTask) -> None:
        """A task's regions just became explored: queued tasks on the same
        target that share any of them are less novel now."""
        if not explored_task.regions:
            return
        tasks = self._store.list(FrontierTask, target_id=explored_task.target_id)
        for task in tasks:
            if task.status is not TaskStatus.QUEUED or not set(task.regions) & set(explored_task.regions):
                continue
            before = task.priority
            self._rescore(task, tasks)
            if task.priority != before:
                self._save(task)
                self._log("frontier.novelty_update", task, cause=explored_task.id, before={"priority": before})

    def _save(self, task: FrontierTask) -> None:
        task.updated_at = now()
        self._store.put(task)

    def _log(self, event: str, task: FrontierTask, **details: Any) -> None:
        if self._audit is not None:
            self._audit.record(
                event,
                task_id=task.id,
                target_id=task.target_id,
                equivalence_key=task.equivalence_key,
                priority=task.priority,
                novelty=task.novelty,
                **details,
            )

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize mutations across processes sharing the state directory,
        so two drivers cannot pop the same task."""
        with open(self._store.root / ".frontier.lock", "w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
