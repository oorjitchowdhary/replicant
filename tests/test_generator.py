"""Test Dockerfile generation."""
import pytest
import tempfile
from pathlib import Path
from replicant.analyzers.repo import EnvironmentSpec
from replicant.generators.docker import generate

def test_generate_requires_primary_env():
    """Test that generate raises error without env file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        spec = EnvironmentSpec(repo_path=Path(tmpdir))
        with pytest.raises(RuntimeError, match="No environment file"):
            generate(spec, "test123")

def test_generate_pip():
    """Test Dockerfile generation for requirements.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        req = repo / "requirements.txt"
        req.write_text("torch>=2.0")
        
        spec = EnvironmentSpec(
            repo_path=repo,
            primary_env="requirements.txt",
            primary_env_path=req,
            python_version="3.10",
        )
        spec.env_files["requirements.txt"] = req
        
        with tempfile.TemporaryDirectory() as builddir:
            from replicant.utils.config import BUILD
            import shutil
            test_build = BUILD / "test_pip"
            if test_build.exists():
                shutil.rmtree(test_build)
            
            result = generate(spec, "test_pip")
            assert (result / "Dockerfile").exists()
            dockerfile = (result / "Dockerfile").read_text()
            assert "python:3.10" in dockerfile
            assert "requirements.txt" in dockerfile
            
            # cleanup
            shutil.rmtree(test_build, ignore_errors=True)

def test_generate_conda():
    """Test Dockerfile generation for environment.yml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        env = repo / "environment.yml"
        env.write_text("name: test\ndependencies:\n  - pytorch")
        
        spec = EnvironmentSpec(
            repo_path=repo,
            primary_env="environment.yml",
            primary_env_path=env,
        )
        spec.env_files["environment.yml"] = env
        
        with tempfile.TemporaryDirectory() as builddir:
            from replicant.utils.config import BUILD
            import shutil
            test_build = BUILD / "test_conda"
            if test_build.exists():
                shutil.rmtree(test_build)
            
            result = generate(spec, "test_conda")
            assert (result / "Dockerfile").exists()
            dockerfile = (result / "Dockerfile").read_text()
            assert "miniconda" in dockerfile
            assert "environment.yml" in dockerfile
            
            # cleanup
            shutil.rmtree(test_build, ignore_errors=True)
