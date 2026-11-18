import re
import unittest

from autoresearch.containment import VMSpec
from autoresearch.containment.docker import inspect
from autoresearch.state import Target
from autoresearch.taxonomy import ContainmentProfile, TargetType, profile_for

from .docker_support import ContainmentTestCase, probe_guest_image, requires_docker, wait_for

BOOT_TIMEOUT = 600  # generous: the guest may be running under pure emulation


def probe_spec(**cmdline: str) -> VMSpec:
    args = " ".join(f"asr.{k}={v}" for k, v in cmdline.items())
    return VMSpec(
        image=probe_guest_image(),
        kernel="/vm/vmlinuz",
        initrd="/vm/initramfs.gz",
        append=f"console=ttyS0 quiet {args}",
        disk_size="16M",
        memory_mb=192,
    )


@requires_docker
class IsolatedSegmentTest(ContainmentTestCase):
    def wait_for_console(self, instance, marker: str) -> str:
        found = wait_for(lambda: marker in self.manager.console(instance), BOOT_TIMEOUT, interval=2)
        console = self.manager.console(instance)
        self.assertTrue(found, f"{marker} never appeared on the console:\n{console[-3000:]}")
        return console

    def test_device_targets_boot_on_an_isolated_segment_with_allowlist_only_egress(self):
        for target_type in (TargetType.FIRMWARE, TargetType.DEVICE, TargetType.NETWORK):
            self.assertIs(profile_for(target_type), ContainmentProfile.ISOLATED_SEGMENT)
        target = Target(id="tgt-fw", engagement_id="eng-1", asset="router-fw.bin", target_type=TargetType.FIRMWARE)
        instance = self.provision(
            target,
            allowlist=["allowed.test"],
            vm=probe_spec(allowed="allowed.test", blocked="blocked.test"),
        )
        blocked_ip = self.add_upstream(instance, "blocked.test", "BLOCKED-BODY")
        self.add_upstream(instance, "allowed.test", "ALLOWED-BODY", files={"direct.txt": f"{blocked_ip} 1.1.1.1"})

        # Provisioned on an isolated segment: internal network, no other attachment.
        self.assertIs(instance.profile, ContainmentProfile.ISOLATED_SEGMENT)
        info = inspect("container", instance.container)
        self.assertEqual(list(info["NetworkSettings"]["Networks"]), [instance.network])
        network = inspect("network", instance.network)
        self.assertTrue(network["Internal"])
        self.assertFalse(info["HostConfig"]["Privileged"])

        # The instance boots.
        console = self.wait_for_console(instance, "ASR_PROBE_DONE")
        self.assertIn(f"ASR_BOOT_OK ip={instance.guest_ip}/24 mac={instance.guest_mac}", console)

        # The allowlist is the only way out.
        self.assertIn("ASR_ALLOWED=[ALLOWED-BODY]", console)
        self.assertIn("ASR_BLOCKED=DENIED", console)
        self.assertNotIn("BLOCKED-BODY", console)

        # No route to the outside: the guest has no default route, and inventing
        # one via the gateway gets it nowhere because the gateway does not route.
        routes = re.search(r"ASR_ROUTES_BEFORE=\[(.*?)\]", console).group(1)
        self.assertNotIn("default", routes)
        self.assertIn("ASR_DEFAULT_ROUTE_ADDED", console)
        for ip in (blocked_ip, "1.1.1.1"):
            self.assertIn(f"ASR_DIRECT_{ip}=BLOCKED", console)
            self.assertIn(f"ASR_ROUTED_{ip}=BLOCKED", console)
        self.assertNotIn("REACHED", console)

        # The guest is a host on the segment in its own right: the gateway saw
        # its address, not the runner container's.
        gateway_log = self.manager.gateway_log(instance)
        self.assertIn(f"ALLOW src={instance.guest_ip} dst=allowed.test:80", gateway_log)
        self.assertIn(f"DENY src={instance.guest_ip} dst=blocked.test:80", gateway_log)


if __name__ == "__main__":
    unittest.main()
