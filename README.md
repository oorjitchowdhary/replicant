# replicant

Turn research papers into working local environments using AI.

## What It Does

Give **replicant** an arXiv paper (or a PDF, or a GitHub URL) and it will:

1. **Intelligently analyze** the paper using an AI model (via AWS Bedrock) to extract GitHub repository links, dependencies, and environment details
2. Clone the repo and detect existing environment files (`Dockerfile`, `environment.yml`, `requirements.txt`, `Pipfile`, etc.)
3. Use AI to resolve ambiguous or underspecified dependencies with correct version pinning
4. Generate a Docker image with all dependencies installed
5. Drop you into an interactive shell with the code mounted at `/workspace`

## Setup

**Prerequisites:** Docker must be installed and running. An AWS account with Bedrock access is required.

```bash
pip install replicant
```

On first run, replicant will automatically launch a setup wizard:

```
[1/5] Checking Docker...
[2/5] Installing Terraform...
[3/5] AWS credentials...
[4/5] Selecting Bedrock model...
[5/5] Testing Bedrock access...
      Config saved to ~/.replicant/config.json
```

You can also run it explicitly at any time:

```bash
replicant init          # run setup wizard
replicant init --reset  # wipe config and start over
```

The wizard walks you through AWS credentials, region, and model selection. Config is saved to `~/.replicant/config.json`.

## Quick Start

```bash
# From an arXiv ID
replicant setup 2301.12345

# From a local PDF
replicant setup ./paper.pdf

# From a GitHub URL directly
replicant setup https://github.com/author/repo

# If the paper doesn't contain a GitHub link, specify it manually
replicant setup 2301.12345 --github https://github.com/author/repo

# Enter the environment
replicant shell
```

## Commands

| Command | Description |
|---------|-------------|
| `replicant init` | Run the first-time setup wizard |
| `replicant init --reset` | Wipe config and re-run wizard |
| `replicant setup <source>` | Set up from arXiv ID, PDF path, or GitHub URL |
| `replicant setup <source> --github <url>` | Specify GitHub repo explicitly |
| `replicant setup <source> --cloud` | Build on AWS EC2 (GPU / large data) |
| `replicant shell [env_id]` | Enter environment (latest if no ID) |
| `replicant list` | List all environments |
| `replicant info [env_id]` | Show environment details |
| `replicant delete <env_id>` | Remove environment and Docker image |
| `replicant validate [env_id]` | Run validation checks |
| `replicant llm-config` | Show current Bedrock config and test connection |
| `replicant cloud teardown <env_id>` | Tear down cloud infrastructure |
| `replicant cloud status` | List running cloud environments |
| `replicant benchmark <corpus>` | Batch-run across a corpus of papers |

### Global Flags

- `--verbose` — Show debug output (build logs, etc.)

### Benchmark Flags

```bash
replicant benchmark corpus.csv [OPTIONS]

  -o, --output DIR        Output directory for results (default: ~/.replicant/benchmark/)
  -t, --timeout SECONDS   Max seconds per Docker build (default: 600)
  -w, --workers N         Number of parallel workers (default: 4)
  --resume                Skip papers that already have result files
  --no-llm                Baseline mode: skip LLM inference, build directly from raw spec files
```

The `--no-llm` flag skips all Bedrock API calls and generates Dockerfiles directly from raw spec files. Useful for baseline comparisons — results include `"llm_assisted": false`.

## Cloud Execution

For papers that require a GPU or large datasets, replicant can provision an AWS EC2 instance automatically:

```bash
replicant setup 2301.12345 --cloud
```

replicant will prompt automatically when it detects GPU requirements or large data downloads. Cloud builds use a `g4dn.xlarge` instance by default and require Terraform (auto-installed by `replicant init`).

```bash
replicant cloud status              # list running cloud environments
replicant cloud teardown <env_id>   # shut down EC2 instance
```

## How Environments Are Built

replicant detects environment files in priority order:

1. **`Dockerfile`** — Used as-is, built directly
2. **`environment.yml`** — Generates a conda-based Dockerfile
3. **`requirements.txt`** — Generates a pip-based Dockerfile; AI resolves version pins
4. **`setup.py` / `pyproject.toml`** — Generates a Dockerfile that `pip install`s the package
5. **`Pipfile`** — Generates a pipenv-based Dockerfile

## Storage

All data lives under `~/.replicant/`:

```
~/.replicant/
├── config.json       # Bedrock model + AWS config (written by replicant init)
├── environments/     # Metadata JSON per environment
├── repos/            # Cloned repositories
├── dockerfiles/      # Generated Dockerfiles and build contexts
├── logs/             # Docker build logs
└── papers/           # Downloaded arXiv PDFs
```

Set `REPLICANT_HOME` to override the base directory.

## Architecture

```
replicant/
├── cli.py              # Click CLI entrypoint
├── sources/
│   ├── arxiv.py        # Fetch papers from arXiv
│   ├── github.py       # Clone repositories
│   └── pdf.py          # PDF text extraction
├── analyzers/
│   ├── repo.py         # Environment file detection and spec building
│   ├── paper.py        # AI-powered paper analysis
│   └── dependencies.py # AI dependency resolution and version pinning
├── generators/
│   └── docker.py       # Dockerfile generation
├── executors/
│   ├── local.py        # Docker build / run / shell (local)
│   └── cloud.py        # Docker build / run / shell (EC2)
├── providers/
│   └── aws.py          # Terraform wrapper for EC2 + S3 provisioning
├── benchmark.py        # Batch benchmarking across paper corpora
└── utils/
    ├── config.py        # EnvMeta dataclass, path constants
    ├── onboarding.py    # First-run wizard, config file management
    ├── llm_config.py    # Bedrock client + model configuration
    ├── preflight.py     # PyPI package validation
    ├── build_errors.py  # Build log parser for retry logic
    └── validation.py    # Post-build environment validation
```

## Docs

- [How it works](docs/how-it-works.md) — pipeline, AI dependency resolution, implementation overview
- [Supported environments](docs/supported-environments.md) — env file types, priority order, generated Dockerfiles
- [Troubleshooting](docs/troubleshooting.md) — failure categories and fixes

## License

MIT
