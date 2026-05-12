# Troubleshooting

## Setup fails immediately

**`AWS_BEARER_TOKEN_BEDROCK is required`**

Run `replicant llm-config` — it will tell you exactly what's missing and how to get it. The token is a short-lived bearer token for AWS Bedrock, not a static API key.

**`Docker is not running`**

Start Docker Desktop (or the Docker daemon) and retry.

**`No GitHub URL found`**

The paper doesn't link to a GitHub repo, or replicant couldn't extract it. Pass the URL manually:
```bash
replicant setup 2301.12345 --github https://github.com/author/repo
```

## Build fails

Build logs are always written to `~/.replicant/logs/replicant-{env_id}.log`. This is the first place to look.

```bash
cat ~/.replicant/logs/replicant-$(replicant list | tail -1 | awk '{print $1}').log
```

Common failure categories and fixes:

---

### `phantom_dependency`

A package in `requirements.txt` doesn't exist on PyPI (typo, internal package, renamed package, or a package that was deleted).

**Fix**: The AI resolver usually catches these, but if it misses one, delete the environment and re-run — the LLM may produce a different resolution. If the package is genuinely unpublished, there's no automated fix.

---

### `version_conflict`

Packages have incompatible version requirements (e.g. package A needs `numpy<1.24` but package B needs `numpy>=1.24`).

**Fix**: Usually the AI resolver handles this. If it fails, check the build log — it will show the exact conflict. You can also try deleting the environment and re-running; the LLM may find a different set of compatible versions.

---

### `build_timeout`

Docker build exceeded the timeout (default: 600s). Most common with large conda environments or packages that compile from source.

**Fix**: Increase the timeout with `--timeout` in benchmark mode. For single setups there's no timeout.

---

### `missing_env_spec`

No environment file was found in the repo (no `requirements.txt`, `environment.yml`, `Dockerfile`, `setup.py`, etc.).

**Fix**: Use `--github` to point at a specific repo that has environment files, or provide the env file manually. This is a repo-level issue — replicant can't generate an environment spec from nothing.

---

### `no_runnable_code`

The repo was cloned but there's no Python code to run (e.g. it's a data repository, a LaTeX paper source, or only contains notebooks).

---

### `unknown_build_error`

Something failed during `docker build` that doesn't match a known pattern. Check the build log — it will have the exact `RUN` step that failed and the error output.

Common causes:
- A `apt-get` package name that changed
- A `pip install` that needs build dependencies not in the base image (try adding `-y libxml2-dev` etc.)
- Platform mismatch (some packages only build on x86_64; if you're on Apple Silicon, Docker runs in emulation and some wheels may be unavailable)

---

### `build_order_dependency`

A package must be installed before another (e.g. `torch` must be installed before `flash-attn`). The AI resolver adds `install_commands` for these cases, but sometimes misses them.

---

## Environment shows as `failed`

```bash
replicant info <env_id>        # see status and metadata
replicant delete <env_id>      # remove it
replicant setup <source>       # retry
```

## Checking what replicant detected

Run with `--verbose` to see Docker build output in real time:
```bash
replicant --verbose setup 2301.12345
```

The environment spec table printed before the build shows exactly what Python version and dependencies the AI chose, including the reasoning for each pin.

## Cleaning up

```bash
replicant list                 # see all environments
replicant delete <env_id>      # delete one (removes Docker image + cloned repo)
replicant delete --all         # delete everything
replicant delete <env_id> --keep-code   # delete image but keep cloned repo
```

Docker images can also take up significant disk space. If you're running low:
```bash
docker image ls | grep replicant
docker image prune
```
