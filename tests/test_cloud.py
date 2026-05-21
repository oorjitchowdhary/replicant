"""Tests for cloud executor, AWS provider, and EnvMeta cloud fields (1D)."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from replicant.providers.base import CloudResources
from replicant.executors.cloud import CloudExecutor
from replicant.providers.aws import AWSProvider, _find_terraform, _find_sso_profile, _ensure_aws_credentials
from replicant.utils.config import EnvMeta


# ── fixtures ──────────────────────────────────────────────────────────────────

def _resources(**overrides) -> CloudResources:
    defaults = dict(
        instance_ip="1.2.3.4",
        ssh_key_path=Path("/tmp/key.pem"),
        s3_bucket="replicant-bucket",
        instance_id="i-abc123",
        region="us-west-2",
    )
    defaults.update(overrides)
    return CloudResources(**defaults)


def _ok(returncode=0, stdout="", stderr="") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _fail(stderr="oops") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


# ── CloudResources ────────────────────────────────────────────────────────────

def test_cloud_resources_fields():
    r = _resources()
    assert r.instance_ip == "1.2.3.4"
    assert r.ssh_key_path == Path("/tmp/key.pem")
    assert r.s3_bucket == "replicant-bucket"
    assert r.instance_id == "i-abc123"
    assert r.region == "us-west-2"


# ── CloudExecutor._ssh_opts / _remote ─────────────────────────────────────────

def test_ssh_opts_contain_key_and_no_host_check():
    ex = CloudExecutor(_resources(ssh_key_path=Path("/tmp/mykey.pem")))
    opts = ex._ssh_opts()
    assert "-i" in opts
    assert "/tmp/mykey.pem" in opts
    assert "StrictHostKeyChecking=no" in " ".join(opts)
    assert "BatchMode=yes" in " ".join(opts)


def test_remote_uses_ubuntu_and_ip():
    ex = CloudExecutor(_resources(instance_ip="5.6.7.8"))
    assert ex._remote() == "ubuntu@5.6.7.8"


# ── CloudExecutor.build ───────────────────────────────────────────────────────

def test_build_succeeds_when_all_steps_pass():
    ex = CloudExecutor(_resources())
    with patch.object(ex, "_run_rsync", return_value=_ok()) as mock_rsync, \
         patch.object(ex, "_run_ssh", return_value=_ok()) as mock_ssh:
        assert ex.build(Path("/tmp/build"), "my-tag") is True
    mock_rsync.assert_called_once()
    assert mock_ssh.call_count == 3  # docker build, docker save, aws s3 cp


def test_build_fails_on_rsync_error():
    ex = CloudExecutor(_resources())
    with patch.object(ex, "_run_rsync", return_value=_fail()), \
         patch.object(ex, "_run_ssh") as mock_ssh:
        assert ex.build(Path("/tmp/build"), "my-tag") is False
    mock_ssh.assert_not_called()


def test_build_fails_on_docker_build_error():
    ex = CloudExecutor(_resources())
    with patch.object(ex, "_run_rsync", return_value=_ok()), \
         patch.object(ex, "_run_ssh", side_effect=[_fail(), _ok(), _ok()]):
        assert ex.build(Path("/tmp/build"), "my-tag") is False


def test_build_fails_on_docker_save_error():
    ex = CloudExecutor(_resources())
    with patch.object(ex, "_run_rsync", return_value=_ok()), \
         patch.object(ex, "_run_ssh", side_effect=[_ok(), _fail(), _ok()]):
        assert ex.build(Path("/tmp/build"), "my-tag") is False


def test_build_fails_on_s3_upload_error():
    ex = CloudExecutor(_resources())
    with patch.object(ex, "_run_rsync", return_value=_ok()), \
         patch.object(ex, "_run_ssh", side_effect=[_ok(), _ok(), _fail()]):
        assert ex.build(Path("/tmp/build"), "my-tag") is False


def test_build_rsync_dst_uses_instance_ip():
    ex = CloudExecutor(_resources(instance_ip="9.9.9.9"))
    captured = {}

    def fake_rsync(src, dst):
        captured["dst"] = dst
        return _ok()

    with patch.object(ex, "_run_rsync", side_effect=fake_rsync), \
         patch.object(ex, "_run_ssh", return_value=_ok()):
        ex.build(Path("/tmp/build"), "my-tag")

    assert "9.9.9.9" in captured["dst"]


def test_build_ssh_commands_use_tag_and_bucket():
    ex = CloudExecutor(_resources(s3_bucket="my-bucket"))
    captured_cmds = []

    def fake_ssh(command, **kwargs):
        captured_cmds.append(command)
        return _ok()

    with patch.object(ex, "_run_rsync", return_value=_ok()), \
         patch.object(ex, "_run_ssh", side_effect=fake_ssh):
        ex.build(Path("/tmp/build"), "img-tag")

    assert any("img-tag" in c for c in captured_cmds)
    assert any("my-bucket" in c for c in captured_cmds)


# ── CloudExecutor.remove_image ────────────────────────────────────────────────

def test_remove_image_issues_two_ssh_commands():
    ex = CloudExecutor(_resources())
    cmds = []
    with patch.object(ex, "_run_ssh", side_effect=lambda c, **kw: cmds.append(c) or _ok()):
        ex.remove_image("old-tag")
    assert len(cmds) == 2
    assert any("docker rmi" in c for c in cmds)
    assert any("s3 rm" in c for c in cmds)


def test_remove_image_uses_bucket_and_tag():
    ex = CloudExecutor(_resources(s3_bucket="test-bucket"))
    cmds = []
    with patch.object(ex, "_run_ssh", side_effect=lambda c, **kw: cmds.append(c) or _ok()):
        ex.remove_image("test-tag")
    assert any("test-bucket" in c and "test-tag" in c for c in cmds)


# ── EnvMeta cloud fields ──────────────────────────────────────────────────────

def test_envmeta_cloud_fields_default_none():
    m = EnvMeta(env_id="x", source="s", github_url="g")
    assert m.cloud_provider is None
    assert m.cloud_instance_id is None
    assert m.cloud_region is None
    assert m.cloud_bucket is None


def test_envmeta_cloud_fields_set():
    m = EnvMeta(
        env_id="x", source="s", github_url="g",
        cloud_provider="aws", cloud_instance_id="i-abc",
        cloud_region="us-east-1", cloud_bucket="my-bucket",
    )
    assert m.cloud_provider == "aws"
    assert m.cloud_instance_id == "i-abc"
    assert m.cloud_region == "us-east-1"
    assert m.cloud_bucket == "my-bucket"


def test_envmeta_cloud_fields_serialize():
    import json as _json
    from dataclasses import asdict
    m = EnvMeta(
        env_id="x", source="s", github_url="g",
        cloud_provider="aws", cloud_instance_id="i-xyz",
        cloud_region="us-west-2", cloud_bucket="bucket",
    )
    data = asdict(m)
    assert data["cloud_provider"] == "aws"
    assert data["cloud_instance_id"] == "i-xyz"
    assert data["cloud_region"] == "us-west-2"
    assert data["cloud_bucket"] == "bucket"


def test_envmeta_cloud_fields_roundtrip_json(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLICANT_HOME", str(tmp_path))
    import importlib
    import replicant.utils.config as cfg_mod
    importlib.reload(cfg_mod)
    from replicant.utils.config import EnvMeta as _EnvMeta

    m = _EnvMeta(
        env_id="abc", source="src", github_url="https://github.com/x/y",
        cloud_provider="aws", cloud_instance_id="i-1", cloud_region="eu-west-1", cloud_bucket="b",
    )
    m.save()
    loaded = _EnvMeta.load("abc")
    assert loaded.cloud_provider == "aws"
    assert loaded.cloud_instance_id == "i-1"
    assert loaded.cloud_region == "eu-west-1"
    assert loaded.cloud_bucket == "b"


# ── AWSProvider._tf ───────────────────────────────────────────────────────────

def test_aws_provider_tf_calls_terraform_with_chdir():
    provider = AWSProvider()
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="{}", stderr="")

    with patch("replicant.providers.aws._find_terraform", return_value="terraform"), \
         patch("subprocess.run", side_effect=fake_run):
        provider._tf("version")

    assert "terraform" in captured["cmd"]
    assert any(arg.startswith("-chdir=") for arg in captured["cmd"])
    assert "version" in captured["cmd"]


def test_aws_provider_tf_raises_on_failure():
    provider = AWSProvider()

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="bad error")

    with patch("replicant.providers.aws._find_terraform", return_value="terraform"), \
         patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError, match="Terraform command failed"):
            provider._tf("apply")


def test_aws_provider_tf_no_raise_when_check_false():
    provider = AWSProvider()

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="ignored")

    with patch("replicant.providers.aws._find_terraform", return_value="terraform"), \
         patch("subprocess.run", side_effect=fake_run):
        result = provider._tf("plan", check=False)
    assert result.returncode == 1


# ── AWSProvider.provision ─────────────────────────────────────────────────────

def _fake_tf_outputs() -> str:
    return json.dumps({
        "instance_public_ip": {"value": "10.0.0.1"},
        "s3_bucket_name": {"value": "replicant-test-bucket"},
        "instance_id": {"value": "i-deadbeef"},
        "key_path": {"value": "/tmp/key.pem"},
    })


_no_creds = patch("replicant.providers.aws._ensure_aws_credentials")
_no_wait  = patch("replicant.providers.aws._wait_for_instance_ready")


def test_provision_returns_cloud_resources():
    provider = AWSProvider()

    def fake_tf(*args, **kwargs):
        if "output" in args:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=_fake_tf_outputs(), stderr="")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with _no_creds, _no_wait, patch.object(provider, "_tf", side_effect=fake_tf):
        resources = provider.provision(MagicMock(), "env-abc")

    assert resources.instance_ip == "10.0.0.1"
    assert resources.s3_bucket == "replicant-test-bucket"
    assert resources.instance_id == "i-deadbeef"
    assert resources.ssh_key_path == Path("/tmp/key.pem")
    assert resources.region == provider.region


def test_provision_calls_init_then_apply():
    provider = AWSProvider()
    calls = []

    def fake_tf(*args, **kwargs):
        calls.append(args)
        if "output" in args:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=_fake_tf_outputs(), stderr="")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with _no_creds, _no_wait, patch.object(provider, "_tf", side_effect=fake_tf):
        provider.provision(MagicMock(), "env-xyz")

    assert calls[0][0] == "init"
    assert calls[1][0] == "apply"


def test_provision_passes_env_id_as_project_tag():
    provider = AWSProvider()
    apply_args = []

    def fake_tf(*args, **kwargs):
        if args[0] == "apply":
            apply_args.extend(args)
        if "output" in args:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=_fake_tf_outputs(), stderr="")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with _no_creds, _no_wait, patch.object(provider, "_tf", side_effect=fake_tf):
        provider.provision(MagicMock(), "my-env-id")

    assert any("my-env-id" in a for a in apply_args)


def test_provision_waits_for_instance_ready():
    provider = AWSProvider()

    def fake_tf(*args, **kwargs):
        if "output" in args:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=_fake_tf_outputs(), stderr="")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with _no_creds, \
         patch.object(provider, "_tf", side_effect=fake_tf), \
         patch("replicant.providers.aws._wait_for_instance_ready") as mock_wait:
        provider.provision(MagicMock(), "env-wait")

    mock_wait.assert_called_once()


# ── AWSProvider.teardown ──────────────────────────────────────────────────────

def test_teardown_calls_destroy_with_env_id():
    provider = AWSProvider()
    destroy_args = []

    def fake_tf(*args, **kwargs):
        if args[0] == "destroy":
            destroy_args.extend(args)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with _no_creds, patch.object(provider, "_tf", side_effect=fake_tf):
        provider.teardown("env-to-kill")

    assert "destroy" in destroy_args
    assert any("env-to-kill" in a for a in destroy_args)


# ── _find_terraform ───────────────────────────────────────────────────────────

def test_find_terraform_returns_path_when_present():
    with patch("shutil.which", return_value="/usr/local/bin/terraform"):
        assert _find_terraform() == "/usr/local/bin/terraform"


def test_find_terraform_raises_when_missing():
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="terraform binary not found"):
            _find_terraform()


# ── AWSProvider.region default ────────────────────────────────────────────────

def test_aws_provider_default_region(monkeypatch):
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    provider = AWSProvider()
    assert provider.region == "us-west-2"


def test_aws_provider_region_from_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    provider = AWSProvider()
    assert provider.region == "eu-central-1"


# ── _find_sso_profile ─────────────────────────────────────────────────────────

def test_find_sso_profile_returns_none_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert _find_sso_profile() is None


def test_find_sso_profile_returns_none_when_no_sso_section(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text("[profile myprofile]\nregion = us-west-2\n")
    assert _find_sso_profile() is None


def test_find_sso_profile_finds_sso_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text(
        "[profile myprofile]\n"
        "sso_start_url = https://my-org.awsapps.com/start\n"
        "sso_account_id = 123456789\n"
        "region = us-west-2\n"
    )
    assert _find_sso_profile() == "myprofile"


def test_find_sso_profile_prefers_first_sso_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text(
        "[profile plain]\nregion = us-east-1\n\n"
        "[profile sso-first]\nsso_start_url = https://a.awsapps.com/start\n\n"
        "[profile sso-second]\nsso_start_url = https://b.awsapps.com/start\n"
    )
    assert _find_sso_profile() == "sso-first"


# ── _ensure_aws_credentials ───────────────────────────────────────────────────

def test_ensure_credentials_passes_when_sts_succeeds():
    """If STS call succeeds, no SSO flow is triggered."""
    mock_session = MagicMock()
    mock_session.return_value.client.return_value.get_caller_identity.return_value = {}
    with patch("boto3.Session", mock_session):
        _ensure_aws_credentials("us-west-2")  # should not raise


def test_ensure_credentials_prompts_iam_when_no_creds_and_no_profile():
    """NoCredentialsError + no SSO profile → falls through to IAM key prompt."""
    import botocore.exceptions

    mock_session = MagicMock()
    mock_session.return_value.client.return_value.get_caller_identity.side_effect = \
        botocore.exceptions.NoCredentialsError()

    with patch("boto3.Session", mock_session), \
         patch("replicant.providers.aws._find_sso_profile", return_value=None), \
         patch("replicant.providers.aws._prompt_iam_credentials") as mock_prompt:
        _ensure_aws_credentials("us-west-2")

    mock_prompt.assert_called_once_with("us-west-2")


def test_ensure_credentials_triggers_sso_login_when_profile_found():
    """NoCredentialsError + SSO profile present → `aws sso login` is called."""
    import botocore.exceptions
    from unittest.mock import patch as _patch

    login_calls = []

    def fake_subprocess_run(cmd, **kwargs):
        login_calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_session = MagicMock()
    mock_session.return_value.client.return_value.get_caller_identity.side_effect = [
        botocore.exceptions.NoCredentialsError(),
        {},
    ]
    mock_session.return_value.region_name = "us-west-2"

    # patch.dict contains any os.environ mutations made by the code under test.
    with _patch.dict("os.environ", {}, clear=False), \
         patch("boto3.Session", mock_session), \
         patch("replicant.providers.aws._find_sso_profile", return_value="my-sso-profile"), \
         patch("subprocess.run", side_effect=fake_subprocess_run):
        _ensure_aws_credentials("us-west-2")

    assert any("sso" in " ".join(c) and "login" in " ".join(c) for c in login_calls)
    assert any("my-sso-profile" in " ".join(c) for c in login_calls)


def test_ensure_credentials_raises_when_sso_login_fails(monkeypatch):
    """If `aws sso login` exits nonzero, raise RuntimeError."""
    import botocore.exceptions

    mock_session = MagicMock()
    mock_session.return_value.client.return_value.get_caller_identity.side_effect = \
        botocore.exceptions.NoCredentialsError()

    with patch("boto3.Session", mock_session), \
         patch("replicant.providers.aws._find_sso_profile", return_value="my-profile"), \
         patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=1)), \
         pytest.raises(RuntimeError, match="SSO login failed"):
        _ensure_aws_credentials("us-west-2")
