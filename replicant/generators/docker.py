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
    if p.endswith("Dockerfile"):            return _existing(spec, d)
    if p.endswith((".yml", ".yaml")):       return _conda(spec, d)
    if "requirements" in p or p.endswith(("reqs.txt",)):  return _pip(spec, d)
    if p.endswith(("setup.py", "pyproject.toml", "setup.cfg")): return _setuppy(spec, d)
    if p.endswith("Pipfile"):               return _pipenv(spec, d)
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
    """Generate pip-based Dockerfile using AI-resolved dependencies."""
    
    # Use AI-resolved dependencies if available
    if spec.resolved_deps and spec.resolved_deps.dependencies:
        from replicant.analyzers.dependencies import generate_requirements_txt
        requirements_content = generate_requirements_txt(spec.resolved_deps)
        python_version = spec.resolved_deps.python_version
        
        # Check for TensorFlow version to determine base image
        base_image, tf_preinstalled = _select_base_image(spec.resolved_deps, python_version)
        
        # If TF is preinstalled in base image, filter it from requirements
        if tf_preinstalled:
            requirements_content = _filter_tensorflow_from_requirements(requirements_content)
    else:
        # Fallback to original requirements.txt
        requirements_content = ""
        if spec.primary_env_path and spec.primary_env_path.exists():
            requirements_content = spec.primary_env_path.read_text()
        python_version = spec.python_version
        base_image = f"python:{python_version}-slim"
        tf_preinstalled = False
    
    # Write requirements.txt
    (d / "requirements.txt").write_text(requirements_content)
    
    # Generate Dockerfile with appropriate base image
    if tf_preinstalled:
        # TensorFlow base images have old pip, upgrade it first
        (d / "Dockerfile").write_text(f"""\
FROM {base_image}
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /workspace
CMD ["/bin/bash"]
""")
    else:
        # Standard Python image
        (d / "Dockerfile").write_text(f"""\
FROM {base_image}
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /workspace
CMD ["/bin/bash"]
""")
    return d


def _select_base_image(resolved_deps, python_version: str) -> tuple[str, bool]:
    """Select the best Docker base image based on dependencies.
    
    Returns:
        (base_image, tf_preinstalled): The Docker image tag and whether TF is preinstalled
    """
    # Check if TensorFlow is in dependencies and what version
    tf_version = None
    for dep in resolved_deps.dependencies:
        pkg_lower = dep.package.lower()
        if pkg_lower in ("tensorflow", "tensorflow-gpu"):
            tf_version = dep.version_spec
            break
    
    if tf_version:
        # Parse TF version from spec like "==1.15.0" or ">=2.0,<3.0"
        if "1.15" in tf_version or "1.14" in tf_version or "1.13" in tf_version:
            # Use official TensorFlow 1.x image - these are x86_64 only
            # but that's fine for Docker which can emulate
            return "tensorflow/tensorflow:1.15.0-py3", True
        elif "1." in tf_version and "==" in tf_version:
            # Other TF 1.x versions
            version = tf_version.replace("==", "").strip()
            return f"tensorflow/tensorflow:{version}-py3", True
        elif "2.0" in tf_version or "2.1" in tf_version or "2.2" in tf_version:
            # Early TF 2.x
            version = tf_version.replace("==", "").replace(">=", "").split(",")[0].strip()
            if version:
                return f"tensorflow/tensorflow:{version}", True
    
    # Default to standard Python image
    v = python_version
    if v.count(".") > 1:
        v = ".".join(v.split(".")[:2])
    return f"python:{v}-slim", False


def _filter_tensorflow_from_requirements(requirements_content: str) -> str:
    """Remove tensorflow from requirements since it's in the base image."""
    lines = requirements_content.split("\n")
    filtered = []
    for line in lines:
        line_lower = line.lower().strip()
        # Skip tensorflow lines but keep other deps
        if line_lower.startswith("tensorflow") and not line_lower.startswith("tensorflow-hub"):
            filtered.append(f"# {line}  # Provided by base image")
        else:
            filtered.append(line)
    return "\n".join(filtered)


def _pipenv(spec: EnvironmentSpec, d: Path) -> Path:
    shutil.copy2(spec.primary_env_path, d / "Pipfile")
    lockfile = spec.primary_env_path.parent / "Pipfile.lock"
    if lockfile.exists():
        shutil.copy2(lockfile, d / "Pipfile.lock")
    v = spec.python_version
    if v.count(".") > 1: v = ".".join(v.split(".")[:2])
    (d / "Dockerfile").write_text(f"""\
FROM python:{v}-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pipenv
COPY Pipfile* /tmp/
RUN cd /tmp && pipenv install --system --deploy --ignore-pipfile || pipenv install --system
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
