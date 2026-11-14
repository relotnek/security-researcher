import tempfile
import unittest
from pathlib import Path

from autoresearch.audit import AuditLog
from autoresearch.scope import ActionClass, ScopeGate, ScopeRegistry
from autoresearch.state import StateStore


class ScopeTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = StateStore(self.root / "state")
        self.registry = ScopeRegistry(self.store)
        self.audit = AuditLog(self.root / "audit.jsonl")
        self.gate = ScopeGate(self.registry, self.audit)
        self.registry.declare(
            "eng-1",
            in_scope=["app.example.com", "*.lab.example.com", "10.20.0.0/24"],
            forbidden=["prod.lab.example.com", "10.20.0.1"],
            permitted_actions=[ActionClass.STATIC_ANALYSIS, ActionClass.NETWORK_PROBE],
        )


class RegistryTest(ScopeTestCase):
    def test_scope_reads_back_exactly(self):
        scope = ScopeRegistry(StateStore(self.root / "state")).get("eng-1")
        self.assertEqual(scope.in_scope, ["app.example.com", "*.lab.example.com", "10.20.0.0/24"])
        self.assertEqual(scope.forbidden, ["prod.lab.example.com", "10.20.0.1"])
        self.assertEqual(scope.permitted_actions, ["static_analysis", "network_probe"])

    def test_scopes_are_per_engagement(self):
        self.registry.declare("eng-2", in_scope=["other.test"], permitted_actions=["fuzzing"])
        self.assertEqual(self.registry.get("eng-2").in_scope, ["other.test"])
        self.assertEqual(self.registry.get("eng-1").permitted_actions, ["static_analysis", "network_probe"])
        self.assertIsNone(self.registry.get("eng-3"))

    def test_unknown_action_class_rejected_at_declaration(self):
        with self.assertRaises(ValueError):
            self.registry.declare("eng-x", in_scope=["a"], permitted_actions=["anything_goes"])


class GateTest(ScopeTestCase):
    def assertDeniedAndLogged(self, engagement, asset, action, reason_contains):
        before = len(self.audit.entries("scope.deny"))
        decision = self.gate.authorize(engagement, asset, action)
        self.assertFalse(decision.allowed)
        self.assertIn(reason_contains, decision.reason)
        denials = self.audit.entries("scope.deny")
        self.assertEqual(len(denials), before + 1)
        self.assertEqual(denials[-1]["asset"], str(asset))
        self.assertEqual(denials[-1]["action_class"], str(action))
        self.assertEqual(denials[-1]["engagement_id"], str(engagement))
        self.assertIn(reason_contains, denials[-1]["reason"])

    def test_in_scope_and_permitted_is_allowed(self):
        for asset in ("app.example.com", "APP.example.com", "db.lab.example.com", "10.20.0.77"):
            with self.subTest(asset=asset):
                self.assertTrue(self.gate.authorize("eng-1", asset, ActionClass.NETWORK_PROBE))
        self.assertEqual(len(self.audit.entries("scope.allow")), 4)

    def test_out_of_scope_target_denied_and_logged(self):
        self.assertDeniedAndLogged("eng-1", "evil.example.org", ActionClass.NETWORK_PROBE, "not in scope")
        self.assertDeniedAndLogged("eng-1", "10.20.1.5", ActionClass.NETWORK_PROBE, "not in scope")

    def test_forbidden_action_class_denied_and_logged(self):
        self.assertDeniedAndLogged("eng-1", "app.example.com", ActionClass.EXPLOITATION, "not permitted")

    def test_forbidden_asset_wins_over_in_scope(self):
        self.assertDeniedAndLogged("eng-1", "prod.lab.example.com", ActionClass.NETWORK_PROBE, "forbidden")
        self.assertDeniedAndLogged("eng-1", "10.20.0.1", ActionClass.NETWORK_PROBE, "forbidden")

    def test_indeterminate_is_denied(self):
        self.assertDeniedAndLogged("eng-unknown", "app.example.com", ActionClass.NETWORK_PROBE, "no scope")
        self.assertDeniedAndLogged("eng-1", "", ActionClass.NETWORK_PROBE, "no target asset")
        self.assertDeniedAndLogged("eng-1", "app.example.com", "made_up_action", "unknown action class")
        # A lookup that blows up must deny, not raise.
        self.assertDeniedAndLogged("../escape", "app.example.com", ActionClass.NETWORK_PROBE, "indeterminate")

    def test_corrupt_scope_record_is_denied(self):
        (self.root / "state" / "scopes" / "eng-1.json").write_text("{not json")
        self.assertDeniedAndLogged("eng-1", "app.example.com", ActionClass.NETWORK_PROBE, "indeterminate")
