"""Cloud (EC2) executor: build, shell, and cleanup via SSH + S3."""
from __future__ import annotations
import subprocess
from pathlib import Path

from replicant.providers.base import CloudResources
from replicant.utils.config import EnvMeta


class CloudExecutor:
    """Executes Docker operations on a remote EC2 instance."""

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

    def _run_rsync(self, src: str, dst: str) -> subprocess.CompletedProcess:
        ssh_str = "ssh " + " ".join(self._ssh_opts())
        cmd = ["rsync", "-az", "-e", ssh_str, src, dst]
        return subprocess.run(cmd, capture_output=True, text=True)

    # ── Executor protocol ────────────────────────────────────────────────────

    def build(self, build_dir: Path, tag: str, verbose: bool = False) -> bool:
        """
        1. rsync build context to EC2
        2. docker build on remote
        3. docker save + gzip
        4. upload .tar.gz to S3
        """
        build_dir = Path(build_dir)
        remote = self._remote()
        bucket = self.resources.s3_bucket

        # 1. rsync
        rsync_dst = f"{remote}:/tmp/replicant-build/"
        r = self._run_rsync(f"{build_dir}/", rsync_dst)
        if r.returncode != 0:
            if verbose:
                print(r.stderr)
            return False

        # 2. docker build
        r = self._run_ssh(f"docker build -t {tag} /tmp/replicant-build/")
        if r.returncode != 0:
            if verbose:
                print(r.stderr)
            return False

        # 3. docker save + gzip
        r = self._run_ssh(f"docker save {tag} | gzip > /tmp/{tag}.tar.gz")
        if r.returncode != 0:
            if verbose:
                print(r.stderr)
            return False

        # 4. upload to S3
        r = self._run_ssh(f"aws s3 cp /tmp/{tag}.tar.gz s3://{bucket}/{tag}.tar.gz")
        if r.returncode != 0:
            if verbose:
                print(r.stderr)
            return False

        return True

    def shell(self, meta: EnvMeta, gpu: bool = False) -> None:
        """
        Sync repo code to instance, load image from S3 if not present,
        then launch an interactive shell with the code mounted at /workspace.
        """
        tag = meta.docker_image
        bucket = self.resources.s3_bucket
        remote = self._remote()

        # Sync the local repo clone to ~/code on the instance (ubuntu-owned path).
        if meta.code_path:
            print("  Syncing code to instance…")
            self._run_rsync(f"{meta.code_path}/", f"{remote}:/home/ubuntu/code/")

        # Load image from S3 if not already present on the remote.
        load_cmd = (
            f"docker image inspect {tag} > /dev/null 2>&1 || "
            f"aws s3 cp s3://{bucket}/{tag}.tar.gz - | docker load"
        )
        self._run_ssh(load_cmd, capture=False)

        gpu_flag = "--gpus all" if gpu else ""
        run_cmd = (
            f"docker run -it --rm {gpu_flag} "
            f"-v /home/ubuntu/code:/workspace -w /workspace {tag} /bin/bash"
        ).strip()

        cmd = ["ssh", "-t", *self._ssh_opts(), remote, run_cmd]
        subprocess.run(cmd)

    def remove_image(self, tag: str) -> None:
        """Remove Docker image on remote (ignore errors) and delete from S3."""
        bucket = self.resources.s3_bucket

        # Remove on remote — ignore errors
        self._run_ssh(f"docker rmi {tag} || true")

        # Remove from S3
        self._run_ssh(f"aws s3 rm s3://{bucket}/{tag}.tar.gz")
