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
