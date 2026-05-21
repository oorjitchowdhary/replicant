"""AWS cloud provider using Terraform."""
from __future__ import annotations
import configparser
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

    def _tf(self, *args: str, check: bool = True, stream: bool = False) -> subprocess.CompletedProcess:
        """Run a terraform command inside terraform_dir."""
        terraform = _find_terraform()
        cmd = [terraform, f"-chdir={self.terraform_dir}", *args]
        if stream:
            result = subprocess.run(cmd, text=True)
            result.stdout = ""
            result.stderr = ""
        else:
            result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(
                f"Terraform command failed: {' '.join(args)}\n"
                f"stdout: {getattr(result, 'stdout', '')}\n"
                f"stderr: {getattr(result, 'stderr', '')}"
            )
        return result

    # ── public API ───────────────────────────────────────────────────────────

    def provision(self, spec: "EnvironmentSpec", env_id: str) -> CloudResources:
        """Initialize and apply Terraform config, returning the provisioned resources."""
        _ensure_aws_credentials(self.region)
        # Update region in case SSO profile changed it
        self.region = os.environ.get("AWS_DEFAULT_REGION", self.region)

        self._tf("init", "-input=false", stream=True)
        self._tf(
            "apply",
            "-auto-approve",
            "-input=false",
            f"-var=project_tag={env_id}",
            stream=True,
        )

        # Parse outputs
        out_result = self._tf("output", "-json")
        outputs = json.loads(out_result.stdout)

        instance_ip = outputs["instance_public_ip"]["value"]
        s3_bucket = outputs["s3_bucket_name"]["value"]
        instance_id = outputs["instance_id"]["value"]
        key_path = Path(outputs["key_path"]["value"]).expanduser()

        resources = CloudResources(
            instance_ip=instance_ip,
            ssh_key_path=key_path,
            s3_bucket=s3_bucket,
            instance_id=instance_id,
            region=self.region,
        )

        _wait_for_instance_ready(resources)
        return resources

    def teardown(self, env_id: str) -> None:
        """Destroy all Terraform-managed resources for the given env_id."""
        _ensure_aws_credentials(self.region)
        self._tf(
            "destroy",
            "-auto-approve",
            "-input=false",
            f"-var=project_tag={env_id}",
            stream=True,
        )


# ── credential helpers ───────────────────────────────────────────────────────

def _ensure_aws_credentials(region: str) -> None:
    """
    Verify AWS credentials are valid. If not:
      1. Try SSO login if a profile is configured.
      2. Otherwise prompt for IAM access keys, save to ~/.aws/credentials, and continue.
    Sets AWS_DEFAULT_REGION in os.environ so terraform subprocess calls inherit it.
    """
    import boto3
    import botocore.exceptions

    # 1. Check if current credentials already work.
    try:
        boto3.Session().client("sts", region_name=region).get_caller_identity()
        return
    except botocore.exceptions.NoCredentialsError:
        pass
    except botocore.exceptions.ClientError as e:
        if "sso" not in str(e).lower() and "token" not in str(e).lower():
            raise

    # 2. Try SSO if a profile is configured.
    profile = os.environ.get("AWS_PROFILE") or _find_sso_profile()
    if profile:
        print(f"\n  Opening browser for AWS SSO login (profile: {profile})…")
        result = subprocess.run(["aws", "sso", "login", "--profile", profile])
        if result.returncode != 0:
            raise RuntimeError(f"AWS SSO login failed for profile '{profile}'.")
        os.environ["AWS_PROFILE"] = profile
        session = boto3.Session(profile_name=profile)
        profile_region = session.region_name
        if profile_region:
            os.environ["AWS_DEFAULT_REGION"] = profile_region
        try:
            session.client("sts", region_name=profile_region or region).get_caller_identity()
            return
        except Exception as e:
            raise RuntimeError(f"AWS credentials still invalid after SSO login: {e}") from e

    # 3. No credentials at all — prompt for IAM access keys interactively.
    _prompt_iam_credentials(region)


def _find_sso_profile() -> str | None:
    """Return the first SSO-configured profile name from ~/.aws/config."""
    config_path = Path.home() / ".aws" / "config"
    if not config_path.exists():
        return None
    config = configparser.ConfigParser()
    config.read(config_path)
    for section in config.sections():
        if "sso_start_url" in config[section]:
            # Section names are "profile <name>" for named profiles, "default" for default.
            return section.replace("profile ", "").strip()
    return None


def _prompt_iam_credentials(region: str) -> None:
    """
    Interactively collect IAM access keys, verify them, and persist to
    ~/.aws/credentials so all future calls (and terraform) work without
    re-prompting.
    """
    import webbrowser
    import boto3
    import botocore.exceptions
    import click

    console_url = "https://console.aws.amazon.com/iam/home#/security_credentials"

    print("\n  No AWS credentials found.")
    print(f"  Opening the AWS console to create an access key…")
    print(f"  → {console_url}")
    print()
    print("  Steps:")
    print("    1. Sign in if prompted")
    print("    2. Scroll to 'Access keys' → 'Create access key'")
    print("    3. Copy the Access Key ID and Secret Access Key")
    print()

    webbrowser.open(console_url)

    key_id = click.prompt("  AWS Access Key ID", hide_input=False).strip()
    secret = click.prompt("  AWS Secret Access Key", hide_input=True).strip()

    # Verify before saving.
    try:
        boto3.Session(
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name=region,
        ).client("sts").get_caller_identity()
    except botocore.exceptions.ClientError as e:
        raise RuntimeError(f"Credential verification failed: {e}") from e

    # Persist to ~/.aws/credentials under [default].
    creds_path = Path.home() / ".aws" / "credentials"
    creds_path.parent.mkdir(exist_ok=True)

    cfg = configparser.ConfigParser()
    if creds_path.exists():
        cfg.read(creds_path)
    if "default" not in cfg:
        cfg["default"] = {}
    cfg["default"]["aws_access_key_id"] = key_id
    cfg["default"]["aws_secret_access_key"] = secret

    with creds_path.open("w") as f:
        cfg.write(f)
    creds_path.chmod(0o600)

    # Also write region to ~/.aws/config.
    config_path = Path.home() / ".aws" / "config"
    ccfg = configparser.ConfigParser()
    if config_path.exists():
        ccfg.read(config_path)
    if "default" not in ccfg:
        ccfg["default"] = {}
    ccfg["default"]["region"] = region
    ccfg["default"]["output"] = "json"
    with config_path.open("w") as f:
        ccfg.write(f)

    os.environ["AWS_ACCESS_KEY_ID"] = key_id
    os.environ["AWS_SECRET_ACCESS_KEY"] = secret
    os.environ["AWS_DEFAULT_REGION"] = region

    print(f"\n  Credentials saved to {creds_path}. You won't be prompted again.")


def _wait_for_instance_ready(resources: "CloudResources", timeout: int = 300) -> None:
    """
    Block until the EC2 instance is reachable over SSH and Docker is running.
    Polls every 10 seconds, raises RuntimeError after `timeout` seconds.
    """
    import time

    ssh_opts = [
        "-i", str(resources.ssh_key_path),
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
    ]
    remote = f"ubuntu@{resources.instance_ip}"
    deadline = time.time() + timeout
    attempt = 0

    print(f"\n  Waiting for instance {resources.instance_ip} to be ready", end="", flush=True)

    while time.time() < deadline:
        attempt += 1
        result = subprocess.run(
            ["ssh", *ssh_opts, remote, "docker info > /dev/null 2>&1"],
            capture_output=True,
        )
        if result.returncode == 0:
            print(f" ready ({attempt * 10}s)", flush=True)
            return
        print(".", end="", flush=True)
        time.sleep(10)

    print()
    raise RuntimeError(
        f"Instance {resources.instance_ip} did not become ready within {timeout}s."
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
