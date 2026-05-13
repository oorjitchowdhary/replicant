"""AWS cloud provider using Terraform."""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from replicant.providers.base import CloudResources

if TYPE_CHECKING:
    from replicant.analyzers.repo import EnvironmentSpec

# Repo root is three levels up from this file: replicant/providers/aws.py
_REPO_ROOT = Path(__file__).parent.parent.parent


class AWSProvider:
    """Provisions and tears down AWS infrastructure via Terraform."""

    def __init__(self) -> None:
        self.terraform_dir: Path = _REPO_ROOT / "terraform" / "aws"
        self.region: str = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")

    # ── helpers ─────────────────────────────────────────────────────────────

    def _tf(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a terraform command inside terraform_dir."""
        terraform = _find_terraform()
        cmd = [terraform, f"-chdir={self.terraform_dir}", *args]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(
                f"Terraform command failed: {' '.join(args)}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        return result

    # ── public API ───────────────────────────────────────────────────────────

    def provision(self, spec: "EnvironmentSpec", env_id: str) -> CloudResources:
        """Initialize and apply Terraform config, returning the provisioned resources."""
        self._tf("init", "-input=false")
        self._tf(
            "apply",
            "-auto-approve",
            "-input=false",
            f"-var=project_tag={env_id}",
        )

        # Parse outputs
        out_result = self._tf("output", "-json")
        outputs = json.loads(out_result.stdout)

        instance_ip = outputs["instance_public_ip"]["value"]
        s3_bucket = outputs["s3_bucket_name"]["value"]
        instance_id = outputs["instance_id"]["value"]
        key_path = Path(outputs["key_path"]["value"]).expanduser()

        return CloudResources(
            instance_ip=instance_ip,
            ssh_key_path=key_path,
            s3_bucket=s3_bucket,
            instance_id=instance_id,
            region=self.region,
        )

    def teardown(self, env_id: str) -> None:
        """Destroy all Terraform-managed resources for the given env_id."""
        self._tf(
            "destroy",
            "-auto-approve",
            "-input=false",
            f"-var=project_tag={env_id}",
        )


def _find_terraform() -> str:
    """Return the path to the terraform binary, raising if not found."""
    import shutil
    tf = shutil.which("terraform")
    if tf is None:
        raise RuntimeError(
            "terraform binary not found in PATH. "
            "Install Terraform: https://developer.hashicorp.com/terraform/install"
        )
    return tf
