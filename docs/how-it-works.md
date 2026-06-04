# How It Works

replicant turns a research paper (or GitHub repo) into a runnable Docker environment in five steps, with PyPI validation and one-shot retry baked in.

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
  3b. PyPI preflight validation
         │
         ▼
  4. Generate Dockerfile
         │
         ▼
  5. Docker build → (retry on failure) → shell
```

### 1. Fetch & extract

- **arXiv ID** → downloads the PDF, extracts text, runs `paper.py` to pull out the GitHub URL, datasets, hardware hints, and frameworks mentioned in the paper.
- **Local PDF** → same analysis, skips the download.
- **GitHub URL** → skips paper analysis entirely; clones directly.

The paper analyzer uses Claude (via AWS Bedrock) to parse unstructured text and return structured output: GitHub links, dataset names, download URLs, checkpoint URLs, GPU/TPU requirements.

### 2. Analyze repo

`analyzers/repo.py` scans the cloned repository:

- **Environment files** — detected in priority order (see [Supported Environments](supported-environments.md)). Searches up to 3 levels deep with monorepo-aware heuristics. The highest-priority file becomes the `primary_env` that drives Dockerfile generation.
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

### 3b. PyPI preflight validation

Before generating the Dockerfile, `utils/preflight.py` checks every resolved package name against the PyPI JSON API in parallel. Any 404s are phantom dependencies — packages that don't exist on PyPI.

If phantoms are found, the resolver re-runs with the phantom names appended to the prompt as additional context. The corrected resolution is validated once more. If phantoms persist after the re-run, a warning is shown and the build proceeds — the one-shot retry in step 5 handles it if the build breaks.

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

**Local builds:** `executors/local.py` runs `docker build` in the generated context directory. Build logs are streamed to `~/.replicant/logs/{env_id}.log`.

**Cloud builds (`--cloud`):** `executors/cloud.py` rsyncs the build context to the EC2 instance, runs `docker build` remotely (streaming output over SSH), authenticates with ECR, then tags and pushes the image. On `replicant shell`, the image is pulled from ECR if not cached locally on the instance and run with the code mounted at `/workspace`.

**One-shot retry:** If the build fails, `utils/build_errors.py` extracts the failing `RUN` step and the last 50 lines of the error log, then re-invokes the dependency resolver with that failure context appended. A new Dockerfile is generated and the build is retried once. The retry attempt is logged distinctly.

On success the environment is marked `ready`. On failure (including after retry) it's marked `failed` and the log has the full error.

---

## Cloud execution

Cloud builds provision an EC2 `g4dn.xlarge` instance (NVIDIA T4 GPU) via Terraform. Infrastructure is managed per-environment: each cloud build gets its own ECR repository.

```
replicant setup <paper> --cloud
         │
         ├─ AWSProvider.provision()
         │    └─ terraform apply (EC2 + ECR + IAM)
         │
         ├─ CloudExecutor.build()
         │    ├─ rsync build context → EC2
         │    ├─ docker build (on EC2)
         │    ├─ ECR login (aws ecr get-login-password | docker login)
         │    └─ docker tag + push → ECR
         │
         ├─ sync code → EC2 ~/code
         │
         └─ ready

replicant shell <env_id>
         │
         ├─ ECR login
         ├─ docker pull (if not cached)
         └─ docker run -it -v ~/code:/workspace
```

Terraform state lives in `~/.replicant/terraform/aws/`. Terraform binaries are bundled with the pip package; the `replicant init` wizard installs the `terraform` CLI if it's not already present.

Tear down with `replicant cloud teardown <env_id>` or `replicant delete <env_id>` — both call `terraform destroy` and remove ECR images.

---

## Storage layout

```
~/.replicant/
├── config.json       # Bedrock model + AWS region + profile (written by replicant init)
├── environments/     # One JSON metadata file per environment
├── repos/            # Cloned repositories
├── dockerfiles/      # Generated build contexts (Dockerfile + supporting files)
├── logs/             # Docker build logs
├── papers/           # Downloaded arXiv PDFs
└── terraform/        # Terraform working directory (state, provider cache)
    └── aws/
```

Set `REPLICANT_HOME` to use a different base directory.

---

## LLM integration

replicant uses **Claude via AWS Bedrock**. Two modules make LLM calls:

- `analyzers/paper.py` — paper analysis (GitHub URL extraction, datasets, hardware)
- `analyzers/dependencies.py` — dependency resolution and version pinning

Both use `boto3` with the Bedrock `converse` API. Credentials and model selection are configured by `replicant init` and stored in `~/.replicant/config.json`. To override without re-running init, set `BEDROCK_MODEL_ID` and `AWS_DEFAULT_REGION` as environment variables.

Throttling is handled with exponential backoff (30s, 60s retry).
