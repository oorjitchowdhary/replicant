# Onboarding & Generic Bedrock Setup — Design Spec

**Date:** 2026-05-24  
**Status:** Approved

---

## Problem

replicant currently requires a UW-specific `AWS_BEARER_TOKEN_BEDROCK` env var that no public user would have. There is no first-run setup flow, no Terraform install assistance, and no way to pick a Bedrock model. This blocks a public PyPI release.

---

## Goals

- Any user with an AWS account can install replicant and get running in under 5 minutes
- First run auto-triggers a wizard — no `replicant init` required, though it works as an explicit command too
- Standard boto3 credential chain replaces the UW bearer token entirely
- Terraform is auto-installed if possible; local execution works without it
- Users can pick any Bedrock model from a curated list

---

## Architecture

### New file: `replicant/utils/onboarding.py`

Contains all wizard logic. Three public functions:

```python
def load_config() -> dict:
    """Load ~/.replicant/config.json. Returns {} if missing."""

def save_config(cfg: dict) -> None:
    """Write ~/.replicant/config.json atomically."""

def ensure_configured() -> None:
    """Run wizard if config is missing or incomplete. Called at top of every CLI command."""

def run_wizard(reset: bool = False) -> None:
    """Run the full 5-step onboarding wizard."""
```

### Config file: `~/.replicant/config.json`

```json
{
  "aws_region": "us-east-1",
  "bedrock_model_id": "us.anthropic.claude-sonnet-4-6-20251001-v2:0",
  "aws_profile": "default"
}
```

Config is considered complete if both `aws_region` and `bedrock_model_id` are present. `aws_profile` is optional — omitting it uses the default boto3 credential chain.

### Modified: `replicant/utils/llm_config.py`

- Remove `AWS_BEARER_TOKEN_BEDROCK` check entirely
- `get_bedrock_client()` reads from config file first, then env vars, then boto3 defaults
- `check_bedrock_setup()` renamed to `test_bedrock_connection(model_id, region, profile)` — same `(bool, str)` return, used by wizard step 5
- `BEDROCK_MODEL_ID` reads from config file via `load_config()`

### Modified: `replicant/cli.py`

- Each command calls `ensure_configured()` at the top (before any other logic)
- `replicant init` added: runs `run_wizard(reset=False)`
- `replicant init --reset` runs `run_wizard(reset=True)` — wipes config and restarts
- `replicant llm-config` updated to print current config from file + run a live Bedrock test

---

## Wizard Flow

```
[1/5] Checking Docker...
[2/5] Installing Terraform...
[3/5] AWS credentials...
[4/5] Selecting Bedrock model...
[5/5] Testing Bedrock access...
      Config saved to ~/.replicant/config.json
```

### Step 1 — Docker

Calls existing `check_docker()`. On failure: print fix instructions and abort wizard. Docker is required for all replicant usage.

### Step 2 — Terraform

`shutil.which("terraform")` — if found, print path and continue.

If missing, auto-install in order:
1. **macOS**: `brew tap hashicorp/tap && brew install hashicorp/tap/terraform` (if `brew` in PATH)
2. **Linux (apt)**: HashiCorp apt repository + `apt-get install terraform`
3. **Linux/WSL fallback**: download zip from `releases.hashicorp.com` for detected arch, unzip to `~/.local/bin/`, append to `~/.bashrc` / `~/.zshrc`

On install failure: print `https://developer.hashicorp.com/terraform/install` and a warning that cloud execution won't work. **Do not abort** — local execution works without Terraform.

Install runs with a `rich` spinner; stderr is captured and shown inline on failure.

### Step 3 — AWS credentials

Calls `boto3.Session().get_credentials()`:
- If credentials found: show which profile/source and ask user to confirm (`[Y/n]`)
- If not found: run existing `_prompt_iam_credentials()` flow from `providers/aws.py` (prompts for Access Key ID + Secret, opens browser to IAM console, tests with STS, saves to `~/.aws/credentials`)

Prompts for region (default: `us-east-1`, shown with a note that this should match where Bedrock is enabled on their account).

### Step 4 — Model selection

Present a numbered list:
```
  1. claude-sonnet-4-6   (recommended — best quality)
  2. claude-haiku-4-5    (fastest, cheapest)
  3. claude-sonnet-3-5   (widely available)
  4. claude-opus-4-7     (most capable, slower)
  Enter number [1]:
```

Model IDs are the full Bedrock cross-region inference profile IDs. Default is option 1.

### Step 5 — Bedrock test

Fires a minimal `converse()` call with `maxTokens: 16`. On success: write config and print confirmation. On failure: show the specific boto3 error, re-prompt credentials (back to step 3), retry once. If still failing after retry: abort with instructions to check IAM permissions and Bedrock model access in the AWS console.

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Docker not running | Abort wizard with fix instructions |
| Terraform install fails | Warn + continue (cloud optional) |
| AWS credentials invalid | Re-prompt once, then abort with IAM help link |
| Bedrock model not enabled | Show error + link to Bedrock console to enable model access |
| Config file unwritable | Abort with path + permissions hint |

---

## `ensure_configured()` behavior

```python
def ensure_configured():
    cfg = load_config()
    if not cfg.get("bedrock_model_id") or not cfg.get("aws_region"):
        console.print("[bold yellow]Welcome to replicant![/] Let's get you set up first.\n")
        run_wizard()
```

Called at the top of `setup`, `shell`, `list`, `info`, `delete`, `validate` — any command that needs a working LLM or cloud config. Not called for `replicant init` itself (which runs the wizard directly).

---

## Testing

- `test_onboarding.py`: mock boto3, mock subprocess for Terraform install, mock `check_docker()`
- Test `ensure_configured()` skips wizard when config is complete
- Test `ensure_configured()` triggers wizard when config is missing
- Test each Terraform install path (brew, apt, fallback) with mocked subprocess
- Test `load_config()` / `save_config()` round-trip
- No network calls in tests

---

## Files Changed

| File | Change |
|------|--------|
| `replicant/utils/onboarding.py` | **New** — wizard, load/save config, ensure_configured |
| `replicant/utils/llm_config.py` | Remove bearer token, read from config file |
| `replicant/cli.py` | Add `ensure_configured()` calls, `replicant init` command |
| `replicant/providers/aws.py` | `_prompt_iam_credentials()` stays here; onboarding.py imports and calls it |
| `tests/test_onboarding.py` | **New** |
| `README.md` | Update setup section to `pip install replicant` + first-run instructions |
