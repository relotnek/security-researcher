import unittest

from autoresearch.containment import ContainmentError, SandboxSpec, VMSpec
from autoresearch.containment.docker import inspect
from autoresearch.state import Target
from autoresearch.taxonomy import ContainmentProfile, TargetType

from .docker_support import ContainmentTestCase, requires_docker

CODE_TARGET = Target(id="tgt-code", engagement_id="eng-1", asset="acme/widget", target_type=TargetType.SOURCE_CODE)


@requires_docker
class DockerSandboxTest(ContainmentTestCase):
    def sh(self, instance, script, timeout=60):
        return self.manager.exec_in(instance, ["sh", "-c", script], timeout=timeout)

    def test_code_target_gets_a_running_sandbox_with_default_deny_egress(self):
        instance = self.provision(CODE_TARGET, allowlist=["allowed.test"])
        allowed_ip = self.add_upstream(instance, "allowed.test", "ALLOWED-BODY")
        blocked_ip = self.add_upstream(instance, "blocked.test", "BLOCKED-BODY")

        # The container starts, in the Docker-sandbox profile, on an internal network.
        self.assertIs(instance.profile, ContainmentProfile.DOCKER_SANDBOX)
        info = inspect("container", instance.container)
        self.assertTrue(info["State"]["Running"])
        self.assertEqual(list(info["NetworkSettings"]["Networks"]), [instance.network])
        self.assertTrue(inspect("network", instance.network)["Internal"])
        self.assertEqual(info["HostConfig"]["CapDrop"], ["ALL"])
        self.assertGreater(info["HostConfig"]["Memory"], 0)
        self.assertGreater(info["HostConfig"]["PidsLimit"], 0)

        # Allowlisted host: reachable, through the gateway only.
        ok = self.sh(instance, "wget -q -T 10 -O- http://allowed.test/")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("ALLOWED-BODY", ok.stdout)

        # Non-allowlisted host: refused by the gateway...
        denied = self.sh(instance, "wget -q -T 10 -O- http://blocked.test/")
        self.assertNotEqual(denied.returncode, 0)
        self.assertNotIn("BLOCKED-BODY", denied.stdout)
        self.assertIn("403", denied.stderr)
        self.assertIn("DENY", self.manager.gateway_log(instance))
        self.assertIn("dst=blocked.test:80", self.manager.gateway_log(instance))

        # ...and unreachable when the sandbox bypasses the proxy: there is no
        # route off the internal network, not even to hosts that are live.
        for ip in (blocked_ip, allowed_ip, "1.1.1.1"):
            with self.subTest(direct=ip):
                direct = self.sh(instance, f"http_proxy= wget -q -T 5 -O- http://{ip}/")
                self.assertNotEqual(direct.returncode, 0)
                self.assertNotIn("BODY", direct.stdout)
        self.assertNotIn("default", self.sh(instance, "ip route").stdout)

        # No DNS path to the outside either.
        dns = self.sh(instance, "nslookup -timeout=3 example.com")
        self.assertNotEqual(dns.returncode, 0)

        # An allowlisted name on a non-allowlisted port is still denied.
        port = self.sh(instance, "wget -q -T 10 -O- http://allowed.test:8080/")
        self.assertIn("403", port.stderr)

    def test_empty_allowlist_denies_everything(self):
        instance = self.provision(CODE_TARGET)
        self.add_upstream(instance, "allowed.test", "ALLOWED-BODY")
        result = self.sh(instance, "wget -q -T 10 -O- http://allowed.test/")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("ALLOWED-BODY", result.stdout)

    def test_profile_follows_target_class_not_the_caller(self):
        with self.assertRaises(ContainmentError):
            self.manager.provision(CODE_TARGET, vm=VMSpec(image="whatever"))
        firmware = Target(id="tgt-fw", engagement_id="eng-1", asset="fw.bin", target_type=TargetType.FIRMWARE)
        with self.assertRaises(ContainmentError):
            self.manager.provision(firmware, sandbox=SandboxSpec())

    def test_failed_provisioning_leaves_nothing_behind(self):
        with self.assertRaises(ContainmentError):
            self.manager.provision(CODE_TARGET, sandbox=SandboxSpec(image="autoresearch/does-not-exist:nope"))
        failed = self.audit.entries("containment.provision_failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(self.manager.resources(failed[0]["instance_id"]), {"containers": [], "networks": []})


if __name__ == "__main__":
    unittest.main()
