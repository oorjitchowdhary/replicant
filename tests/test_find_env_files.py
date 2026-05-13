"""Tests for _find_env_files — depth, priority, and monorepo heuristics (1A)."""
import tempfile
from pathlib import Path

import pytest

from replicant.analyzers.repo import _find_env_files


# ── helpers ──────────────────────────────────────────────────────────────────

def make_repo(structure: dict[str, str]) -> Path:
    """Create a temp repo with the given path→content mapping. Returns repo Path."""
    tmp = tempfile.mkdtemp()
    repo = Path(tmp)
    for rel, content in structure.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return repo


# ── priority (root-level files) ───────────────────────────────────────────────

def test_dockerfile_beats_requirements():
    repo = make_repo({
        "Dockerfile": "FROM python:3.10\n",
        "requirements.txt": "numpy\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "Dockerfile"


def test_environment_yml_beats_requirements():
    repo = make_repo({
        "environment.yml": "name: env\ndependencies:\n  - numpy\n",
        "requirements.txt": "numpy\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "environment.yml"


def test_requirements_beats_setup_py():
    repo = make_repo({
        "requirements.txt": "numpy\n",
        "setup.py": "from setuptools import setup\nsetup(name='x')\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "requirements.txt"


def test_setup_py_beats_pyproject():
    repo = make_repo({
        "setup.py": "from setuptools import setup\nsetup(name='x')\n",
        "pyproject.toml": "[project]\nname = 'x'\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "setup.py"


def test_environment_yaml_variant():
    repo = make_repo({"environment.yaml": "name: env\n"})
    _, primary, _ = _find_env_files(repo)
    assert primary == "environment.yaml"


def test_conda_yml_variant():
    repo = make_repo({"conda_environment.yml": "name: env\n"})
    _, primary, _ = _find_env_files(repo)
    assert primary == "conda_environment.yml"


def test_requirements_variants_found():
    repo = make_repo({
        "requirements-dev.txt": "pytest\n",
        "requirements_base.txt": "numpy\ntorch\n",
    })
    found, _, _ = _find_env_files(repo)
    assert "requirements-dev.txt" in found
    assert "requirements_base.txt" in found


def test_largest_requirements_variant_wins():
    repo = make_repo({
        "requirements-dev.txt": "pytest\n",
        "requirements-base.txt": "numpy\ntorch\npandas\nmatplotlib\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "requirements-base.txt"


def test_pipfile():
    repo = make_repo({"Pipfile": "[packages]\nnumpy = '*'\n"})
    _, primary, _ = _find_env_files(repo)
    assert primary == "Pipfile"


def test_no_env_files_returns_none():
    repo = make_repo({"train.py": "import numpy\n"})
    found, primary, primary_path = _find_env_files(repo)
    assert primary is None
    assert primary_path is None


# ── depth-2 detection ─────────────────────────────────────────────────────────

def test_depth2_requirements_found():
    repo = make_repo({"src/requirements.txt": "torch\n"})
    found, primary, _ = _find_env_files(repo)
    assert "src/requirements.txt" in found


def test_depth2_requirements_becomes_primary_when_only_option():
    repo = make_repo({
        "src/requirements.txt": "torch\n",
        "src/model.py": "import torch\n",
        "src/train.py": "import torch\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "src/requirements.txt"


def test_depth2_environment_yml_found():
    repo = make_repo({"project/environment.yml": "name: env\ndependencies:\n  - numpy\n"})
    found, _, _ = _find_env_files(repo)
    assert "project/environment.yml" in found


def test_depth2_setup_py_found():
    repo = make_repo({"mypackage/setup.py": "from setuptools import setup\nsetup(name='x')\n"})
    found, _, _ = _find_env_files(repo)
    assert "mypackage/setup.py" in found


def test_root_beats_depth2():
    """Root-level requirements.txt should win over a nested one."""
    repo = make_repo({
        "requirements.txt": "numpy\n",
        "src/requirements.txt": "torch\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "requirements.txt"


# ── depth-3 detection ─────────────────────────────────────────────────────────

def test_depth3_requirements_found():
    repo = make_repo({"a/b/c/requirements.txt": "flask\n"})
    found, primary, _ = _find_env_files(repo)
    assert any("requirements.txt" in k for k in found)
    assert primary is not None


def test_depth2_beats_depth3():
    repo = make_repo({
        "src/requirements.txt": "numpy\n",
        "src/lib/deep/requirements.txt": "flask\n",
        "src/model.py": "import numpy\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "src/requirements.txt"


# ── monorepo heuristic ────────────────────────────────────────────────────────

def test_monorepo_prefers_dir_with_most_py_files():
    """When multiple subdirs have requirements.txt, pick the one with most .py files."""
    repo = make_repo({
        "scripts/requirements.txt": "requests\n",
        "scripts/helper.py": "import requests\n",
        "main_package/requirements.txt": "torch\nnumpy\n",
        "main_package/model.py": "import torch\n",
        "main_package/train.py": "import torch\n",
        "main_package/eval.py": "import torch\n",
        "main_package/data.py": "import numpy\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "main_package/requirements.txt"


def test_monorepo_prefers_shallower_over_deeper():
    """Depth-1 subdir beats depth-2 even with fewer .py files."""
    repo = make_repo({
        "src/requirements.txt": "numpy\n",
        "src/module.py": "import numpy\n",
        "src/core/lib/requirements.txt": "torch\n",
        "src/core/lib/a.py": "import torch\n",
        "src/core/lib/b.py": "import torch\n",
        "src/core/lib/c.py": "import torch\n",
    })
    _, primary, _ = _find_env_files(repo)
    assert primary == "src/requirements.txt"


# ── found dict completeness ───────────────────────────────────────────────────

def test_found_includes_all_discovered_files():
    repo = make_repo({
        "requirements.txt": "numpy\n",
        "setup.py": "from setuptools import setup\nsetup(name='x')\n",
        "docker/Dockerfile": "FROM ubuntu\n",
    })
    found, _, _ = _find_env_files(repo)
    assert "requirements.txt" in found
    assert "setup.py" in found
    assert "docker/Dockerfile" in found


def test_primary_path_is_absolute_and_exists():
    repo = make_repo({"requirements.txt": "numpy\n"})
    _, primary, primary_path = _find_env_files(repo)
    assert primary_path is not None
    assert primary_path.is_absolute()
    assert primary_path.exists()
