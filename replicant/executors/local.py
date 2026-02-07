"""Docker build / shell / cleanup."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
import docker
from docker.errors import APIError, BuildError, ImageNotFound
from replicant.utils.config import EnvMeta, LOGS, ensure_dirs


def check_docker():
    try: docker.from_env().ping()
    except Exception:
        raise RuntimeError(
            "Docker is not running. Install Docker Desktop and start it."
        )

def has_gpu() -> bool:
    try: return "nvidia" in docker.from_env().info().get("Runtimes", {})
    except Exception: return False

def build(build_dir: str | Path, tag: str, verbose=False) -> bool:
    ensure_dirs()
    log_path = LOGS / f"{tag}.log"
    client = docker.from_env()
    lines: list[str] = []
    try:
        _, log = client.images.build(path=str(build_dir), tag=tag, rm=True, forcerm=True)
        for chunk in log:
            if s := chunk.get("stream", ""):
                lines.append(s)
                if verbose: print(s, end="")
        log_path.write_text("".join(lines))
        return True
    except BuildError as e:
        for chunk in e.build_log:
            if s := (chunk.get("stream","") or chunk.get("error","")):
                lines.append(s)
                if verbose: print(s, end="", file=sys.stderr)
        log_path.write_text("".join(lines))
        return False
    except APIError as e:
        log_path.write_text(f"Docker API error: {e}\n")
        return False

def shell(meta: EnvMeta, gpu=False):
    cmd = ["docker","run","--rm","-it","-v",f"{meta.code_path}:/workspace","-w","/workspace"]
    if gpu and has_gpu(): cmd += ["--gpus","all"]
    cmd += [meta.docker_image, "/bin/bash"]
    if sys.platform != "win32": os.execvp("docker", cmd)
    else: subprocess.run(cmd)

def remove_image(tag: str) -> bool:
    try: docker.from_env().images.remove(tag, force=True); return True
    except (ImageNotFound, APIError): return False
