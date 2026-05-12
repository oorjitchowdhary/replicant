# How It Works

replicant turns a research paper (or GitHub repo) into a runnable Docker environment in five steps.

## Pipeline

```
source (arXiv / PDF / GitHub URL)
         │
         ▼
  1. Fetch & extract
         │
         ▼
  2. Analyze repo
         │
         ▼
  3. AI dependency resolution
         │
         ▼
  4. Generate Dockerfile
         │
         ▼
  5. Docker build → shell
```

### 1. Fetch & extract

- **arXiv ID** → downloads the PDF from arXiv, extracts text, runs `paper.py` to pull out the GitHub URL, datasets, hardware hints, and frameworks mentioned in the paper.
- **Local PDF** → same analysis, skips the download.
- **GitHub URL** → skips paper analysis entirely; clones directly.

The paper analyzer uses Claude (via AWS Bedrock) to parse unstructured text and return structured output: GitHub links, dataset names, download URLs, checkpoint URLs, GPU/TPU requirements.

### 2. Analyze repo

`analyzers/repo.py` scans the cloned repository:

- **Environment files** — detected in priority order (see [Supported Environments](supported-environments.md)). The highest-priority file becomes the `primary_env` that drives Dockerfile generation.
- **Packages** — parsed from `requirements.txt`, `environment.yml`, `setup.py`, `pyproject.toml`.
- **Datasets & downloads** — regex patterns scan all text files for HuggingFace `load_dataset()` calls, `wget`/`curl`/`gdown` commands, Google Drive links, and direct `.tar.gz`/`.zip` URLs.
- **Hardware** — scans for `cuda`, `.to('cuda')`, `torch.device`, `tpu`, `xla` patterns.
- **Entrypoints** — finds scripts named `train*.py`, `main*.py`, `run*.py`, `eval*.py`, etc.
- **Python version** — checks `.python-version`, `runtime.txt`, `environment.yml` in that order, then falls back to regex on all text files, then defaults to 3.10.

If a PDF was provided, paper context is merged in: datasets, frameworks, hardware hints, and download URLs from the paper augment what was found in the repo.

### 3. AI dependency resolution

`analyzers/dependencies.py` sends the full context — existing requirements, env yml, setup.py, representative code samples, README — to Claude with a structured JSON schema.

The model returns `ResolvedDependencies`: a Python version with reasoning, every package pinned to a compatible version with a brief rationale, compatibility notes, and any special install commands (e.g. for CUDA wheels).

Key heuristics baked into the prompt:
- Uses the repo's git commit year to pick era-appropriate versions (e.g. `numpy<2.0` for pre-2024 repos, `protobuf<4.0` for pre-2023)
- Matches PyTorch ↔ torchvision ↔ torchaudio versions
- Detects TF 1.x API patterns (`tf.Session`, `tf.placeholder`, `tf.contrib`) and forces `tensorflow==1.15.0` + Python 3.7
- Respects existing pins; only overrides if clearly broken

This step is skipped when `--no-llm` is passed (baseline mode).

### 4. Generate Dockerfile

`generators/docker.py` picks a generation strategy based on `primary_env`:

| Env file | Strategy |
|----------|----------|
| `Dockerfile` | Used as-is (copied directly) |
| `environment.yml` | `continuumio/miniconda3` base, `conda env create` |
| `requirements.txt` | `python:{version}-slim`, `pip install -r` using AI-resolved deps |
| `setup.py` / `pyproject.toml` | `python:{version}-slim`, `pip install .` |
| `Pipfile` | `python:{version}-slim`, `pipenv install --system` |

For `requirements.txt`, if TensorFlow 1.x is detected the base image switches to `tensorflow/tensorflow:1.15.0-py3` to avoid the notoriously painful TF 1.x install.

### 5. Docker build

`executors/local.py` runs `docker build` in the generated context directory. Build logs are streamed to `~/.replicant/logs/{image}.log`. On success the environment is marked `ready`; on failure it's `failed` and the log has the full error.

## Storage layout

```
~/.replicant/
├── environments/   # One JSON metadata file per environment
├── repos/          # Cloned repositories
├── dockerfiles/    # Generated build contexts (Dockerfile + supporting files)
├── logs/           # Docker build logs
└── papers/         # Downloaded arXiv PDFs
```

Set `REPLICANT_HOME` to use a different base directory.

## LLM integration

replicant uses **Claude via AWS Bedrock** (default: `us.anthropic.claude-sonnet-4-6`). Two modules make LLM calls:

- `analyzers/paper.py` — paper analysis (GitHub URL extraction, datasets, hardware)
- `analyzers/dependencies.py` — dependency resolution

Both use `boto3` with the Bedrock `converse` API. The bearer token auth is handled via `AWS_BEARER_TOKEN_BEDROCK`. Override the model with `BEDROCK_MODEL_ID` and region with `AWS_DEFAULT_REGION`.

Throttling is handled with exponential backoff (30s, 60s retry).
