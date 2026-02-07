# replicant

Turn research papers into working local environments.

## What It Does

Give **replicant** an arXiv paper (or a PDF, or a GitHub URL) and it will:

1. Extract the GitHub repository link from the paper
2. Clone the repo and detect existing environment files (`Dockerfile`, `environment.yml`, `requirements.txt`)
3. Generate a Docker image with all dependencies installed
4. Drop you into an interactive shell with the code mounted at `/workspace`

## Install

```bash
pip install -e .
```

Requires **Docker** to be installed and running.

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

### Global Flags

- `--verbose` — Show debug output (build logs, etc.)

## How Environments Are Built

Replicant detects environment files in priority order:

1. **`Dockerfile`** — Used as-is, built directly
2. **`environment.yml`** — Generates a conda-based Dockerfile
3. **`requirements.txt`** — Generates a pip-based Dockerfile with inferred Python version
4. **`setup.py` / `pyproject.toml`** — Generates a Dockerfile that `pip install`s the package

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
├── parsers/
│   ├── pdf.py          # Extract GitHub URLs from PDFs
│   ├── arxiv.py        # Fetch papers from arXiv
│   └── github.py       # Clone repositories
├── analyzers/
│   └── stage1.py       # Find environment files in repos
├── generators/
│   └── docker.py       # Generate Dockerfiles
├── executors/
│   └── local.py        # Docker build / run / shell
└── utils/
    ├── config.py       # Metadata management
    └── validation.py   # Environment validation
```

## License

MIT
