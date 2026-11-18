import unittest

from autoresearch.boundary import ActionGuard
from autoresearch.containment.docker import docker
from autoresearch.scope import ActionClass, ScopeGate, ScopeRegistry
from autoresearch.state import Engagement, Mode, Target
from autoresearch.taxonomy import TargetType

from .docker_support import ContainmentTestCase, requires_docker


@requires_docker
class DoubleBoundaryTest(ContainmentTestCase):
    def setUp(self):
        super().setUp()
        self.store.put(Engagement(id="eng-1", name="Acme bounty", mode=Mode.DISCOVERY, seed="acme-bbp"))
        ScopeRegistry(self.store).declare(
            "eng-1",
            in_scope=["acme/*"],
            forbidden=["acme/billing"],
            permitted_actions=[ActionClass.STATIC_ANALYSIS, ActionClass.DYNAMIC_ANALYSIS],
        )
        self.widget = self.store.put(
            Target(id="tgt-widget", engagement_id="eng-1", asset="acme/widget", target_type=TargetType.SOURCE_CODE)
        )
        self.billing = self.store.put(
            Target(id="tgt-billing", engagement_id="eng-1", asset="acme/billing", target_type=TargetType.WEB_APP)
        )
        self.guard = ActionGuard(self.store, ScopeGate(ScopeRegistry(self.store), self.audit), self.manager, self.audit)
        self.counter = 0

    def attempt(self, target, action, instance_id):
        """Try an action that leaves a marker where it ran."""
        self.counter += 1
        marker = f"/tmp/ran-{self.counter}"
        result = self.guard.run(
            engagement_id="eng-1",
            target_id=target.id,
            action_class=action,
            instance_id=instance_id,
            argv=["sh", "-c", f"touch {marker} && hostname"],
        )
        return result, marker

    def ran_in(self, instance, marker) -> bool:
        return docker("exec", instance.container, "test", "-e", marker, check=False).returncode == 0

    def assert_blocked(self, result, marker, boundaries, instances):
        self.assertFalse(result.allowed)
        self.assertEqual(result.blocked_by, boundaries)
        self.assertIsNone(result.returncode)
        for instance in instances:
            self.assertFalse(self.ran_in(instance, marker), "blocked action ran anyway")
        logged = self.audit.entries("action.blocked")[-1]
        self.assertEqual(tuple(logged["blocked_by"]), boundaries)
        self.assertIn(marker, " ".join(logged["argv"]))

    def test_action_requires_both_boundaries(self):
        widget_box = self.provision(self.widget)
        billing_box = self.provision(self.billing)
        boxes = [widget_box, billing_box]

        # Both boundaries pass: the action runs, and runs inside the instance.
        result, marker = self.attempt(self.widget, ActionClass.DYNAMIC_ANALYSIS, widget_box.id)
        self.assertTrue(result.allowed)
        self.assertEqual(result.returncode, 0)
        container_hostname = docker("inspect", "-f", "{{.Config.Hostname}}", widget_box.container).stdout.strip()
        self.assertEqual(result.stdout.strip(), container_hostname)
        self.assertTrue(self.ran_in(widget_box, marker))
        executed = self.audit.entries("action.executed")
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0]["instance_id"], widget_box.id)
        self.assertEqual(self.audit.entries("action.blocked"), [])

        # Scope fails, containment passes: forbidden asset with a perfectly good instance.
        scope_denials = len(self.audit.entries("scope.deny"))
        result, marker = self.attempt(self.billing, ActionClass.DYNAMIC_ANALYSIS, billing_box.id)
        self.assert_blocked(result, marker, ("scope",), boxes)
        self.assertEqual(len(self.audit.entries("scope.deny")), scope_denials + 1)

        # Scope fails on the action class.
        result, marker = self.attempt(self.widget, ActionClass.EXPLOITATION, widget_box.id)
        self.assert_blocked(result, marker, ("scope",), boxes)

        # Containment fails, scope passes: in-scope target, permitted action, but...
        containment_denials = len(self.audit.entries("containment.deny"))
        # ...no instance at all,
        result, marker = self.attempt(self.widget, ActionClass.DYNAMIC_ANALYSIS, None)
        self.assert_blocked(result, marker, ("containment",), boxes)
        # ...an instance that does not exist,
        result, marker = self.attempt(self.widget, ActionClass.DYNAMIC_ANALYSIS, "ins-000000000000")
        self.assert_blocked(result, marker, ("containment",), boxes)
        # ...another target's instance,
        result, marker = self.attempt(self.widget, ActionClass.DYNAMIC_ANALYSIS, billing_box.id)
        self.assert_blocked(result, marker, ("containment",), boxes)
        self.assertEqual(len(self.audit.entries("containment.deny")), containment_denials + 3)

        # Both fail.
        result, marker = self.attempt(self.billing, ActionClass.EXPLOITATION, widget_box.id)
        self.assert_blocked(result, marker, ("scope", "containment"), boxes)

        # An unknown target is denied by scope.
        ghost = Target(id="tgt-ghost", engagement_id="eng-1", asset="acme/widget", target_type=TargetType.BINARY)
        result, marker = self.attempt(ghost, ActionClass.DYNAMIC_ANALYSIS, widget_box.id)
        self.assert_blocked(result, marker, ("scope", "containment"), boxes)

        # Only the one authorized, contained action ever executed.
        self.assertEqual(len(self.audit.entries("action.executed")), 1)

    def test_instance_that_loses_isolation_is_no_longer_containment(self):
        box = self.provision(self.widget)
        result, _ = self.attempt(self.widget, ActionClass.STATIC_ANALYSIS, box.id)
        self.assertTrue(result.allowed)

        # Someone attaches the sandbox to a routable network behind our back.
        docker("network", "connect", box.egress_network, box.container)
        result, marker = self.attempt(self.widget, ActionClass.STATIC_ANALYSIS, box.id)
        self.assert_blocked(result, marker, ("containment",), [box])
        self.assertIn("other than its isolated network", result.reasons[0])

    def test_torn_down_instance_is_no_longer_containment(self):
        box = self.provision(self.widget)
        self.manager.teardown(box.id)
        result, marker = self.attempt(self.widget, ActionClass.STATIC_ANALYSIS, box.id)
        self.assert_blocked(result, marker, ("containment",), [])
        self.assertIn("torn down", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
