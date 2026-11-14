"""Containment provisioning, snapshot, and teardown.

Every contained instance has the same network shape, whatever its profile:

    workload ──(internal network: no gateway, no route out)── egress gateway ──(egress network)── allowlisted hosts

* The workload (a Docker sandbox, or a VM bridged onto the segment) is attached
  only to an ``--internal`` Docker network whose bridge has no host address,
  so it has no route to the internet, to production, or to the Docker host.
* The egress gateway is the one host that is also attached to an egress
  network. It forwards only to allowlisted destinations, so egress is
  default-deny and the allowlist is the only exception.

The profile is chosen from the target's class and cannot be overridden by the
caller: code/software targets get a Docker sandbox, device/firmware/network
targets get a VM on an isolated segment.
"""

from __future__ import annotations

import ipaddress
import random
import subprocess
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from ..audit import AuditLog
from ..state import Record, StateStore, Target, new_id, now
from ..taxonomy import ContainmentProfile, profile_for
from .docker import IMAGES_DIR, DockerError, docker, ensure_image, inspect

LABEL = "autoresearch.instance"
GATEWAY_ALIAS = "egress-gateway"
PROXY_PORT = 3128
SNAPSHOT_REPO = "autoresearch/snapshot"


class ContainmentError(RuntimeError):
    pass


class InstanceStatus(StrEnum):
    RUNNING = "running"
    TORN_DOWN = "torn_down"


@dataclass
class SandboxSpec:
    """A Docker sandbox for a code/software target."""

    image: str = "alpine:3.21"
    command: list[str] = field(default_factory=lambda: ["sleep", "infinity"])
    memory: str = "512m"
    cpus: str = "1.0"
    pids_limit: int = 256


@dataclass
class VMSpec:
    """A VM on an isolated segment for a device/firmware/network target.

    ``image`` is an image built ``FROM`` the vm-runner image
    (:meth:`ContainmentManager.vm_runner_image`) that adds the guest's
    kernel / initrd / disk. A disk at ``/vm/disk.qcow2`` (or one created from
    ``disk_size``) is attached and is what snapshots capture.
    """

    image: str
    kernel: str | None = None
    initrd: str | None = None
    append: str = ""
    disk_size: str | None = None
    memory_mb: int = 256
    arch: str = "x86_64"
    machine: str | None = None
    nic: str = "virtio-net-pci"
    extra: str = ""
    cpus: str = "1.0"


@dataclass
class Instance(Record):
    kind: ClassVar[str] = "instances"
    _enums: ClassVar = {"profile": ContainmentProfile, "status": InstanceStatus}

    id: str
    engagement_id: str
    target_id: str
    asset: str
    profile: ContainmentProfile
    status: InstanceStatus
    container: str  # where actions against the target execute
    gateway_container: str
    network: str  # the internal (isolated) network / segment
    egress_network: str
    subnet: str
    gateway_ip: str
    allowlist: list[str] = field(default_factory=list)
    spec: dict[str, Any] = field(default_factory=dict)
    guest_ip: str | None = None
    guest_mac: str | None = None
    restored_from: str | None = None
    created_at: str = field(default_factory=now)
    torn_down_at: str | None = None

    @property
    def proxy_url(self) -> str:
        return f"http://{GATEWAY_ALIAS}:{PROXY_PORT}"


@dataclass
class Snapshot(Record):
    kind: ClassVar[str] = "snapshots"
    _enums: ClassVar = {"profile": ContainmentProfile}

    id: str
    instance_id: str
    engagement_id: str
    target_id: str
    asset: str
    profile: ContainmentProfile
    image: str
    allowlist: list[str] = field(default_factory=list)
    spec: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    created_at: str = field(default_factory=now)


class ContainmentManager:
    def __init__(self, store: StateStore, audit: AuditLog) -> None:
        self._store = store
        self._audit = audit

    # -- images ------------------------------------------------------------

    @staticmethod
    def gateway_image() -> str:
        return ensure_image("autoresearch/egress-gateway", IMAGES_DIR / "egress-gateway")

    @staticmethod
    def vm_runner_image() -> str:
        return ensure_image("autoresearch/vm-runner", IMAGES_DIR / "vm-runner")

    # -- provisioning ------------------------------------------------------

    def provision(
        self,
        target: Target,
        *,
        allowlist: list[str] | None = None,
        sandbox: SandboxSpec | None = None,
        vm: VMSpec | None = None,
    ) -> Instance:
        """Provision an isolated instance of ``target``. The containment
        profile follows from the target's class."""
        profile = profile_for(target.target_type)
        if profile is ContainmentProfile.DOCKER_SANDBOX:
            if vm is not None:
                raise ContainmentError("code/software targets are contained in a Docker sandbox, not a VM")
            spec = asdict(sandbox or SandboxSpec())
        else:
            if sandbox is not None:
                raise ContainmentError(
                    "device/firmware/network targets are contained on an isolated segment, not a Docker sandbox"
                )
            if vm is None:
                raise ContainmentError("a VMSpec is required for device/firmware/network targets")
            spec = asdict(vm)
        return self._provision(
            target.engagement_id, target.id, target.asset, profile, spec, list(allowlist or []), None
        )

    def restore(self, snapshot_id: str, *, append: str | None = None) -> Instance:
        """Reconstitute a new contained instance from a retained snapshot."""
        snap = self._store.get(Snapshot, snapshot_id)
        if snap is None:
            raise ContainmentError(f"unknown snapshot {snapshot_id!r}")
        spec = {**snap.spec, "image": snap.image}
        if append is not None and snap.profile is ContainmentProfile.ISOLATED_SEGMENT:
            spec["append"] = append
        return self._provision(
            snap.engagement_id, snap.target_id, snap.asset, snap.profile, spec, list(snap.allowlist), snap.id
        )

    def _provision(
        self,
        engagement_id: str,
        target_id: str,
        asset: str,
        profile: ContainmentProfile,
        spec: dict[str, Any],
        allowlist: list[str],
        restored_from: str | None,
    ) -> Instance:
        for entry in allowlist:
            if not entry.strip() or "," in entry or any(c.isspace() for c in entry):
                raise ContainmentError(f"invalid allowlist entry {entry!r}")
        instance_id = new_id("ins")
        base = f"asr-{instance_id}"
        label = f"{LABEL}={instance_id}"
        network, egress, gateway = f"{base}-int", f"{base}-egress", f"{base}-gw"
        try:
            gateway_image = self.gateway_image()
            subnet = self._create_isolated_network(network, label)
            docker("network", "create", "--label", label, egress)
            docker(
                "run", "-d", "--name", gateway, "--label", label,
                "--network", egress,
                "--sysctl", "net.ipv4.ip_forward=0",  # a proxy, never a router
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--read-only", "--memory", "128m", "--pids-limit", "64",
                "-e", f"ALLOWLIST={','.join(allowlist)}",
                "-e", f"PROXY_PORT={PROXY_PORT}",
                gateway_image,
            )  # fmt: skip
            docker("network", "connect", "--alias", GATEWAY_ALIAS, network, gateway)
            gateway_ip = inspect("container", gateway)["NetworkSettings"]["Networks"][network]["IPAddress"]

            guest_ip = guest_mac = None
            if profile is ContainmentProfile.DOCKER_SANDBOX:
                container = f"{base}-box"
                proxy = f"http://{GATEWAY_ALIAS}:{PROXY_PORT}"
                docker(
                    "run", "-d", "--name", container, "--label", label,
                    "--network", network,
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--memory", str(spec["memory"]), "--cpus", str(spec["cpus"]),
                    "--pids-limit", str(spec["pids_limit"]),
                    "-e", f"HTTP_PROXY={proxy}", "-e", f"HTTPS_PROXY={proxy}",
                    "-e", f"http_proxy={proxy}", "-e", f"https_proxy={proxy}",
                    spec["image"], *spec["command"],
                )  # fmt: skip
            else:
                container = f"{base}-vm"
                net = ipaddress.ip_network(subnet)
                # Docker allocates from the lower half of the subnet (--ip-range);
                # guests live in the upper half so the two never collide.
                guest_ip = str(net.network_address + 200)
                guest_mac = "52:54:00:%02x:%02x:%02x" % tuple(random.randrange(256) for _ in range(3))
                append = " ".join(
                    filter(
                        None,
                        [
                            spec.get("append", ""),
                            f"asr.ip={guest_ip}/{net.prefixlen}",
                            f"asr.proxy={gateway_ip}:{PROXY_PORT}",
                        ],
                    )
                )
                env = {
                    "VM_ARCH": spec["arch"],
                    "VM_MACHINE": spec.get("machine") or "",
                    "VM_MEMORY": str(spec["memory_mb"]),
                    "VM_KERNEL": spec.get("kernel") or "",
                    "VM_INITRD": spec.get("initrd") or "",
                    "VM_APPEND": append,
                    "VM_DISK_SIZE": spec.get("disk_size") or "",
                    "VM_NIC": spec["nic"],
                    "VM_MAC": guest_mac,
                    "VM_EXTRA": spec.get("extra") or "",
                }
                docker(
                    "run", "-d", "--name", container, "--label", label,
                    "--network", network,
                    # NET_ADMIN/MKNOD only to bridge the guest's tap onto the segment.
                    "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "--cap-add", "MKNOD",
                    "--security-opt", "no-new-privileges",
                    "--memory", f"{int(spec['memory_mb']) + 256}m", "--cpus", str(spec["cpus"]),
                    *[arg for k, v in env.items() for arg in ("-e", f"{k}={v}")],
                    spec["image"],
                )  # fmt: skip

            instance = Instance(
                id=instance_id,
                engagement_id=engagement_id,
                target_id=target_id,
                asset=asset,
                profile=profile,
                status=InstanceStatus.RUNNING,
                container=container,
                gateway_container=gateway,
                network=network,
                egress_network=egress,
                subnet=subnet,
                gateway_ip=gateway_ip,
                allowlist=allowlist,
                spec=spec,
                guest_ip=guest_ip,
                guest_mac=guest_mac,
                restored_from=restored_from,
            )
            ok, reason = self._inspect_isolation(instance)
            if not ok:
                raise ContainmentError(f"provisioned instance failed isolation check: {reason}")
            self._store.put(instance)
        except Exception as exc:
            self._release(instance_id)
            self._audit.record(
                "containment.provision_failed",
                instance_id=instance_id, target_id=target_id, error=str(exc),
            )  # fmt: skip
            if isinstance(exc, ContainmentError):
                raise
            raise ContainmentError(f"provisioning failed: {exc}") from exc
        self._audit.record(
            "containment.provision",
            instance_id=instance_id, engagement_id=engagement_id, target_id=target_id,
            profile=str(profile), allowlist=allowlist, restored_from=restored_from,
        )  # fmt: skip
        return instance

    @staticmethod
    def _create_isolated_network(name: str, label: str) -> str:
        last = ""
        for _ in range(25):
            subnet = f"10.{random.randrange(64, 128)}.{random.randrange(256)}.0/24"
            lower_half = subnet.replace("/24", "/25")
            proc = docker(
                "network", "create", "--internal", "--label", label,
                "--subnet", subnet, "--ip-range", lower_half,
                # No host address on the bridge: the Docker host itself is not
                # reachable from the segment, and there is no gateway to route via.
                "-o", "com.docker.network.bridge.inhibit_ipv4=true",
                name,
                check=False,
            )  # fmt: skip
            if proc.returncode == 0:
                return subnet
            last = proc.stderr.strip()
            if "overlap" not in last.lower():
                break
        raise DockerError(f"could not create isolated network: {last}")

    # -- isolation check ---------------------------------------------------

    def _inspect_isolation(self, instance: Instance) -> tuple[bool, str]:
        info = inspect("container", instance.container)
        if info is None:
            return False, "instance container does not exist"
        if not info["State"]["Running"]:
            return False, "instance container is not running"
        if info["Config"]["Labels"].get(LABEL) != instance.id:
            return False, "container does not belong to this instance"
        if info["HostConfig"].get("Privileged"):
            return False, "instance container is privileged"
        attached = set(info["NetworkSettings"]["Networks"])
        if attached != {instance.network}:
            return False, f"instance is attached to networks other than its isolated network: {sorted(attached)}"
        net = inspect("network", instance.network)
        if net is None or not net.get("Internal"):
            return False, "instance network is not internal"
        return True, "contained"

    def check(
        self, instance_id: str, *, engagement_id: str | None = None, target_id: str | None = None
    ) -> tuple[bool, str, Instance | None]:
        """Is ``instance_id`` a live, isolated instance of this target? Any
        doubt - including an error while checking - is a 'no'."""
        try:
            instance = self._store.get(Instance, instance_id) if instance_id else None
            if instance is None:
                return False, "no such contained instance", None
            if instance.status is not InstanceStatus.RUNNING:
                return False, "contained instance has been torn down", instance
            if engagement_id is not None and instance.engagement_id != engagement_id:
                return False, "contained instance belongs to a different engagement", instance
            if target_id is not None and instance.target_id != target_id:
                return False, "contained instance is not an instance of this target", instance
            ok, reason = self._inspect_isolation(instance)
            return ok, reason, instance
        except Exception as exc:
            return False, f"indeterminate: {type(exc).__name__}: {exc}", None

    def get(self, instance_id: str) -> Instance | None:
        return self._store.get(Instance, instance_id)

    # -- execution / observation ------------------------------------------

    def exec_in(
        self, instance: Instance, argv: list[str], *, timeout: float = 120
    ) -> subprocess.CompletedProcess[str]:
        """Run ``argv`` inside the instance. Not a public entry point for
        target actions - those go through :class:`autoresearch.boundary.ActionGuard`."""
        return docker("exec", instance.container, *argv, check=False, timeout=timeout)

    def console(self, instance: Instance) -> str:
        """Console output of the instance (the guest's serial console for VMs)."""
        proc = docker("logs", instance.container, check=False)
        return proc.stdout + proc.stderr

    def gateway_log(self, instance: Instance) -> str:
        """Egress decisions captured at the segment boundary."""
        proc = docker("logs", instance.gateway_container, check=False)
        return proc.stdout + proc.stderr

    # -- snapshot / teardown -----------------------------------------------

    def snapshot(self, instance_id: str, *, note: str = "") -> Snapshot:
        """Snapshot the instance's persistent state (sandbox filesystem, or the
        VM's disk) into a retained image. The instance is paused while the
        snapshot is taken; in-memory state (running processes, guest RAM) is
        not captured - a restored sandbox restarts its command and a restored
        VM boots from the snapshotted disk."""
        ok, reason, instance = self.check(instance_id)
        if not ok or instance is None:
            raise ContainmentError(f"cannot snapshot: {reason}")
        snapshot_id = new_id("snap")
        image = f"{SNAPSHOT_REPO}:{snapshot_id}"
        is_vm = instance.profile is ContainmentProfile.ISOLATED_SEGMENT
        try:
            if is_vm:
                # Stop the guest first: QEMU flushes its disks on stop, so the
                # committed disk image is consistent rather than mid-write.
                stopped = docker("exec", instance.container, "vm-ctl", "stop", check=False, timeout=60)
                if "paused" not in stopped.stdout:
                    raise ContainmentError(f"could not quiesce the guest: {stopped.stdout} {stopped.stderr}".strip())
            docker(
                "commit", "--pause=true",
                "--change", f"LABEL autoresearch.snapshot={snapshot_id}",
                instance.container, image,
            )  # fmt: skip
        except DockerError as exc:
            raise ContainmentError(f"snapshot failed: {exc}") from exc
        finally:
            if is_vm:
                docker("exec", instance.container, "vm-ctl", "cont", check=False, timeout=60)
        snap = self._store.put(
            Snapshot(
                id=snapshot_id,
                instance_id=instance.id,
                engagement_id=instance.engagement_id,
                target_id=instance.target_id,
                asset=instance.asset,
                profile=instance.profile,
                image=image,
                allowlist=list(instance.allowlist),
                spec=dict(instance.spec),
                note=note,
            )
        )
        self._audit.record("containment.snapshot", instance_id=instance.id, snapshot_id=snapshot_id, image=image)
        return snap

    def delete_snapshot(self, snapshot_id: str) -> None:
        snap = self._store.get(Snapshot, snapshot_id)
        if snap is None:
            return
        docker("image", "rm", "-f", snap.image, check=False)
        self._store.delete(Snapshot, snapshot_id)
        self._audit.record("containment.snapshot_deleted", snapshot_id=snapshot_id)

    def teardown(self, instance_id: str) -> None:
        """Release the instance's ephemeral resources (containers, networks).
        Retained snapshots are untouched. Idempotent."""
        self._release(instance_id)
        instance = self._store.get(Instance, instance_id)
        if instance is not None and instance.status is not InstanceStatus.TORN_DOWN:
            instance.status = InstanceStatus.TORN_DOWN
            instance.torn_down_at = now()
            self._store.put(instance)
        self._audit.record("containment.teardown", instance_id=instance_id)

    @staticmethod
    def resources(instance_id: str) -> dict[str, list[str]]:
        """Live Docker resources still held by an instance."""
        flt = f"label={LABEL}={instance_id}"
        return {
            "containers": docker("ps", "-aq", "--filter", flt).stdout.split(),
            "networks": docker("network", "ls", "-q", "--filter", flt).stdout.split(),
        }

    @classmethod
    def _release(cls, instance_id: str) -> None:
        held = cls.resources(instance_id)
        if held["containers"]:
            docker("rm", "-f", "-v", *held["containers"], check=False)
        if held["networks"]:
            docker("network", "rm", *held["networks"], check=False)
        left = cls.resources(instance_id)
        if left["containers"] or left["networks"]:
            raise ContainmentError(f"teardown incomplete for {instance_id}: {left}")
