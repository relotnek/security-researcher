import unittest

from autoresearch.containment import ContainmentError, Instance, InstanceStatus, Snapshot
from autoresearch.containment.docker import inspect
from autoresearch.state import StateStore, Target
from autoresearch.taxonomy import TargetType

from .docker_support import ContainmentTestCase, requires_docker
from .test_containment_segment import IsolatedSegmentTest, probe_spec

EMPTY = {"containers": [], "networks": []}


@requires_docker
class SnapshotTeardownTest(ContainmentTestCase):
    def assert_torn_down_but_snapshot_retained(self, instance, snapshot):
        self.assertEqual(self.manager.resources(instance.id), EMPTY)
        for name in (instance.container, instance.gateway_container):
            self.assertIsNone(inspect("container", name))
        for name in (instance.network, instance.egress_network):
            self.assertIsNone(inspect("network", name))
        self.assertIs(self.store.get(Instance, instance.id).status, InstanceStatus.TORN_DOWN)
        self.assertFalse(self.manager.check(instance.id)[0])
        # The snapshot outlives the instance, in Docker and in durable state.
        self.assertIsNotNone(inspect("image", snapshot.image))
        self.assertEqual(StateStore(self.root / "state").get(Snapshot, snapshot.id), snapshot)

    def test_sandbox_snapshot_reconstitutes_state_and_survives_teardown(self):
        target = Target(id="tgt-code", engagement_id="eng-1", asset="acme/widget", target_type=TargetType.BINARY)
        instance = self.provision(target, allowlist=["allowed.test"])
        wrote = self.manager.exec_in(
            instance, ["sh", "-c", "mkdir -p /work && echo crash-input-7f3a > /work/repro.txt"]
        )
        self.assertEqual(wrote.returncode, 0, wrote.stderr)

        snapshot = self.manager.snapshot(instance.id, note="state reproducing finding fnd-1")
        self.addCleanup(self.manager.delete_snapshot, snapshot.id)
        self.manager.teardown(instance.id)
        self.assert_torn_down_but_snapshot_retained(instance, snapshot)
        self.manager.teardown(instance.id)  # idempotent

        restored = self.manager.restore(snapshot.id)
        self.addCleanup(self.manager.teardown, restored.id)
        self.assertNotEqual(restored.id, instance.id)
        self.assertEqual(restored.restored_from, snapshot.id)
        self.assertEqual((restored.target_id, restored.allowlist), (instance.target_id, instance.allowlist))
        read = self.manager.exec_in(restored, ["cat", "/work/repro.txt"])
        self.assertEqual(read.stdout.strip(), "crash-input-7f3a")
        # The reconstituted instance is contained like the original.
        self.assertTrue(self.manager.check(restored.id, target_id=target.id)[0])
        self.assertEqual(list(inspect("container", restored.container)["NetworkSettings"]["Networks"]), [restored.network])

    def test_vm_snapshot_reconstitutes_disk_state_and_survives_teardown(self):
        wait_for_console = IsolatedSegmentTest.wait_for_console
        target = Target(id="tgt-dev", engagement_id="eng-1", asset="cam-01", target_type=TargetType.DEVICE)
        instance = self.provision(target, vm=probe_spec(netprobe="0", mark="FIRST-BOOT"))
        console = wait_for_console(self, instance, "ASR_DISK_WROTE=[FIRST-BOOT]")
        self.assertIn("ASR_DISK_PREV=[]", console)  # fresh disk

        snapshot = self.manager.snapshot(instance.id)
        self.addCleanup(self.manager.delete_snapshot, snapshot.id)
        self.manager.teardown(instance.id)
        self.assert_torn_down_but_snapshot_retained(instance, snapshot)

        restored = self.manager.restore(snapshot.id, append="console=ttyS0 quiet asr.netprobe=0")
        self.addCleanup(self.manager.teardown, restored.id)
        console = wait_for_console(self, restored, "ASR_PROBE_DONE")
        self.assertIn("ASR_DISK_PREV=[FIRST-BOOT]", console)

    def test_cannot_snapshot_a_torn_down_instance(self):
        target = Target(id="tgt-code", engagement_id="eng-1", asset="acme/widget", target_type=TargetType.WEB_APP)
        instance = self.provision(target)
        self.manager.teardown(instance.id)
        with self.assertRaises(ContainmentError):
            self.manager.snapshot(instance.id)

    def test_delete_snapshot_releases_the_image(self):
        target = Target(id="tgt-code", engagement_id="eng-1", asset="acme/widget", target_type=TargetType.WEB_APP)
        instance = self.provision(target)
        snapshot = self.manager.snapshot(instance.id)
        self.manager.delete_snapshot(snapshot.id)
        self.assertIsNone(inspect("image", snapshot.image))
        self.assertIsNone(self.store.get(Snapshot, snapshot.id))


if __name__ == "__main__":
    unittest.main()
