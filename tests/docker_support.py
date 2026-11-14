"""Shared fixtures for tests that need a real Docker daemon."""

import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from autoresearch.audit import AuditLog
from autoresearch.containment import ContainmentManager
from autoresearch.containment.docker import docker, ensure_image
from autoresearch.state import StateStore


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


requires_docker = unittest.skipUnless(docker_available(), "requires a Docker daemon")


def wait_for(predicate, timeout: float, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(interval)


class ContainmentTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = StateStore(self.root / "state")
        self.audit = AuditLog(self.root / "audit.jsonl")
        self.manager = ContainmentManager(self.store, self.audit)

    def provision(self, *args, **kwargs):
        instance = self.manager.provision(*args, **kwargs)
        self.addCleanup(self.manager.teardown, instance.id)
        return instance

    def add_upstream(self, instance, name: str, body: str, files: dict[str, str] | None = None) -> str:
        """Start an HTTP server named ``name`` on the instance's egress network
        - a stand-in for a host on the outside. Returns its IP there."""
        write = "".join(f" && echo {content} > /www/{fname}" for fname, content in (files or {}).items())
        container = f"{instance.egress_network}-{name.replace('.', '-')}"
        docker(
            "run", "-d", "--name", container, "--label", f"autoresearch.instance={instance.id}",
            "--network", instance.egress_network, "--network-alias", name,
            "python:3.13-alpine", "sh", "-c",
            f"mkdir -p /www && echo {body} > /www/index.html{write} && exec python3 -m http.server 80 -d /www",
        )  # fmt: skip
        ip = docker(
            "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container
        ).stdout.strip()
        probe = ["python3", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1', timeout=2)"]
        ready = wait_for(lambda: docker("exec", container, *probe, check=False).returncode == 0, 30)
        self.assertTrue(ready, f"upstream {name} did not start")
        return ip


def probe_guest_image() -> str:
    """Build the probe-guest VM image on top of the vm-runner image."""
    return ensure_image(
        "autoresearch/test-probe-guest",
        Path(__file__).parent / "fixtures" / "probe-guest",
        {"RUNNER": ContainmentManager.vm_runner_image()},
    )
