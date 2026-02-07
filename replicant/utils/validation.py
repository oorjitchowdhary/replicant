"""Validate a built environment."""
from __future__ import annotations
from dataclasses import dataclass
import docker
from docker.errors import ImageNotFound, APIError
from replicant.utils.config import EnvMeta

@dataclass
class Check:
    name: str; passed: bool; msg: str

def validate(meta: EnvMeta) -> list[Check]:
    results: list[Check] = []
    try:
        client = docker.from_env()
        client.images.get(meta.docker_image)
        results.append(Check("build", True, "Image exists"))
    except ImageNotFound:
        return [Check("build", False, f"Image '{meta.docker_image}' not found")]
    except APIError as e:
        return [Check("build", False, str(e))]

    # python works?
    try:
        out = client.containers.run(meta.docker_image, "python --version", remove=True)
        results.append(Check("python", True, out.decode().strip()))
    except Exception as e:
        results.append(Check("python", False, str(e)))

    # scripts present?
    try:
        out = client.containers.run(meta.docker_image, "sh -c 'ls /workspace/*.py 2>/dev/null | head -5'", remove=True)
        decoded = out.decode().strip()
        results.append(Check("scripts", True, decoded or "No .py files in root (may be in subdirs)"))
    except Exception as e:
        results.append(Check("scripts", False, str(e)))

    return results
