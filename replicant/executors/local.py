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

class LocalExecutor:
    """Runs Docker builds and shells on the local machine."""

    def build(self, build_dir: str | Path, tag: str, verbose: bool = False) -> bool:
        ensure_dirs()
        log_path = LOGS / f"{tag}.log"

        def _as_text(value) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return str(value)

        env = os.environ.copy()
        env['DOCKER_BUILDKIT'] = '1'

        cmd = [
            "docker", "build",
            "--platform", "linux/amd64",
            "-t", tag,
            "-f", str(Path(build_dir) / "Dockerfile"),
            str(build_dir)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                env=env
            )

            output = _as_text(result.stdout) + _as_text(result.stderr)
            log_path.write_text(output)

            if verbose:
                print(output, end="")

            return result.returncode == 0

        except Exception as e:
            log_path.write_text(f"Build error: {e}\n")
            return False

    def shell(self, meta: EnvMeta, gpu: bool = False) -> None:
        cmd = ["docker", "run", "--rm", "-it", "-v", f"{meta.code_path}:/workspace", "-w", "/workspace"]
        if gpu and has_gpu():
            cmd += ["--gpus", "all"]
        cmd += [meta.docker_image, "/bin/bash"]
        if sys.platform != "win32":
            os.execvp("docker", cmd)
        else:
            subprocess.run(cmd)

    def remove_image(self, tag: str) -> bool:
        try:
            docker.from_env().images.remove(tag, force=True)
            return True
        except (ImageNotFound, APIError):
            return False


# Module-level functions preserved for backward compatibility.
_local = LocalExecutor()


def build(build_dir: str | Path, tag: str, verbose=False) -> bool:
    return _local.build(build_dir, tag, verbose)

def shell(meta: EnvMeta, gpu=False):
    _local.shell(meta, gpu)

def remove_image(tag: str) -> bool:
    return _local.remove_image(tag)
