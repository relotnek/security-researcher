"""Thin wrapper over the docker CLI."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

IMAGES_DIR = Path(__file__).parent / "images"


class DockerError(RuntimeError):
    pass


def docker(*args: str, check: bool = True, timeout: float | None = 300) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise DockerError(f"docker {' '.join(args[:3])}... failed: {proc.stderr.strip()}")
    return proc


def inspect(kind: str, name: str) -> dict[str, Any] | None:
    proc = docker(kind, "inspect", name, check=False)
    if proc.returncode != 0:
        return None
    return json.loads(proc.stdout)[0]


def ensure_image(name: str, context: Path, build_args: dict[str, str] | None = None) -> str:
    """Build ``context`` into an image tagged by content hash; reuse if present."""
    digest = hashlib.sha256()
    for path in sorted(p for p in context.rglob("*") if p.is_file()):
        digest.update(path.relative_to(context).as_posix().encode())
        digest.update(path.read_bytes())
    for key, value in sorted((build_args or {}).items()):
        digest.update(f"{key}={value}".encode())
    tag = f"{name}:{digest.hexdigest()[:12]}"
    if inspect("image", tag) is None:
        args = ["build", "-q", "-t", tag]
        for key, value in (build_args or {}).items():
            args += ["--build-arg", f"{key}={value}"]
        docker(*args, str(context), timeout=1200)
    return tag
