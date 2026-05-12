# Supported Environment Files

replicant detects environment files in priority order. The highest-priority file found becomes the `primary_env` and drives Dockerfile generation.

## Priority order

1. `Dockerfile` (root), `docker/Dockerfile`
2. `environment.yml`, `environment.yaml`, `conda_environment.yml`, `conda.yml`
3. `requirements.txt` (root)
4. `requirements-*.txt`, `requirements_*.txt` (root, largest wins)
5. `requirements/*.txt` (subdirectory; `requirements/requirements.txt` preferred, else largest)
6. `setup.py`
7. `pyproject.toml`, `setup.cfg`
8. `Pipfile`
9. One-level-deep fallbacks (e.g. `mypackage/setup.py`)

If none of these are found, setup fails with `missing_env_spec`.

## What each generates

### Dockerfile

Used as-is. The repo is copied into the build context alongside the Dockerfile. No modifications are made.

**Best case.** If the paper's repo ships a working Dockerfile, replicant uses it directly.

### environment.yml (conda)

```dockerfile
FROM continuumio/miniconda3:latest
COPY environment.yml /tmp/environment.yml
RUN conda env create -f /tmp/environment.yml -n env && conda clean -afy
RUN echo "conda activate env" >> ~/.bashrc
SHELL ["conda", "run", "-n", "env", "/bin/bash", "-c"]
WORKDIR /workspace
```

The conda environment is activated by default in the shell.

### requirements.txt (pip)

AI-resolved dependencies replace the original `requirements.txt`. The Python version and all package versions come from Claude's analysis of the repo code, not just what's written in the file.

```dockerfile
FROM python:{version}-slim           # or tensorflow/tensorflow:{version} for TF 1.x
RUN apt-get install -y build-essential git
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /workspace
```

**TensorFlow 1.x special case**: if Claude detects TF 1.x API patterns (`tf.Session`, `tf.placeholder`, `tf.contrib`), the base image switches to `tensorflow/tensorflow:1.15.0-py3` and TF is removed from `requirements.txt` since it's already in the image.

### setup.py / pyproject.toml / setup.cfg

The whole repo is copied and installed as a package.

```dockerfile
FROM python:{version}-slim
RUN apt-get install -y build-essential git
COPY repo /tmp/repo
RUN pip install --no-cache-dir /tmp/repo
WORKDIR /workspace
```

### Pipfile

```dockerfile
FROM python:{version}-slim
RUN pip install pipenv
COPY Pipfile* /tmp/
RUN cd /tmp && pipenv install --system --deploy --ignore-pipfile || pipenv install --system
WORKDIR /workspace
```

Falls back to `pipenv install --system` (without lock file enforcement) if `--deploy` fails.

## Baseline mode

Pass `--no-llm` to `replicant benchmark` to skip AI dependency resolution entirely. The Dockerfile is generated directly from the raw spec file with no version inference. Useful for comparing against the AI-assisted baseline.

In baseline mode:
- `requirements.txt` is used verbatim (no AI re-pinning)
- Python version defaults to what's detected in the file, or 3.10
- No TF 1.x special-casing
