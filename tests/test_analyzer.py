"""Test repo analyzer."""
import pytest
import tempfile
from pathlib import Path
from replicant.analyzers.repo import analyze, EnvironmentSpec, _extract_packages, _infer_python

def test_environment_spec_defaults():
    """Test EnvironmentSpec default values."""
    spec = EnvironmentSpec(repo_path=Path("."))
    assert spec.python_version == "3.10"
    assert spec.packages == []
    assert spec.datasets == []
    assert not spec.needs_gpu

def test_extract_packages_requirements():
    """Test package extraction from requirements.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        req = repo / "requirements.txt"
        req.write_text("torch>=2.0\nnumpy==1.24.0\n# comment\npandas")
        
        spec = EnvironmentSpec(repo_path=repo)
        pkgs = _extract_packages(repo, spec)
        assert "torch" in pkgs
        assert "numpy" in pkgs
        assert "pandas" in pkgs

def test_extract_packages_environment_yml():
    """Test package extraction from environment.yml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        env = repo / "environment.yml"
        env.write_text("""
name: test
dependencies:
  - python=3.9
  - pytorch
  - numpy>=1.20
""")
        spec = EnvironmentSpec(repo_path=repo)
        pkgs = _extract_packages(repo, spec)
        assert "pytorch" in pkgs
        assert "numpy" in pkgs

def test_infer_python_from_file():
    """Test Python version inference from .python-version."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / ".python-version").write_text("3.11")
        spec = EnvironmentSpec(repo_path=repo)
        version = _infer_python(repo, spec, "")
        assert version == "3.11"

def test_analyze_finds_env_files():
    """Test that analyze finds environment files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "requirements.txt").write_text("torch\n")
        (repo / "setup.py").write_text("from setuptools import setup\nsetup(name='test')")
        
        spec = analyze(repo)
        assert "requirements.txt" in spec.env_files
        assert "setup.py" in spec.env_files
        assert spec.primary_env == "requirements.txt"  # higher priority

def test_analyze_detects_gpu():
    """Test GPU detection from code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "train.py").write_text("import torch\ndevice = torch.device('cuda')")
        (repo / "requirements.txt").write_text("torch")
        
        spec = analyze(repo)
        assert spec.needs_gpu

def test_analyze_finds_entrypoints():
    """Test entrypoint detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "train.py").write_text("# training script")
        (repo / "main.py").write_text("# main script")
        (repo / "utils.py").write_text("# utils")
        (repo / "requirements.txt").write_text("torch")
        
        spec = analyze(repo)
        assert "train.py" in spec.entrypoints
        assert "main.py" in spec.entrypoints
        assert "utils.py" not in spec.entrypoints
