# replicant — Claude Code Guide

## What this project is

replicant turns research papers into runnable Docker environments. Given an arXiv ID, PDF, or GitHub URL it clones the repo, analyzes it with Claude (via AWS Bedrock), resolves dependencies, generates a Dockerfile, and builds the image. GPU/large-data papers can run on AWS EC2 via `--cloud`.

## Running and testing

```bash
# install (editable)
pip install -e ".[dev]"

# run all tests
python -m pytest

# run a specific test file
python -m pytest tests/test_find_env_files.py -v

# CLI smoke-check (requires AWS_BEARER_TOKEN_BEDROCK)
replicant llm-config
replicant setup 2301.00001
replicant setup https://github.com/org/repo --cloud
```

Tests never hit the network or Docker — all external calls are mocked. One pre-existing failure in `tests/test_paper.py::test_extract_context_frameworks` is unrelated to active work (framework name format mismatch).

## Repo layout

```
replicant/
  analyzers/
    repo.py           # _find_env_files(), analyze(), _resolve_with_ai()
    dependencies.py   # resolve_dependencies() — LLM structured output
    paper.py          # analyze_paper() — arXiv/PDF context extraction
  executors/
    base.py           # Executor protocol
    local.py          # LocalExecutor (+ module-level backward-compat wrappers)
    cloud.py          # CloudExecutor — rsync → SSH docker build → S3
  providers/
    base.py           # CloudProvider protocol, CloudResources dataclass
    aws.py            # AWSProvider wrapping terraform subprocess
  generators/
    docker.py         # generate() — renders Dockerfile from EnvironmentSpec
  sources/
    arxiv.py          # fetch arXiv metadata + PDF
    github.py         # clone repo
    pdf.py            # extract text from PDF
  utils/
    config.py         # EnvMeta dataclass, path constants (HOME, LOGS, etc.)
    preflight.py      # validate_packages(), revalidate_with_llm()
    build_errors.py   # parse_build_failure() — extract signal from build log
    llm_config.py     # check_bedrock_setup()
    patterns.py       # GITHUB_RE and other regexes
    validation.py     # post-build environment validation checks
  cli.py              # Click entrypoint — setup, shell, list, info, delete,
                      #   validate, benchmark, llm-config, cloud teardown/status
  benchmark.py        # PaperResult model, run_benchmark(), _run_one()
terraform/aws/        # Terraform config for EC2 + S3 (g4dn.xlarge default)
tests/                # Unit tests — one file per module
docs/                 # how-it-works.md, supported-environments.md, troubleshooting.md
```

## Key data types

**`EnvironmentSpec`** (`analyzers/repo.py`) — everything `analyze()` produces: `primary_env`, `env_files`, `python_version`, `resolved_deps`, `frameworks`, `packages`, `datasets`, `download_urls`, `needs_gpu`, `needs_tpu`, `readme_setup`, etc.

**`ResolvedDependencies`** / **`DependencySpec`** (`analyzers/dependencies.py`) — Pydantic models for LLM structured output. `DependencySpec` has `package`, `version_spec`, `reason`, `is_critical`.

**`EnvMeta`** (`utils/config.py`) — persisted JSON per environment in `~/.replicant/environments/`. Fields: `env_id`, `source`, `github_url`, `docker_image`, `status`, `code_path`, cloud fields (`cloud_provider`, `cloud_instance_id`, `cloud_region`, `cloud_bucket`).

**`CloudResources`** (`providers/base.py`) — output of `provision()`: `instance_ip`, `ssh_key_path`, `s3_bucket`, `instance_id`, `region`.

**`PaperResult`** (`benchmark.py`) — Pydantic model for benchmark output JSON. Includes `retry_attempted: bool`.

## LLM integration

All LLM calls go through AWS Bedrock (Claude Sonnet). Requires `AWS_BEARER_TOKEN_BEDROCK` env var. The model is configured in `utils/llm_config.py`. `resolve_dependencies()` and `analyze_paper()` both call Bedrock — never call them in tests without mocking.

## Core pipeline (setup command)

1. Resolve GitHub URL from arXiv / PDF / direct input
2. Clone repo (`sources/github.py`)
3. `analyze(code_path, pdf_path)` → `EnvironmentSpec`
   - `_find_env_files()` — searches 3 levels deep, monorepo heuristic
   - `_resolve_with_ai()` — LLM dependency resolution + PyPI preflight validation
4. Auto-prompt for `--cloud` if `needs_gpu` or `download_urls`
5. `generate(spec, eid)` → Dockerfile in `~/.replicant/dockerfiles/<eid>/`
6. `LocalExecutor.build()` or `CloudExecutor.build()` → docker image
7. One-shot retry on failure: parse build log → re-resolve with failure context → rebuild

## Phase roadmap

**Phase 1 (done):** Env file detection depth, PyPI preflight validation, one-shot build retry, cloud execution via EC2/Terraform.

**Phase 2 (next):** Import inference — when `primary_env is None` after `_find_env_files()`, scan `.py` files for imports, filter stdlib/internal, map to PyPI packages via known table + LLM fallback. New file: `replicant/analyzers/imports.py`. Trigger: `analyze()` in `analyzers/repo.py`. Show confidence indicators; prompt user before building inferred deps.

**Phase 3 (deferred):** Non-technical paper reproducibility — find closest open-source implementation via Papers with Code + GitHub search.

## Git workflow

- Main branch is `main` — the tool. `acm-rep-2026` branch holds benchmark artifacts (results, corpus files).
- Benchmark data (`results/`, `corpus*.csv`, `corpus*.json`) is gitignored on main.
- Never commit ANSI color codes into messages — write commit messages to a temp file and use `git commit -F <file>`.
- Always ask before running any git command.
