from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from replicant.utils.onboarding import load_config, save_config

def test_load_config_returns_empty_dict_when_missing(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        assert load_config() == {}

def test_load_config_returns_dict_when_present(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"aws_region": "us-east-1", "bedrock_model_id": "my-model"}))
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        cfg = load_config()
    assert cfg["aws_region"] == "us-east-1"
    assert cfg["bedrock_model_id"] == "my-model"

def test_save_config_writes_json(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        save_config({"aws_region": "eu-west-1", "bedrock_model_id": "m"})
    data = json.loads(cfg_path.read_text())
    assert data["aws_region"] == "eu-west-1"

def test_save_config_creates_parent_dir(tmp_path):
    cfg_path = tmp_path / "nested" / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        save_config({"bedrock_model_id": "x", "aws_region": "us-east-1"})
    assert cfg_path.exists()


# New tests for llm_config
from unittest.mock import MagicMock, patch
from replicant.utils.llm_config import test_bedrock_connection, get_bedrock_client

def test_bedrock_connection_returns_true_on_success():
    mock_client = MagicMock()
    mock_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "hi"}]}}
    }
    with patch("replicant.utils.llm_config.get_bedrock_client", return_value=mock_client):
        ok, msg = test_bedrock_connection("us.anthropic.claude-sonnet-4-6", "us-east-1", None)
    assert ok is True
    assert "success" in msg.lower()

def test_bedrock_connection_returns_false_on_exception():
    mock_client = MagicMock()
    mock_client.converse.side_effect = Exception("no access")
    with patch("replicant.utils.llm_config.get_bedrock_client", return_value=mock_client):
        ok, msg = test_bedrock_connection("my-model", "us-east-1", None)
    assert ok is False
    assert "no access" in msg

def test_get_bedrock_client_uses_config_region(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"aws_region": "ap-southeast-1", "bedrock_model_id": "m"}))
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path), \
         patch("boto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.client.return_value = MagicMock()
        get_bedrock_client()
    mock_session.client.assert_called_once()
    call_kwargs = mock_session.client.call_args[1]
    assert call_kwargs["region_name"] == "ap-southeast-1"


# New tests for terraform auto-install
import shutil
from replicant.utils.onboarding import _install_terraform, _step_terraform

def test_step_terraform_skips_when_already_installed():
    with patch("shutil.which", return_value="/usr/local/bin/terraform"):
        result = _step_terraform()
    assert result is True

def test_install_terraform_tries_brew_on_macos():
    def which_side_effect(x):
        if x == "brew":
            return "/usr/bin/brew"
        if x == "terraform":
            return "/usr/local/bin/terraform"
        return None
    with patch("platform.system", return_value="Darwin"), \
         patch("shutil.which", side_effect=which_side_effect), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ok = _install_terraform()
    assert ok is True
    cmds = [" ".join(c.args[0]) if isinstance(c.args[0], list) else " ".join(c.args) for c in mock_run.call_args_list]
    assert any("brew" in c for c in cmds)

def test_install_terraform_returns_false_when_all_fail():
    with patch("platform.system", return_value="Darwin"), \
         patch("shutil.which", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        ok = _install_terraform()
    assert ok is False
