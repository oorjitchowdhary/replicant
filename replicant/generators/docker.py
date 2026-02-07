"""Generate Dockerfiles from EnvironmentSpec."""
from __future__ import annotations
import shutil
from pathlib import Path
from replicant.analyzers.repo import EnvironmentSpec
from replicant.utils.config import BUILD, ensure_dirs


def generate(spec: EnvironmentSpec, eid: str) -> Path:
    ensure_dirs()
    d = BUILD / eid; d.mkdir(parents=True, exist_ok=True)
    p = spec.primary_env
    if not p:
        raise RuntimeError("No environment file found in repo.")
    if p.endswith("Dockerfile"):       return _existing(spec, d)
    if p.endswith((".yml", ".yaml")):   return _conda(spec, d)
    if "requirements" in p:            return _pip(spec, d)
    if p in ("setup.py","pyproject.toml"): return _setuppy(spec, d)
    raise RuntimeError(f"Can't handle: {p}")


def _existing(spec: EnvironmentSpec, d: Path) -> Path:
    dest = d / "repo"
    if dest.exists(): shutil.rmtree(dest)
    shutil.copytree(spec.repo_path, dest, dirs_exist_ok=True)
    src = dest / spec.primary_env_path.relative_to(spec.repo_path)
    shutil.copy2(src, d / "Dockerfile")
    return d


def _conda(spec: EnvironmentSpec, d: Path) -> Path:
    f = spec.primary_env_path
    shutil.copy2(f, d / f.name)
    (d / "Dockerfile").write_text(f"""\
FROM continuumio/miniconda3:latest
COPY {f.name} /tmp/{f.name}
RUN conda env create -f /tmp/{f.name} -n env && conda clean -afy
RUN echo "conda activate env" >> ~/.bashrc
SHELL ["conda", "run", "-n", "env", "/bin/bash", "-c"]
WORKDIR /workspace
CMD ["/bin/bash"]
""")
    return d


def _pip(spec: EnvironmentSpec, d: Path) -> Path:
    shutil.copy2(spec.primary_env_path, d / "requirements.txt")
    v = spec.python_version
    if v.count(".") > 1: v = ".".join(v.split(".")[:2])
    (d / "Dockerfile").write_text(f"""\
FROM python:{v}-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /workspace
CMD ["/bin/bash"]
""")
    return d


def _setuppy(spec: EnvironmentSpec, d: Path) -> Path:
    dest = d / "repo"
    if dest.exists(): shutil.rmtree(dest)
    shutil.copytree(spec.repo_path, dest, dirs_exist_ok=True)
    v = spec.python_version
    if v.count(".") > 1: v = ".".join(v.split(".")[:2])
    (d / "Dockerfile").write_text(f"""\
FROM python:{v}-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git && rm -rf /var/lib/apt/lists/*
COPY repo /tmp/repo
RUN pip install --no-cache-dir /tmp/repo
WORKDIR /workspace
CMD ["/bin/bash"]
""")
    return d
