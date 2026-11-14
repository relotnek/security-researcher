"""The double safety boundary.

:class:`ActionGuard` is the single entry point for target-touching actions.
An action proceeds only if BOTH hold:

* scope (L0): the scope registry authorizes this action class on this target;
* containment (L0.5): a live, isolated instance of this same target exists.

The action is then executed *inside that instance* - the guard has no way to
run it anywhere else - so "inside containment" is a property of the execution
path, not a promise. Failing either boundary blocks the action, and every
decision is logged.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .audit import AuditLog
from .containment import ContainmentManager
from .scope import ActionClass, ScopeGate
from .state import StateStore, Target


@dataclass(frozen=True)
class ActionResult:
    allowed: bool
    blocked_by: tuple[str, ...] = ()  # subset of ("scope", "containment")
    reasons: tuple[str, ...] = ()
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


class ActionGuard:
    def __init__(
        self, store: StateStore, gate: ScopeGate, containment: ContainmentManager, audit: AuditLog
    ) -> None:
        self._store = store
        self._gate = gate
        self._containment = containment
        self._audit = audit

    def run(
        self,
        *,
        engagement_id: str,
        target_id: str,
        action_class: ActionClass | str,
        instance_id: str | None,
        argv: list[str],
        timeout: float = 120,
    ) -> ActionResult:
        action = str(action_class)
        context = {
            "engagement_id": engagement_id,
            "target_id": target_id,
            "action_class": action,
            "instance_id": instance_id,
            "argv": list(argv),
        }
        blocked_by: list[str] = []
        reasons: list[str] = []

        # Boundary 1 - scope. The asset checked is the one on the target's
        # durable record, never one supplied by the caller.
        try:
            target = self._store.get(Target, target_id)
        except Exception:
            target = None
        if target is None or target.engagement_id != engagement_id:
            asset = ""  # unknown target: the gate denies an empty asset, and logs it
        else:
            asset = target.asset
        decision = self._gate.authorize(engagement_id, asset, action)
        if not decision.allowed:
            blocked_by.append("scope")
            reasons.append("unknown target for this engagement" if not asset else decision.reason)

        # Boundary 2 - containment. Evaluated even if scope already failed so
        # the log records the state of both boundaries.
        contained, why, instance = self._containment.check(
            instance_id or "", engagement_id=engagement_id, target_id=target_id
        )
        self._audit.record("containment.allow" if contained else "containment.deny", reason=why, **context)
        if not contained or instance is None:
            blocked_by.append("containment")
            reasons.append(why)

        if blocked_by:
            self._audit.record("action.blocked", blocked_by=blocked_by, reasons=reasons, **context)
            return ActionResult(False, tuple(blocked_by), tuple(reasons))

        try:
            proc = self._containment.exec_in(instance, list(argv), timeout=timeout)
        except subprocess.TimeoutExpired:
            self._audit.record("action.timeout", timeout=timeout, **context)
            raise
        self._audit.record("action.executed", returncode=proc.returncode, **context)
        return ActionResult(True, (), (), proc.returncode, proc.stdout, proc.stderr)
