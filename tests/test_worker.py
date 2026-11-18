import tempfile
import unittest
from pathlib import Path

from autoresearch.boundary import ActionGuard
from autoresearch.containment.docker import docker
from autoresearch.scope import ActionClass, ScopeGate, ScopeRegistry
from autoresearch.state import Engagement, Finding, FindingStatus, FrontierTask, Mode, StateStore, Target, TaskStatus
from autoresearch.taxonomy import TargetType
from autoresearch.worker import (
    STAGES,
    Budget,
    Candidate,
    EvidenceBundle,
    FirmwarePipeline,
    MobilePipeline,
    NativePipeline,
    Observation,
    WebPipeline,
    Worker,
    WorkerContext,
    bundle_id,
    select_pipeline,
)

from .docker_support import ContainmentTestCase, requires_docker

FIRMWARE_SAMPLE = """#firmware config dump
device=home-router
version=1.2.3
ssid=HOME-NET
admin_password=hunter2
"""

WEB_ENDPOINTS = "/admin?debug=1\n/api/users\n/healthz\n"


# -- pipeline selection: no Docker needed (3.1) ----------------------------


class PipelineSelectionTest(unittest.TestCase):
    def _target(self, target_type):
        return Target(id="tgt", engagement_id="eng", asset="asset", target_type=target_type)

    def test_each_class_routes_to_its_pipeline(self):
        cases = {
            TargetType.FIRMWARE: FirmwarePipeline,
            TargetType.DEVICE: FirmwarePipeline,
            TargetType.NETWORK: FirmwarePipeline,
            TargetType.MOBILE_APP: MobilePipeline,
            TargetType.WEB_APP: WebPipeline,
            TargetType.BINARY: NativePipeline,
            TargetType.SOURCE_CODE: NativePipeline,
        }
        for target_type, pipeline_cls in cases.items():
            with self.subTest(target_type=target_type):
                self.assertIsInstance(select_pipeline(self._target(target_type)), pipeline_cls)

    def test_every_target_type_is_routable(self):
        for target_type in TargetType:
            self.assertIsNotNone(select_pipeline(self._target(target_type)))


# -- documentation matches the implemented stages (1.2) --------------------


class DocsTest(unittest.TestCase):
    def setUp(self):
        self.doc = (Path(__file__).resolve().parents[1] / "docs" / "worker.md").read_text()
        import autoresearch.worker as worker_mod

        self.module_doc = worker_mod.__doc__ or ""

    def test_lifecycle_stages_are_the_expected_five(self):
        self.assertEqual(STAGES, ("load", "plan", "work", "checkpoint", "terminate"))
        self.assertEqual(Worker.STAGES, STAGES)

    def test_docs_document_every_stage(self):
        for stage in STAGES:
            self.assertIn(stage, self.doc.lower(), f"docs/worker.md omits stage {stage!r}")
            self.assertIn(stage, self.module_doc.lower(), f"module docstring omits stage {stage!r}")

    def test_docs_document_inputs_and_outputs(self):
        for token in ("instance_id", "budget", "task_id", "Observation", "Candidate", "EvidenceBundle"):
            self.assertIn(token, self.doc, f"docs/worker.md omits {token}")


# -- a candidate is structurally unconfirmable -----------------------------


class CandidateRecordTest(unittest.TestCase):
    def test_candidate_cannot_be_confirmed(self):
        with self.assertRaises(ValueError):
            Candidate(
                id="cnd-1", engagement_id="e", target_id="t", task_id="k",
                hypothesis="x", status="confirmed",
            )  # fmt: skip


# -- Docker-backed worker tests --------------------------------------------


class WorkerTestCase(ContainmentTestCase):
    """A provisioned sandbox target with a worker wired to the double boundary."""

    PERMITTED = [ActionClass.STATIC_ANALYSIS, ActionClass.DYNAMIC_ANALYSIS]

    def setUp(self):
        super().setUp()
        self.store.put(Engagement(id="eng-1", name="bounty", mode=Mode.DISCOVERY, seed="prog"))
        ScopeRegistry(self.store).declare(
            "eng-1", in_scope=["sample/*"], permitted_actions=self.PERMITTED
        )
        self.guard = ActionGuard(
            self.store, ScopeGate(ScopeRegistry(self.store), self.audit), self.manager, self.audit
        )
        self.worker = Worker(self.store, self.guard, self.audit)

    def make_target(self, tid, asset, target_type):
        target = self.store.put(
            Target(id=tid, engagement_id="eng-1", asset=asset, target_type=target_type)
        )
        instance = self.provision(target)
        return target, instance

    def plant(self, instance, script):
        proc = docker("exec", instance.container, "sh", "-c", script, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def plant_firmware(self, instance):
        self.plant(instance, f"mkdir -p /target && cat > /target/fw.bin <<'EOF'\n{FIRMWARE_SAMPLE}EOF")

    def plant_web(self, instance):
        self.plant(instance, f"mkdir -p /target && cat > /target/endpoints.txt <<'EOF'\n{WEB_ENDPOINTS}EOF")

    def candidates(self):
        return self.store.list(Candidate)

    def confirmed_findings(self):
        return [f for f in self.store.list(Finding) if f.status is FindingStatus.CONFIRMED]


@requires_docker
class EpisodeLifecycleTest(WorkerTestCase):
    def test_episode_exits_at_budget_having_checkpointed(self):
        # The web plan yields 1 capture + 3 endpoint obligations = 4 actions.
        _, instance = self.make_target("tgt-web", "sample/app", TargetType.WEB_APP)
        self.plant_web(instance)

        result = self.worker.run_episode(
            engagement_id="eng-1", target_id="tgt-web", task_id="tsk-web1",
            instance_id=instance.id, budget=Budget(max_actions=2),
        )  # fmt: skip

        self.assertEqual(result.reason, "budget")
        self.assertEqual(result.budget_spent, 2)
        # The checkpoint is durable and carries the still-open obligations.
        bundle = self.store.get(EvidenceBundle, bundle_id("tsk-web1"))
        self.assertIsNotNone(bundle)
        self.assertTrue(bundle.open_obligations(), "budget-stopped episode left no open obligations")
        self.assertEqual(len(bundle.closed_obligations()), 2)
        # The stage sequence the episode emitted is a prefix-consistent subsequence of STAGES.
        stages = [e["stage"] for e in self.audit.entries("worker.stage")]
        self.assertEqual(stages, list(STAGES))

    def test_unknown_or_foreign_target_is_rejected(self):
        with self.assertRaises(Exception):
            self.worker.run_episode(
                engagement_id="eng-1", target_id="tgt-missing", task_id="tsk-x",
                instance_id=None, budget=Budget(max_actions=1),
            )  # fmt: skip


@requires_docker
class ResumeHandoffTest(WorkerTestCase):
    def test_bundle_lists_open_and_closed_obligations(self):
        _, instance = self.make_target("tgt-web", "sample/app", TargetType.WEB_APP)
        self.plant_web(instance)
        self.worker.run_episode(
            engagement_id="eng-1", target_id="tgt-web", task_id="tsk-r",
            instance_id=instance.id, budget=Budget(max_actions=2),
        )  # fmt: skip
        bundle = self.store.get(EvidenceBundle, bundle_id("tsk-r"))
        self.assertTrue(bundle.closed_obligations())
        self.assertTrue(bundle.open_obligations())
        statuses = {o["status"] for o in bundle.obligations}
        self.assertEqual(statuses, {"open", "closed"})

    def test_second_episode_resumes_open_without_rederiving_closed(self):
        _, instance = self.make_target("tgt-web", "sample/app", TargetType.WEB_APP)
        self.plant_web(instance)

        first = self.worker.run_episode(
            engagement_id="eng-1", target_id="tgt-web", task_id="tsk-r2",
            instance_id=instance.id, budget=Budget(max_actions=2),
        )  # fmt: skip
        self.assertEqual(first.reason, "budget")
        closed_after_first = {
            o["id"] for o in self.store.get(EvidenceBundle, bundle_id("tsk-r2")).closed_obligations()
        }
        first_obs_ids = {o.id for o in first.observations}

        second = self.worker.run_episode(
            engagement_id="eng-1", target_id="tgt-web", task_id="tsk-r2",
            instance_id=instance.id, budget=Budget(max_actions=10),
        )  # fmt: skip

        self.assertEqual(second.reason, "complete")
        self.assertEqual(second.bundle.episode_count, 2)
        # The second episode did not re-plan and did not re-touch closed obligations.
        second_obs_ids = {o.id for o in second.observations}
        self.assertFalse(first_obs_ids & second_obs_ids, "an observation was produced twice")
        second_closed = {o["id"] for o in second.bundle.closed_obligations()}
        self.assertTrue(closed_after_first <= second_closed)
        for ob in second.bundle.obligations:
            if ob["id"] in closed_after_first:
                self.assertEqual(ob["closed_in_episode"], first.episode_id, "a closed obligation was reworked")
        # One observation per obligation across both episodes: nothing re-derived.
        self.assertFalse(second.bundle.open_obligations())
        self.assertEqual(len(second.bundle.observation_ids), len(second.bundle.obligations))


@requires_docker
class FirmwarePipelineTest(WorkerTestCase):
    def test_firmware_pipeline_produces_observations_and_a_candidate(self):
        # A firmware image, analysed in a code sandbox (extraction + binary analysis).
        target, instance = self.make_target("tgt-fw", "sample/router-fw", TargetType.BINARY)
        self.plant_firmware(instance)

        result = self.worker.run_pipeline(
            FirmwarePipeline(), target=target, task_id="tsk-fw",
            instance_id=instance.id, budget=Budget(max_actions=5),
        )  # fmt: skip

        self.assertEqual(result.reason, "complete")
        self.assertEqual(result.pipeline, "firmware")
        categories = {o.category for o in result.observations}
        self.assertEqual(categories, {"extraction", "strings", "secret"})
        self.assertTrue(result.candidates, "firmware secret scan did not raise a candidate")
        cand = result.candidates[0]
        self.assertEqual(cand.status, "unconfirmed")
        self.assertTrue(any("hunter2" in e for e in cand.evidence))
        self.assertEqual(self.confirmed_findings(), [])


@requires_docker
class WebPipelineTest(WorkerTestCase):
    def test_web_pipeline_produces_observations_and_a_candidate(self):
        target, instance = self.make_target("tgt-web", "sample/app", TargetType.WEB_APP)
        self.plant_web(instance)

        result = self.worker.run_pipeline(
            WebPipeline(), target=target, task_id="tsk-w",
            instance_id=instance.id, budget=Budget(max_actions=10),
        )  # fmt: skip

        self.assertEqual(result.reason, "complete")
        endpoint_obs = [o for o in result.observations if o.category == "endpoint"]
        self.assertEqual(len(endpoint_obs), 3)
        vuln = [o for o in endpoint_obs if o.likely_vuln]
        self.assertEqual(len(vuln), 1)
        self.assertIn("/admin", vuln[0].data["endpoint"])
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].status, "unconfirmed")
        self.assertEqual(self.confirmed_findings(), [])


@requires_docker
class FenceEnforcementTest(WorkerTestCase):
    PERMITTED = [ActionClass.STATIC_ANALYSIS]  # dynamic/exploitation are NOT permitted

    def context(self, target, instance, task_id):
        bundle = self.worker._load_bundle(target, task_id, "native")
        return WorkerContext(
            worker=self.worker, target=target, task_id=task_id, instance_id=instance.id,
            bundle=bundle, budget=Budget(max_actions=10), episode_id="ep-test",
        )  # fmt: skip

    def test_out_of_scope_action_is_not_performed(self):
        target, instance = self.make_target("tgt-n", "sample/bin", TargetType.BINARY)
        self.plant(instance, "mkdir -p /target && echo marker > /target/x")
        ctx = self.context(target, instance, "tsk-f1")

        marker = "/target/should-not-exist"
        result = ctx.action(ActionClass.EXPLOITATION, ["sh", "-c", f"touch {marker}"])

        self.assertFalse(result.allowed)
        self.assertIn("scope", result.blocked_by)
        # The action never ran inside the instance.
        probe = docker("exec", instance.container, "test", "-e", marker, check=False)
        self.assertNotEqual(probe.returncode, 0, "a blocked action ran anyway")

    def test_authorized_action_executes_inside_containment(self):
        target, instance = self.make_target("tgt-n", "sample/bin", TargetType.BINARY)
        ctx = self.context(target, instance, "tsk-f2")

        marker = "/target/ran"
        result = ctx.action(ActionClass.STATIC_ANALYSIS, ["sh", "-c", f"mkdir -p /target && touch {marker} && hostname"])

        self.assertTrue(result.allowed)
        self.assertEqual(result.returncode, 0)
        container_host = docker("inspect", "-f", "{{.Config.Hostname}}", instance.container).stdout.strip()
        self.assertEqual(result.stdout.strip(), container_host)  # ran inside the instance
        probe = docker("exec", instance.container, "test", "-e", marker, check=False)
        self.assertEqual(probe.returncode, 0)

    def test_uncontained_action_is_not_performed(self):
        target, _ = self.make_target("tgt-n", "sample/bin", TargetType.BINARY)
        bundle = self.worker._load_bundle(target, "tsk-f3", "native")
        ctx = WorkerContext(
            worker=self.worker, target=target, task_id="tsk-f3", instance_id=None,
            bundle=bundle, budget=Budget(max_actions=10), episode_id="ep-test",
        )  # fmt: skip
        result = ctx.action(ActionClass.STATIC_ANALYSIS, ["sh", "-c", "echo hi"])
        self.assertFalse(result.allowed)
        self.assertIn("containment", result.blocked_by)


@requires_docker
class CandidateEmissionTest(WorkerTestCase):
    def test_likely_vuln_yields_unconfirmed_candidate_never_a_finding(self):
        target, instance = self.make_target("tgt-fw", "sample/fw", TargetType.BINARY)
        self.plant_firmware(instance)
        result = self.worker.run_pipeline(
            FirmwarePipeline(), target=target, task_id="tsk-c",
            instance_id=instance.id, budget=Budget(max_actions=5),
        )  # fmt: skip

        self.assertEqual(len(result.candidates), 1)
        stored = self.candidates()
        self.assertEqual(len(stored), 1)
        cand = stored[0]
        self.assertEqual(cand.status, "unconfirmed")
        self.assertTrue(cand.hypothesis)
        self.assertTrue(cand.evidence)
        self.assertTrue(cand.reproduction_leads)
        self.assertEqual(cand.source_episode, result.episode_id)
        # No finding of any kind was written, let alone a confirmed one.
        self.assertEqual(self.store.list(Finding), [])
        self.assertEqual(self.confirmed_findings(), [])


@requires_docker
class IntegrationTest(WorkerTestCase):
    def test_contained_worker_runs_within_budget_emits_candidate_and_resumes(self):
        target, instance = self.make_target("tgt-web", "sample/app", TargetType.WEB_APP)
        self.plant_web(instance)
        # A dispatching frontier task, so we can check the checkpoint link.
        self.store.put(
            FrontierTask(
                id="tsk-int", engagement_id="eng-1", target_id="tgt-web",
                objective="probe the application surface", action_class=str(ActionClass.DYNAMIC_ANALYSIS),
                estimates={"likelihood": 0.5, "impact": 5, "value": 5, "cost": 2},
                provenance={"source": "test"}, status=TaskStatus.IN_PROGRESS,
            )  # fmt: skip
        )

        first = self.worker.run_episode(
            engagement_id="eng-1", target_id="tgt-web", task_id="tsk-int",
            instance_id=instance.id, budget=Budget(max_actions=2),
        )  # fmt: skip
        self.assertEqual(first.reason, "budget")
        self.assertTrue(first.observations)
        # The vulnerable endpoint is captured first, so the candidate lands in episode one.
        self.assertTrue(first.candidates, "no candidate emitted in the dispatched episode")

        # The checkpoint is resumable and linked from the task.
        linked = self.store.get(FrontierTask, "tsk-int")
        self.assertEqual(linked.checkpoint_ref, bundle_id("tsk-int"))

        second = self.worker.run_episode(
            engagement_id="eng-1", target_id="tgt-web", task_id="tsk-int",
            instance_id=instance.id, budget=Budget(max_actions=10),
        )  # fmt: skip
        self.assertEqual(second.reason, "complete")
        self.assertEqual(second.bundle.episode_count, 2)
        self.assertFalse(second.bundle.open_obligations())
        # Observations cover every obligation exactly once across the two episodes.
        self.assertEqual(len(second.bundle.observation_ids), len(second.bundle.obligations))
        self.assertEqual(self.confirmed_findings(), [])


if __name__ == "__main__":
    unittest.main()
