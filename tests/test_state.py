import tempfile
import unittest

from autoresearch.state import (
    DeadEnd,
    Engagement,
    Finding,
    FindingStatus,
    FrontierTask,
    Mode,
    StateStore,
    Target,
    TaskStatus,
)
from autoresearch.taxonomy import TargetClass, TargetType


class RoundTripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_every_record_kind_round_trips_through_a_fresh_store(self):
        records = [
            Engagement(id="eng-1", name="Home router", mode=Mode.DIRECTED, seed="CVE-2024-0001"),
            Target(
                id="tgt-1",
                engagement_id="eng-1",
                asset="router-fw-1.2.3.bin",
                target_type=TargetType.FIRMWARE,
                description="vendor firmware image",
            ),
            Finding(
                id="fnd-1",
                engagement_id="eng-1",
                target_id="tgt-1",
                title="Stack overflow in httpd",
                status=FindingStatus.CONFIRMED,
                poc_ref="evidence/poc-1.py",
                snapshot_ref="autoresearch/snapshot:abc",
                evidence_refs=["evidence/bundle-1.tar"],
            ),
            FrontierTask(
                id="tsk-1",
                engagement_id="eng-1",
                target_id="tgt-1",
                description="Audit CGI handlers for unchecked strcpy",
                score=0.82,
                status=TaskStatus.IN_PROGRESS,
                equivalence_key="httpd:cgi:strcpy",
                checkpoint_ref="evidence/bundle-1.tar",
            ),
            DeadEnd(
                id="ded-1",
                engagement_id="eng-1",
                task_id="tsk-0",
                equivalence_key="httpd:auth:bypass",
                reason="auth check is constant-time and complete",
            ),
        ]
        writer = StateStore(self.tmp.name)
        for record in records:
            writer.put(record)

        # A fresh store instance models a new episode with no prior context.
        reader = StateStore(self.tmp.name)
        for record in records:
            loaded = reader.get(type(record), record.id)
            self.assertEqual(loaded, record)
            self.assertIs(type(loaded), type(record))
            self.assertEqual(reader.list(type(record)), [record])

        target = reader.get(Target, "tgt-1")
        self.assertIs(target.target_type, TargetType.FIRMWARE)
        self.assertIs(target.target_class, TargetClass.DEVICE)

    def test_list_filters_and_missing_records(self):
        store = StateStore(self.tmp.name)
        a = store.put(FrontierTask(id="t-a", engagement_id="e1", target_id="x", description="a"))
        store.put(FrontierTask(id="t-b", engagement_id="e2", target_id="x", description="b"))
        self.assertEqual(store.list(FrontierTask, engagement_id="e1"), [a])
        self.assertIsNone(store.get(FrontierTask, "nope"))
        self.assertEqual(store.list(DeadEnd), [])

    def test_overwrite_replaces_record(self):
        store = StateStore(self.tmp.name)
        task = store.put(FrontierTask(id="t-a", engagement_id="e1", target_id="x", description="a"))
        task.status = TaskStatus.DEAD_END
        store.put(task)
        self.assertIs(store.get(FrontierTask, "t-a").status, TaskStatus.DEAD_END)

    def test_rejects_path_traversal_ids(self):
        store = StateStore(self.tmp.name)
        with self.assertRaises(ValueError):
            store.get(Engagement, "../../etc/passwd")

    def test_confirmed_finding_requires_poc(self):
        with self.assertRaises(ValueError):
            Finding(
                id="f", engagement_id="e", target_id="t", title="x", status=FindingStatus.CONFIRMED
            )

    def test_unknown_schema_version_rejected(self):
        with self.assertRaises(ValueError):
            Engagement.from_dict(
                {"schema_version": 99, "id": "e", "name": "n", "mode": "directed", "seed": "s"}
            )
