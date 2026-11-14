"""Scope registry (L0): the authorization boundary.

Records, per engagement, which assets are in scope, which are explicitly
forbidden, and which action classes are permitted - and enforces that
deny-by-default before any target-touching action.
"""

from __future__ import annotations

import fnmatch
import ipaddress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

from .audit import AuditLog
from .state import Record, StateStore, now


class ActionClass(StrEnum):
    """Classes of target-touching action an engagement may permit."""

    STATIC_ANALYSIS = "static_analysis"  # inspect artifacts without running them
    DYNAMIC_ANALYSIS = "dynamic_analysis"  # run / instrument / debug the target
    NETWORK_PROBE = "network_probe"  # scan or probe the target over the network
    FUZZING = "fuzzing"
    EXPLOITATION = "exploitation"  # detonate a proof-of-concept
    DENIAL_OF_SERVICE = "denial_of_service"


@dataclass
class Scope(Record):
    """An engagement's scope. Stored under the engagement's id."""

    kind: ClassVar[str] = "scopes"

    id: str  # == engagement id
    in_scope: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    permitted_actions: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=now)

    def __post_init__(self) -> None:
        super().__post_init__()
        # Normalise so membership tests are exact; reject unknown action classes
        # at declaration time rather than silently never matching them.
        self.permitted_actions = [str(ActionClass(a)) for a in self.permitted_actions]
        for pattern in (*self.in_scope, *self.forbidden):
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError("scope asset entries must be non-empty strings")


def _matches(pattern: str, asset: str) -> bool:
    """An asset entry matches by exact name, glob (``*.example.com``), or -
    when the entry is a CIDR and the asset an IP address - containment."""
    pattern, asset = pattern.strip().lower(), asset.strip().lower()
    if pattern == asset:
        return True
    if "/" in pattern:
        try:
            return ipaddress.ip_address(asset) in ipaddress.ip_network(pattern, strict=False)
        except ValueError:
            pass
    return fnmatch.fnmatchcase(asset, pattern)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    engagement_id: str
    asset: str
    action_class: str

    def __bool__(self) -> bool:
        return self.allowed


class ScopeRegistry:
    def __init__(self, store: StateStore) -> None:
        self._store = store

    def declare(
        self,
        engagement_id: str,
        *,
        in_scope: list[str],
        forbidden: list[str] | None = None,
        permitted_actions: list[ActionClass | str],
    ) -> Scope:
        scope = Scope(
            id=engagement_id,
            in_scope=list(in_scope),
            forbidden=list(forbidden or []),
            permitted_actions=[str(a) for a in permitted_actions],
        )
        return self._store.put(scope)

    def get(self, engagement_id: str) -> Scope | None:
        return self._store.get(Scope, engagement_id)


class ScopeGate:
    """Deny-by-default authorization. Call :meth:`authorize` before any
    target-touching action; anything not positively authorized - including any
    error while deciding - is denied, and every denial is logged."""

    def __init__(self, registry: ScopeRegistry, audit: AuditLog) -> None:
        self._registry = registry
        self._audit = audit

    def authorize(self, engagement_id: str, asset: str, action_class: ActionClass | str) -> Decision:
        action = str(action_class)
        try:
            allowed, reason = self._decide(engagement_id, asset, action)
        except Exception as exc:  # indeterminate -> deny
            allowed, reason = False, f"indeterminate: {type(exc).__name__}: {exc}"
        decision = Decision(allowed, reason, str(engagement_id), str(asset), action)
        self._audit.record(
            "scope.allow" if allowed else "scope.deny",
            engagement_id=decision.engagement_id,
            asset=decision.asset,
            action_class=action,
            reason=reason,
        )
        return decision

    def _decide(self, engagement_id: str, asset: str, action: str) -> tuple[bool, str]:
        if not isinstance(asset, str) or not asset.strip():
            return False, "no target asset given"
        scope = self._registry.get(engagement_id)
        if scope is None:
            return False, "no scope declared for engagement"
        if any(_matches(p, asset) for p in scope.forbidden):
            return False, "asset is explicitly forbidden"
        if not any(_matches(p, asset) for p in scope.in_scope):
            return False, "asset is not in scope"
        if action not in {a.value for a in ActionClass}:
            return False, "unknown action class"
        if action not in scope.permitted_actions:
            return False, "action class is not permitted"
        return True, "asset in scope and action class permitted"
