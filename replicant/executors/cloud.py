"""Cloud (EC2) executor: build, shell, and cleanup via SSH + ECR."""
from __future__ import annotations
import subprocess
from pathlib import Path

from replicant.providers.base import CloudResources
from replicant.utils.config import EnvMeta


class CloudExecutor:
    """Executes Docker operations on a remote EC2 instance backed by ECR."""

    def __init__(self, resources: CloudResources) -> None:
        self.resources = resources

    # ── internals ────────────────────────────────────────────────────────────

    def _ssh_opts(self) -> list[str]:
        return [
            "-i", str(self.resources.ssh_key_path),
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
        ]

    def _remote(self) -> str:
        return f"ubuntu@{self.resources.instance_ip}"

    def _run_ssh(self, command: str, capture: bool = True) -> subprocess.CompletedProcess:
        cmd = ["ssh", *self._ssh_opts(), self._remote(), command]
        return subprocess.run(cmd, capture_output=capture, text=True)

    def _run_rsync(self, src: str, dst: str, verbose: bool = False) -> subprocess.CompletedProcess:
        ssh_str = "ssh " + " ".join(self._ssh_opts())
        flags = "-avz" if verbose else "-az"
        cmd = ["rsync", flags, "-e", ssh_str, src, dst]
        return subprocess.run(cmd, capture_output=not verbose, text=True)

    # ── Executor protocol ────────────────────────────────────────────────────

    def _ecr_login_cmd(self) -> str:
        """Authenticate Docker with ECR using the instance role.

        Resets ~/.docker/config.json first to clear any broken credential store
        that Ubuntu's docker.io package ships with ('not implemented' errors).
        """
        registry = self.resources.ecr_repo_url.split("/")[0]
        return (
            "mkdir -p ~/.docker && printf '{}' > ~/.docker/config.json && "
            f"aws ecr get-login-password --region {self.resources.region} "
            f"| docker login --username AWS --password-stdin {registry}"
        )

    def build(self, build_dir: Path, tag: str, verbose: bool = False) -> bool:
        """
        1. rsync build context to EC2
        2. docker build on remote
        3. ECR login via instance role
        4. docker tag + push to ECR
        """
        build_dir = Path(build_dir)
        remote = self._remote()
        image_uri = f"{self.resources.ecr_repo_url}:latest"

        # 1. rsync
        r = self._run_rsync(f"{build_dir}/", f"{remote}:/tmp/replicant-build/", verbose=verbose)
        if r.returncode != 0:
            if verbose:
                print(r.stderr)
            return False

        # 2. docker build — stream always so long builds don't look stalled
        r = self._run_ssh(f"docker build -t {tag} /tmp/replicant-build/", capture=False)
        if r.returncode != 0:
            return False

        # 3. ECR login — stream so auth errors are visible
        r = self._run_ssh(self._ecr_login_cmd(), capture=False)
        if r.returncode != 0:
            return False

        # 4. tag + push to ECR — stream so layer progress is visible
        r = self._run_ssh(f"docker tag {tag} {image_uri}", capture=False)
        if r.returncode != 0:
            return False

        r = self._run_ssh(f"docker push {image_uri}", capture=False)
        if r.returncode != 0:
            return False

        return True

    def sync_code(self, code_path: Path) -> None:
        """Rsync the local repo clone to ~/code on the instance."""
        self._run_rsync(f"{code_path}/", f"{self._remote()}:/home/ubuntu/code/")

    def shell(self, meta: EnvMeta, gpu: bool = False) -> None:
        """
        Pull image from ECR if not cached, then launch an interactive shell
        with the code (already synced during setup) mounted at /workspace.
        """
        image_uri = f"{self.resources.ecr_repo_url}:latest"
        remote = self._remote()

        # Login to ECR, then pull if the image is not already cached.
        self._run_ssh(self._ecr_login_cmd())
        pull_cmd = (
            f"docker image inspect {image_uri} > /dev/null 2>&1 || "
            f"docker pull {image_uri}"
        )
        self._run_ssh(pull_cmd, capture=False)

        gpu_flag = "--gpus all" if gpu else ""
        run_cmd = (
            f"docker run -it --rm {gpu_flag} "
            f"-v /home/ubuntu/code:/workspace -w /workspace {image_uri} /bin/bash"
        ).strip()

        cmd = ["ssh", "-t", *self._ssh_opts(), remote, run_cmd]
        subprocess.run(cmd)

    def remove_image(self, tag: str) -> None:
        """Remove Docker image from ECR and evict from the remote instance cache."""
        import boto3

        image_uri = f"{self.resources.ecr_repo_url}:latest"

        # Evict from remote cache (ignore errors — instance may be gone)
        self._run_ssh(f"docker rmi {image_uri} || true")

        # Delete from ECR via boto3 (works even if the instance is off)
        repo_name = self.resources.ecr_repo_url.split("/", 1)[1]
        try:
            ecr = boto3.client("ecr", region_name=self.resources.region)
            ecr.batch_delete_image(
                repositoryName=repo_name,
                imageIds=[{"imageTag": "latest"}],
            )
        except Exception:
            pass
