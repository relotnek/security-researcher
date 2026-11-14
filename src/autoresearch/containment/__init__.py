"""Containment (L0.5): the isolation substrate."""

from .manager import (
    ContainmentError,
    ContainmentManager,
    Instance,
    InstanceStatus,
    SandboxSpec,
    Snapshot,
    VMSpec,
)

__all__ = [
    "ContainmentError",
    "ContainmentManager",
    "Instance",
    "InstanceStatus",
    "SandboxSpec",
    "Snapshot",
    "VMSpec",
]
