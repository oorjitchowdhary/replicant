# replicant

Turn research papers into working local environments using AI.

## What It Does

Give **replicant** an arXiv paper (or a PDF, or a GitHub URL) and it will:

1. **Intelligently analyze** the paper using Claude (via AWS Bedrock) to extract GitHub repository links, dependencies, and environment details
2. Clone the repo and detect existing environment files (`Dockerfile`, `environment.yml`, `requirements.txt`, `Pipfile`, etc.)
3. Use AI to resolve ambiguous or underspecified dependencies with correct version pinning
4. Generate a Docker image with all dependencies installed
5. Drop you into an interactive shell with the code mounted at `/workspace`

## Setup

**Prerequisites:** Docker must be installed and running.

```bash
# Install
pip install -e .

# Set your AWS Bedrock bearer token
export AWS_BEARER_TOKEN_BEDROCK=your_token

# Optional overrides
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6  # default
export AWS_DEFAULT_REGION=us-west-2                     # default

# Verify setup
replicant llm-config
```

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
| `replicant setup <source>` | Set up from arXiv ID, PDF path, or GitHub URL |
| `replicant setup <source> --github <url>` | Specify GitHub repo explicitly |
| `replicant shell [env_id]` | Enter environment (latest if no ID) |
| `replicant list` | List all environments |
| `replicant info [env_id]` | Show environment details |
| `replicant delete <env_id>` | Remove environment and Docker image |
| `replicant validate [env_id]` | Run validation checks |
| `replicant benchmark <corpus>` | Batch-run across a corpus of papers |
| `replicant llm-config` | Check and configure AI (Bedrock) setup |

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

The `--no-llm` flag is useful for baseline comparisons — it runs the same pipeline but skips all Bedrock API calls and generates Dockerfiles directly from the raw specification files. Results include `"llm_assisted": false` to distinguish baseline runs. `AWS_BEARER_TOKEN_BEDROCK` is not required in this mode.

## How Environments Are Built

Replicant detects environment files in priority order:

1. **`Dockerfile`** — Used as-is, built directly
2. **`environment.yml`** — Generates a conda-based Dockerfile
3. **`requirements.txt`** — Generates a pip-based Dockerfile; AI resolves version pins
4. **`setup.py` / `pyproject.toml`** — Generates a Dockerfile that `pip install`s the package
5. **`Pipfile`** — Generates a pipenv-based Dockerfile

## Storage

All data lives under `~/.replicant/`:

```
~/.replicant/
├── environments/   # Metadata JSON per environment
├── repos/          # Cloned repositories
├── dockerfiles/    # Generated Dockerfiles and build contexts
├── logs/           # Docker build logs
└── papers/         # Downloaded arXiv PDFs
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
│   └── local.py        # Docker build / run / shell
├── benchmark.py        # Batch benchmarking across paper corpora
└── utils/
    ├── config.py        # Metadata management
    ├── llm_config.py    # AWS Bedrock configuration
    └── validation.py    # Environment validation
```

## Docs

- [How it works](docs/how-it-works.md) — pipeline, AI dependency resolution, implementation overview
- [Supported environments](docs/supported-environments.md) — env file types, priority order, generated Dockerfiles
- [Troubleshooting](docs/troubleshooting.md) — failure categories and fixes

## License

MIT
