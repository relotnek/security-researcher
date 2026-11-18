"""Durable research state: the always-on element of the system.

Records are plain JSON files, one per record, under
``<root>/<kind>/<id>.json`` so the semantic layer stays human-readable and a
fresh agent with no prior context can resume from disk alone.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from .taxonomy import TargetClass, TargetType, classify

SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Mode(StrEnum):
    DIRECTED = "directed"  # seeded with a CVE / target model spec -> PoC
    DISCOVERY = "discovery"  # seeded with a bounty program + scope -> findings


class FindingStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DEAD_END = "dead_end"


@dataclass
class Record:
    """Base for every durable record."""

    kind: ClassVar[str]
    _enums: ClassVar[dict[str, type[StrEnum]]] = {}

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {version!r} for {cls.kind}")
        names = {f.name for f in fields(cls)}
        unknown = set(data) - names - {"schema_version"}
        if unknown:
            raise ValueError(f"unknown fields for {cls.kind}: {sorted(unknown)}")
        return cls(**{k: v for k, v in data.items() if k in names})

    def __post_init__(self) -> None:
        for name, enum in self._enums.items():
            setattr(self, name, enum(getattr(self, name)))


@dataclass
class Engagement(Record):
    kind: ClassVar[str] = "engagements"
    _enums: ClassVar = {"mode": Mode}

    id: str
    name: str
    mode: Mode
    seed: str  # CVE id / target model spec (directed) or bounty program (discovery)
    created_at: str = field(default_factory=now)


@dataclass
class Target(Record):
    kind: ClassVar[str] = "targets"
    _enums: ClassVar = {"target_type": TargetType}

    id: str
    engagement_id: str
    asset: str  # the identifier the scope registry authorizes against
    target_type: TargetType
    description: str = ""
    created_at: str = field(default_factory=now)

    @property
    def target_class(self) -> TargetClass:
        return classify(self.target_type)


@dataclass
class Finding(Record):
    kind: ClassVar[str] = "findings"
    _enums: ClassVar = {"status": FindingStatus}

    id: str
    engagement_id: str
    target_id: str
    title: str
    status: FindingStatus = FindingStatus.CANDIDATE
    description: str = ""
    poc_ref: str | None = None  # reproducible proof-of-concept artifact
    snapshot_ref: str | None = None  # containment snapshot that reproduces it
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now)

    def __post_init__(self) -> None:
        super().__post_init__()
        # PoC-gated findings: no PoC, no finding.
        if self.status is FindingStatus.CONFIRMED and not self.poc_ref:
            raise ValueError("a confirmed finding requires a proof-of-concept (poc_ref)")


@dataclass
class FrontierTask(Record):
    """An investigation task on the frontier. See :mod:`autoresearch.frontier`
    for the meaning of each field and docs/frontier.md for the task shape."""

    kind: ClassVar[str] = "frontier_tasks"
    _enums: ClassVar = {"status": TaskStatus}

    id: str
    engagement_id: str
    target_id: str  # target reference
    objective: str  # the hypothesis or objective to investigate
    action_class: str  # intended action class (autoresearch.scope.ActionClass)
    estimates: dict[str, float] = field(default_factory=dict)  # raw per-factor estimates
    provenance: dict[str, Any] = field(default_factory=dict)  # what produced the task
    regions: list[str] = field(default_factory=list)  # coverage footprint
    novelty: float = 0.0  # derived from the footprint, in [0, 1]
    priority: float = 0.0  # combined score; higher dispatches first
    status: TaskStatus = TaskStatus.QUEUED
    equivalence_key: str = ""  # canonical key: tasks sharing it are equivalent
    dead_end_equivalent: bool = False  # equivalent to a recorded dead-end
    merged_provenance: list[dict[str, Any]] = field(default_factory=list)  # duplicates merged in
    checkpoint_ref: str | None = None  # evidence bundle for cold resume
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)


@dataclass
class DeadEnd(Record):
    kind: ClassVar[str] = "dead_ends"

    id: str
    engagement_id: str
    task_id: str
    equivalence_key: str
    reason: str
    created_at: str = field(default_factory=now)


R = TypeVar("R", bound=Record)


class StateStore:
    """File-backed store. Writes are atomic (write-temp-then-rename) so an
    episode dying mid-write never leaves a torn record."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, record_id: str) -> Path:
        if not _ID_RE.match(record_id):
            raise ValueError(f"invalid record id {record_id!r}")
        return self.root / kind / f"{record_id}.json"

    def put(self, record: R) -> R:
        path = self._path(record.kind, record.id)  # type: ignore[attr-defined]
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(record.to_dict(), fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return record

    def get(self, cls: type[R], record_id: str) -> R | None:
        path = self._path(cls.kind, record_id)
        if not path.exists():
            return None
        return cls.from_dict(json.loads(path.read_text()))

    def list(self, cls: type[R], **where: Any) -> list[R]:
        directory = self.root / cls.kind
        if not directory.is_dir():
            return []
        records = [
            cls.from_dict(json.loads(p.read_text()))
            for p in sorted(directory.glob("*.json"))
            if not p.name.startswith(".")
        ]
        return [r for r in records if all(getattr(r, k) == v for k, v in where.items())]

    def delete(self, cls: type[R], record_id: str) -> bool:
        path = self._path(cls.kind, record_id)
        if not path.exists():
            return False
        path.unlink()
        return True
