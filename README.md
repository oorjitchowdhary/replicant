# replicant

**One command from paper to running code.**

Give replicant an arXiv ID, a PDF, or a GitHub URL and it clones the repo, resolves the dependencies with AI, and drops you into a working Docker environment — without touching your local Python.

```bash
pip install replicant
replicant setup 2103.00020   # CLIP — OpenAI's vision-language model
replicant shell              # enter the environment
```

Works on any ML paper. GPU papers spin up an EC2 instance automatically.

---

## Prerequisites

- **Docker** — must be installed and running
- **AWS account** — for Bedrock (the AI backbone) and optionally EC2 (cloud/GPU builds)

On first run, `replicant setup` will walk you through AWS credentials and model selection. You can also run it explicitly:

```bash
replicant init
```

The wizard checks Docker, installs Terraform if needed, verifies AWS credentials, and tests Bedrock access. Takes about 2 minutes.

---

## Install

```bash
pip install replicant
```

Requires Python 3.9+.

---

## Quick Start

```bash
# From an arXiv ID
replicant setup 2301.07041

# From a PDF
replicant setup ./attention-is-all-you-need.pdf

# From a GitHub URL directly
replicant setup https://github.com/karpathy/nanoGPT

# Paper doesn't include a GitHub link? Specify it manually
replicant setup 2301.07041 --github https://github.com/author/repo

# Enter the environment
replicant shell

# Enter a specific environment by ID
replicant shell a3f2c1b0
```

---

## Commands

| Command | Description |
|---------|-------------|
| `replicant init` | Run the first-time setup wizard |
| `replicant init --reset` | Wipe config and re-run wizard |
| `replicant setup <source>` | Set up from arXiv ID, PDF path, or GitHub URL |
| `replicant setup <source> --cloud` | Build on AWS EC2 (GPU / large data) |
| `replicant shell [env_id]` | Enter environment (latest if no ID given) |
| `replicant list` | List all environments |
| `replicant info [env_id]` | Show environment details |
| `replicant delete <env_id>` | Remove environment and Docker image |
| `replicant delete --all` | Remove all environments |
| `replicant validate [env_id]` | Run post-build validation checks |
| `replicant llm-config` | Show current Bedrock config and test connection |
| `replicant cloud status` | List running cloud environments |
| `replicant cloud teardown <env_id>` | Shut down EC2 instance |
| `replicant benchmark <corpus>` | Batch-run across a CSV corpus of papers |

**Global flag:** `--verbose` — stream build logs and debug output.

---

## Cloud Execution

When a paper requires a GPU or downloads large datasets, replicant will prompt automatically:

```
GPU required. Run in the cloud? [y/N]:
```

Or pass `--cloud` to skip the prompt:

```bash
replicant setup 2103.00020 --cloud
```

This provisions a `g4dn.xlarge` EC2 instance (NVIDIA T4), builds the Docker image on it, pushes to ECR, and streams the shell over SSH. The instance runs until you explicitly tear it down:

```bash
replicant cloud teardown <env_id>
```

Cloud builds require Terraform — the `replicant init` wizard installs it automatically on macOS and Linux.

---

## How It Works

replicant analyzes the repo and paper to build an environment spec, then generates a Dockerfile:

1. **Detect** — searches the repo for `Dockerfile`, `environment.yml`, `requirements.txt`, `setup.py`, `pyproject.toml`, `Pipfile` (3 levels deep, monorepo-aware)
2. **Resolve** — Claude reads the paper and repo together to fill in missing dependencies, fix version conflicts, and pin everything correctly
3. **Validate** — checks every package name against PyPI before building; phantoms are re-resolved automatically
4. **Build** — Docker image is built locally or on EC2; one-shot retry on failure re-resolves with the build error as context
5. **Shell** — drops you into `/workspace` with the cloned code mounted

All data lives under `~/.replicant/`. Set `REPLICANT_HOME` to override.

---

## Docs

- [How it works](docs/how-it-works.md) — pipeline, AI dependency resolution, retry logic
- [Supported environments](docs/supported-environments.md) — env file types, priority order, Dockerfile templates
- [Troubleshooting](docs/troubleshooting.md) — common failures and fixes

---

## License

[GNU Affero General Public License v3.0](LICENSE)
