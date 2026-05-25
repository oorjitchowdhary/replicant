# Onboarding & Generic Bedrock Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace UW-specific `AWS_BEARER_TOKEN_BEDROCK` with standard boto3 credentials and add a first-run wizard that auto-installs Terraform, sets up AWS credentials, picks a Bedrock model, and writes `~/.replicant/config.json`.

**Architecture:** New `replicant/utils/onboarding.py` owns all wizard logic and config I/O. `llm_config.py` is simplified to read from the config file. Every CLI command calls `ensure_configured()` at the top, which runs the wizard automatically if config is absent.

**Tech Stack:** Python stdlib (`json`, `shutil`, `subprocess`, `platform`), `boto3`, `rich`, `click`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `replicant/utils/onboarding.py` | **Create** | `load_config`, `save_config`, `ensure_configured`, `run_wizard`, `_step_docker`, `_step_terraform`, `_step_aws_credentials`, `_step_model_select`, `_step_test_bedrock` |
| `replicant/utils/llm_config.py` | **Modify** | Remove bearer token, read model+region from config file, expose `test_bedrock_connection` |
| `replicant/cli.py` | **Modify** | Call `ensure_configured()` in each command, add `replicant init` command, update `llm-config` command |
| `tests/test_onboarding.py` | **Create** | Unit tests for all onboarding functions |

---

## Task 1: Config file utilities

**Files:**
- Create: `replicant/utils/onboarding.py`
- Create: `tests/test_onboarding.py`

- [ ] **Step 1: Write failing tests for load_config and save_config**

```python
# tests/test_onboarding.py
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from replicant.utils.onboarding import load_config, save_config

def test_load_config_returns_empty_dict_when_missing(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        assert load_config() == {}

def test_load_config_returns_dict_when_present(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"aws_region": "us-east-1", "bedrock_model_id": "my-model"}))
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        cfg = load_config()
    assert cfg["aws_region"] == "us-east-1"
    assert cfg["bedrock_model_id"] == "my-model"

def test_save_config_writes_json(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        save_config({"aws_region": "eu-west-1", "bedrock_model_id": "m"})
    data = json.loads(cfg_path.read_text())
    assert data["aws_region"] == "eu-west-1"

def test_save_config_creates_parent_dir(tmp_path):
    cfg_path = tmp_path / "nested" / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path):
        save_config({"bedrock_model_id": "x", "aws_region": "us-east-1"})
    assert cfg_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/oorjitchowdhary/Code/replicant
python -m pytest tests/test_onboarding.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` or `ImportError` (file doesn't exist yet)

- [ ] **Step 3: Create onboarding.py with config utilities**

```python
# replicant/utils/onboarding.py
"""First-run onboarding wizard and config file management."""
from __future__ import annotations
import json
from pathlib import Path

from rich.console import Console

_CONFIG_PATH = Path.home() / ".replicant" / "config.json"
_con = Console()


def load_config() -> dict:
    """Load ~/.replicant/config.json. Returns {} if missing or malformed."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    """Write cfg to ~/.replicant/config.json atomically."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_onboarding.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add replicant/utils/onboarding.py tests/test_onboarding.py
git commit -m "feat: add onboarding config load/save utilities"
```

---

## Task 2: Update llm_config.py to read from config file

**Files:**
- Modify: `replicant/utils/llm_config.py`

- [ ] **Step 1: Write failing test for test_bedrock_connection**

Add to `tests/test_onboarding.py`:

```python
from unittest.mock import MagicMock, patch
from replicant.utils.llm_config import test_bedrock_connection, get_bedrock_client

def test_bedrock_connection_returns_true_on_success():
    mock_client = MagicMock()
    mock_client.converse.return_value = {
        "output": {"message": {"content": [{"text": "hi"}]}}
    }
    with patch("replicant.utils.llm_config.get_bedrock_client", return_value=mock_client):
        ok, msg = test_bedrock_connection("us.anthropic.claude-sonnet-4-6", "us-east-1", None)
    assert ok is True
    assert "success" in msg.lower()

def test_bedrock_connection_returns_false_on_exception():
    mock_client = MagicMock()
    mock_client.converse.side_effect = Exception("no access")
    with patch("replicant.utils.llm_config.get_bedrock_client", return_value=mock_client):
        ok, msg = test_bedrock_connection("my-model", "us-east-1", None)
    assert ok is False
    assert "no access" in msg

def test_get_bedrock_client_uses_config_region(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"aws_region": "ap-southeast-1", "bedrock_model_id": "m"}))
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path), \
         patch("boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        get_bedrock_client()
    call_kwargs = mock_boto.call_args[1]
    assert call_kwargs["region_name"] == "ap-southeast-1"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_onboarding.py::test_bedrock_connection_returns_true_on_success -v
```
Expected: `ImportError: cannot import name 'test_bedrock_connection'`

- [ ] **Step 3: Rewrite llm_config.py**

Replace the entire file:

```python
"""LLM configuration utilities."""
from __future__ import annotations
import os


def _cfg() -> dict:
    from replicant.utils.onboarding import load_config
    return load_config()


def get_bedrock_client(model_id: str | None = None, region: str | None = None, profile: str | None = None):
    """Return a boto3 bedrock-runtime client."""
    import boto3
    from botocore.config import Config
    cfg = _cfg()
    resolved_region = region or cfg.get("aws_region") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    resolved_profile = profile or cfg.get("aws_profile")
    session = boto3.Session(profile_name=resolved_profile) if resolved_profile else boto3.Session()
    return session.client(
        "bedrock-runtime",
        region_name=resolved_region,
        config=Config(read_timeout=300, connect_timeout=10),
    )


def get_model_id() -> str:
    """Return the configured Bedrock model ID."""
    cfg = _cfg()
    return cfg.get("bedrock_model_id") or os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6-20251001-v2:0")


def get_region() -> str:
    cfg = _cfg()
    return cfg.get("aws_region") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")


def test_bedrock_connection(model_id: str, region: str, profile: str | None) -> tuple[bool, str]:
    """Fire a minimal converse() call. Returns (success, message)."""
    try:
        client = get_bedrock_client(model_id=model_id, region=region, profile=profile)
        client.converse(
            modelId=model_id,
            inferenceConfig={"maxTokens": 16},
            messages=[{"role": "user", "content": [{"text": "Hi"}]}],
        )
        return True, f"Bedrock connection successful (model: {model_id})"
    except Exception as e:
        return False, f"Bedrock test failed: {e}"


# Backward-compat aliases used by analyzers/dependencies.py and analyzers/paper.py
BEDROCK_MODEL_ID: str = get_model_id()
AWS_REGION: str = get_region()


def check_bedrock_setup() -> tuple[bool, str]:
    """Legacy check — now delegates to test_bedrock_connection with config values."""
    cfg = _cfg()
    model = cfg.get("bedrock_model_id") or os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6-20251001-v2:0")
    region = cfg.get("aws_region") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    profile = cfg.get("aws_profile")
    if not model:
        return False, "No Bedrock model configured. Run: replicant init"
    return test_bedrock_connection(model, region, profile)


def get_config_instructions() -> str:
    return "Run `replicant init` to configure replicant."
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_onboarding.py -v
```
Expected: all pass

- [ ] **Step 5: Run full test suite to check nothing broke**

```bash
python -m pytest --tb=short -q
```
Expected: same pass/fail count as before (143 pass, 2 known failures in test_paper.py)

- [ ] **Step 6: Commit**

```bash
git add replicant/utils/llm_config.py tests/test_onboarding.py
git commit -m "feat: update llm_config to read from config file, add test_bedrock_connection"
```

---

## Task 3: Terraform auto-install step

**Files:**
- Modify: `replicant/utils/onboarding.py`
- Modify: `tests/test_onboarding.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_onboarding.py`:

```python
import shutil
from replicant.utils.onboarding import _install_terraform, _step_terraform

def test_step_terraform_skips_when_already_installed():
    with patch("shutil.which", return_value="/usr/local/bin/terraform"):
        result = _step_terraform()
    assert result is True

def test_install_terraform_tries_brew_on_macos():
    with patch("platform.system", return_value="Darwin"), \
         patch("shutil.which", side_effect=lambda x: "/usr/bin/brew" if x == "brew" else None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        ok = _install_terraform()
    assert ok is True
    cmds = [" ".join(c.args) for c in mock_run.call_args_list]
    assert any("brew" in c for c in cmds)

def test_install_terraform_returns_false_when_all_fail():
    with patch("platform.system", return_value="Darwin"), \
         patch("shutil.which", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        ok = _install_terraform()
    assert ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_onboarding.py::test_step_terraform_skips_when_already_installed -v
```
Expected: `ImportError: cannot import name '_step_terraform'`

- [ ] **Step 3: Add terraform step to onboarding.py**

Add after the `save_config` function:

```python
import platform
import shutil
import subprocess


def _install_terraform() -> bool:
    """Try to install terraform. Returns True on success."""
    from rich.progress import Progress, SpinnerColumn, TextColumn

    system = platform.system()

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=_con, transient=True) as p:
        p.add_task("Installing Terraform…")

        # macOS — brew
        if system == "Darwin" and shutil.which("brew"):
            r = subprocess.run(
                ["brew", "tap", "hashicorp/tap"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                r2 = subprocess.run(
                    ["brew", "install", "hashicorp/tap/terraform"],
                    capture_output=True, text=True,
                )
                if r2.returncode == 0 and shutil.which("terraform"):
                    return True
            _con.print(f"    [dim]brew install failed: {r.stderr.strip() or r2.stderr.strip()}[/]")

        # Linux — apt
        if system == "Linux" and shutil.which("apt-get"):
            cmds = [
                ["bash", "-c",
                 "wget -O- https://apt.releases.hashicorp.com/gpg | "
                 "sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg"],
                ["bash", "-c",
                 'echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] '
                 'https://apt.releases.hashicorp.com $(lsb_release -cs) main" | '
                 "sudo tee /etc/apt/sources.list.d/hashicorp.list"],
                ["sudo", "apt-get", "update", "-qq"],
                ["sudo", "apt-get", "install", "-y", "terraform"],
            ]
            success = all(subprocess.run(c, capture_output=True).returncode == 0 for c in cmds)
            if success and shutil.which("terraform"):
                return True

        # Fallback — download binary to ~/.local/bin
        try:
            import urllib.request, zipfile, io, tempfile, stat
            arch = "amd64" if platform.machine() in ("x86_64", "AMD64") else "arm64"
            version = "1.9.8"
            url = f"https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{system.lower()}_{arch}.zip"
            local_bin = Path.home() / ".local" / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=60) as resp:
                z = zipfile.ZipFile(io.BytesIO(resp.read()))
                z.extract("terraform", local_bin)
            tf_path = local_bin / "terraform"
            tf_path.chmod(tf_path.stat().st_mode | stat.S_IEXEC)
            # Add to PATH for this session
            os.environ["PATH"] = str(local_bin) + os.pathsep + os.environ.get("PATH", "")
            # Append to shell rc
            for rc in [Path.home() / ".bashrc", Path.home() / ".zshrc"]:
                if rc.exists():
                    line = f'\nexport PATH="$HOME/.local/bin:$PATH"\n'
                    if line.strip() not in rc.read_text():
                        with rc.open("a") as f:
                            f.write(line)
            return shutil.which("terraform") is not None
        except Exception as e:
            _con.print(f"    [dim]fallback install failed: {e}[/]")
            return False


def _step_terraform() -> bool:
    """Wizard step 2: ensure Terraform is installed. Returns True if available (or installed)."""
    if shutil.which("terraform"):
        _con.print("  [green]✔[/] Terraform already installed")
        return True
    _con.print("  [yellow]![/] Terraform not found — attempting install…")
    if _install_terraform():
        _con.print("  [green]✔[/] Terraform installed")
        return True
    _con.print(
        "  [yellow]⚠[/] Could not install Terraform automatically.\n"
        "    Install manually: https://developer.hashicorp.com/terraform/install\n"
        "    Cloud execution will be unavailable until Terraform is installed."
    )
    return False
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_onboarding.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add replicant/utils/onboarding.py tests/test_onboarding.py
git commit -m "feat: add terraform auto-install step to onboarding wizard"
```

---

## Task 4: AWS credentials step

**Files:**
- Modify: `replicant/utils/onboarding.py`
- Modify: `tests/test_onboarding.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_onboarding.py`:

```python
from replicant.utils.onboarding import _step_aws_credentials

def test_step_aws_credentials_returns_region_when_creds_valid():
    mock_session = MagicMock()
    mock_session.get_credentials.return_value = MagicMock()
    mock_session.client.return_value.get_caller_identity.return_value = {}
    mock_session.region_name = "us-east-1"
    with patch("boto3.Session", return_value=mock_session):
        region, profile = _step_aws_credentials(default_region="us-east-1")
    assert region == "us-east-1"

def test_step_aws_credentials_prompts_when_no_creds():
    import botocore.exceptions
    mock_session = MagicMock()
    mock_session.get_credentials.return_value = None
    with patch("boto3.Session", return_value=mock_session), \
         patch("replicant.providers.aws._prompt_iam_credentials") as mock_prompt, \
         patch("click.prompt", return_value="us-east-1"):
        mock_prompt.return_value = None
        # Should call _prompt_iam_credentials
        _step_aws_credentials(default_region="us-east-1")
    mock_prompt.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_onboarding.py::test_step_aws_credentials_returns_region_when_creds_valid -v
```
Expected: `ImportError: cannot import name '_step_aws_credentials'`

- [ ] **Step 3: Add credentials step to onboarding.py**

Add after `_step_terraform`:

```python
def _step_aws_credentials(default_region: str = "us-east-1") -> tuple[str, str | None]:
    """
    Wizard step 3: verify AWS credentials are present and working.
    Returns (region, profile_name_or_None).
    """
    import boto3
    import botocore.exceptions
    import click

    session = boto3.Session()
    creds = session.get_credentials()
    region = session.region_name or default_region
    profile = None

    if creds:
        try:
            session.client("sts", region_name=region).get_caller_identity()
            _con.print(f"  [green]✔[/] AWS credentials found (region: {region})")
            confirm = click.confirm("  Use these credentials?", default=True)
            if confirm:
                # Let user override region
                region = click.prompt("  AWS region", default=region)
                return region, session.profile_name
        except (botocore.exceptions.NoCredentialsError, botocore.exceptions.ClientError):
            pass

    _con.print("  [yellow]![/] No valid AWS credentials found — launching setup…")
    region = click.prompt("  AWS region (must match where Bedrock is enabled)", default=default_region)
    from replicant.providers.aws import _prompt_iam_credentials
    _prompt_iam_credentials(region)
    return region, None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_onboarding.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add replicant/utils/onboarding.py tests/test_onboarding.py
git commit -m "feat: add aws credentials step to onboarding wizard"
```

---

## Task 5: Model selection + full run_wizard + ensure_configured

**Files:**
- Modify: `replicant/utils/onboarding.py`
- Modify: `tests/test_onboarding.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_onboarding.py`:

```python
from replicant.utils.onboarding import _step_model_select, run_wizard, ensure_configured

_MODELS = [
    "us.anthropic.claude-sonnet-4-6-20251001-v2:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.anthropic.claude-sonnet-3-5-20241022-v2:0",
    "us.anthropic.claude-opus-4-7-20250514-v1:0",
]

def test_step_model_select_returns_first_on_default(monkeypatch):
    monkeypatch.setattr("click.prompt", lambda *a, **kw: "1")
    model = _step_model_select()
    assert model == _MODELS[0]

def test_step_model_select_returns_chosen_model(monkeypatch):
    monkeypatch.setattr("click.prompt", lambda *a, **kw: "2")
    model = _step_model_select()
    assert model == _MODELS[1]

def test_ensure_configured_skips_when_config_complete(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "aws_region": "us-east-1",
        "bedrock_model_id": "some-model",
    }))
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path), \
         patch("replicant.utils.onboarding.run_wizard") as mock_wizard:
        ensure_configured()
    mock_wizard.assert_not_called()

def test_ensure_configured_runs_wizard_when_config_missing(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path), \
         patch("replicant.utils.onboarding.run_wizard") as mock_wizard:
        ensure_configured()
    mock_wizard.assert_called_once()

def test_run_wizard_writes_config(tmp_path):
    cfg_path = tmp_path / "config.json"
    with patch("replicant.utils.onboarding._CONFIG_PATH", cfg_path), \
         patch("replicant.utils.onboarding._step_docker", return_value=True), \
         patch("replicant.utils.onboarding._step_terraform", return_value=True), \
         patch("replicant.utils.onboarding._step_aws_credentials", return_value=("us-east-1", None)), \
         patch("replicant.utils.onboarding._step_model_select", return_value="my-model"), \
         patch("replicant.utils.onboarding._step_test_bedrock", return_value=True):
        run_wizard()
    cfg = json.loads(cfg_path.read_text())
    assert cfg["bedrock_model_id"] == "my-model"
    assert cfg["aws_region"] == "us-east-1"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_onboarding.py::test_ensure_configured_skips_when_config_complete -v
```
Expected: `ImportError`

- [ ] **Step 3: Add model select, test bedrock step, run_wizard, ensure_configured to onboarding.py**

Append to `replicant/utils/onboarding.py`:

```python
_MODELS = [
    ("claude-sonnet-4-6", "us.anthropic.claude-sonnet-4-6-20251001-v2:0", "recommended — best quality"),
    ("claude-haiku-4-5",  "us.anthropic.claude-haiku-4-5-20251001-v1:0",  "fastest, cheapest"),
    ("claude-sonnet-3-5", "us.anthropic.claude-sonnet-3-5-20241022-v2:0", "widely available"),
    ("claude-opus-4-7",   "us.anthropic.claude-opus-4-7-20250514-v1:0",   "most capable, slower"),
]


def _step_model_select() -> str:
    """Wizard step 4: pick a Bedrock model. Returns the full model ID."""
    import click
    _con.print("\n  Available Bedrock models:")
    for i, (name, _, desc) in enumerate(_MODELS, 1):
        _con.print(f"    {i}. {name}  ({desc})")
    choice = click.prompt("  Select model", default="1")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(_MODELS):
            model_id = _MODELS[idx][1]
            _con.print(f"  [green]✔[/] Selected {_MODELS[idx][0]}")
            return model_id
    except ValueError:
        pass
    _con.print("  Invalid choice — using default")
    return _MODELS[0][1]


def _step_docker() -> bool:
    """Wizard step 1: verify Docker is running."""
    try:
        from replicant.executors.local import check_docker
        check_docker()
        _con.print("  [green]✔[/] Docker is running")
        return True
    except RuntimeError as e:
        _con.print(f"  [red]✗[/] Docker: {e}")
        return False


def _step_test_bedrock(model_id: str, region: str, profile: str | None) -> bool:
    """Wizard step 5: test Bedrock connection. Returns True on success."""
    from replicant.utils.llm_config import test_bedrock_connection
    _con.print("  Testing Bedrock connection…", end=" ")
    ok, msg = test_bedrock_connection(model_id, region, profile)
    if ok:
        _con.print("[green]✔[/]")
    else:
        _con.print(f"[red]✗[/] {msg}")
    return ok


def run_wizard(reset: bool = False) -> None:
    """Run the 5-step onboarding wizard. Writes ~/.replicant/config.json on success."""
    if reset:
        save_config({})

    _con.print("\n[bold]replicant setup[/] — let's get you configured.\n")

    # Step 1: Docker
    _con.print("[bold][1/5][/] Checking Docker…")
    if not _step_docker():
        _con.print("\n[red]Docker is required. Fix the issue above and re-run.[/]")
        raise SystemExit(1)

    # Step 2: Terraform
    _con.print("[bold][2/5][/] Checking Terraform…")
    _step_terraform()  # non-fatal

    # Step 3: AWS credentials
    _con.print("[bold][3/5][/] AWS credentials…")
    region, profile = _step_aws_credentials()

    # Step 4: Model selection
    _con.print("[bold][4/5][/] Bedrock model…")
    model_id = _step_model_select()

    # Step 5: Test connection (retry once on failure)
    _con.print("[bold][5/5][/] Testing Bedrock access…")
    ok = _step_test_bedrock(model_id, region, profile)
    if not ok:
        _con.print("  Retrying credentials…")
        region, profile = _step_aws_credentials(default_region=region)
        ok = _step_test_bedrock(model_id, region, profile)
        if not ok:
            _con.print(
                "\n[red]Could not connect to Bedrock.[/]\n"
                "Check your IAM permissions and that the model is enabled in the AWS console:\n"
                "https://console.aws.amazon.com/bedrock/home#/models"
            )
            raise SystemExit(1)

    cfg: dict = {"aws_region": region, "bedrock_model_id": model_id}
    if profile:
        cfg["aws_profile"] = profile
    save_config(cfg)
    _con.print(f"\n[green bold]✔ Config saved to {_CONFIG_PATH}[/]")


def ensure_configured() -> None:
    """Run the wizard if config is missing or incomplete."""
    cfg = load_config()
    if cfg.get("bedrock_model_id") and cfg.get("aws_region"):
        return
    _con.print("[bold yellow]Welcome to replicant![/] Let's get you set up first.\n")
    run_wizard()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_onboarding.py -v
```
Expected: all pass

- [ ] **Step 5: Run full suite**

```bash
python -m pytest --tb=short -q
```
Expected: same pass count as before

- [ ] **Step 6: Commit**

```bash
git add replicant/utils/onboarding.py tests/test_onboarding.py
git commit -m "feat: add model selection, run_wizard, and ensure_configured"
```

---

## Task 6: Wire ensure_configured into CLI + add replicant init command

**Files:**
- Modify: `replicant/cli.py`

- [ ] **Step 1: Remove bearer token check and add ensure_configured calls**

In `replicant/cli.py`, remove these lines from the `setup` command (around line 45-52):

```python
    # Check for Bedrock bearer token
    if not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        _abort(
            "AWS_BEARER_TOKEN_BEDROCK is required.\n"
            "Set it with: export AWS_BEARER_TOKEN_BEDROCK=your_token\n"
            "Or run: replicant llm-config for help"
        )
```

Replace with:

```python
    from replicant.utils.onboarding import ensure_configured
    ensure_configured()
```

Apply the same pattern to the `shell` command — add `ensure_configured()` as the first line after the docstring.

- [ ] **Step 2: Add `replicant init` command**

Add before `@main.command()` for the existing `llm_config` command:

```python
@main.command("init")
@click.option("--reset", is_flag=True, help="Wipe existing config and re-run wizard.")
def init_cmd(reset):
    """Run the first-time setup wizard."""
    from replicant.utils.onboarding import run_wizard
    run_wizard(reset=reset)
```

- [ ] **Step 3: Update llm-config command**

Find the existing `llm_config` command in `cli.py` and replace its body with:

```python
@main.command("llm-config")
def llm_config():
    """Show current Bedrock config and test the connection."""
    from replicant.utils.onboarding import load_config
    from replicant.utils.llm_config import test_bedrock_connection
    cfg = load_config()
    if not cfg:
        con.print("[yellow]No config found.[/] Run [bold]replicant init[/] to set up.")
        return
    con.print(f"  Region:   {cfg.get('aws_region', 'not set')}")
    con.print(f"  Model:    {cfg.get('bedrock_model_id', 'not set')}")
    con.print(f"  Profile:  {cfg.get('aws_profile', 'default')}")
    ok, msg = test_bedrock_connection(
        cfg.get("bedrock_model_id", ""),
        cfg.get("aws_region", "us-east-1"),
        cfg.get("aws_profile"),
    )
    if ok:
        con.print(f"  [green]✔[/] {msg}")
    else:
        con.print(f"  [red]✗[/] {msg}")
```

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest --tb=short -q
```
Expected: same pass count as before

- [ ] **Step 5: Smoke test the CLI**

```bash
replicant --help
replicant init --help
replicant llm-config
```
Expected: help text shows `init` command, `llm-config` prints current config

- [ ] **Step 6: Commit**

```bash
git add replicant/cli.py
git commit -m "feat: wire ensure_configured into CLI, add replicant init command"
```

---

## Task 7: Remove os import of bearer token + final cleanup

**Files:**
- Modify: `replicant/cli.py`
- Modify: `replicant/utils/llm_config.py`

- [ ] **Step 1: Remove `os` import from cli.py if no longer needed**

Check if `os` is still used in `cli.py`:

```bash
grep -n "os\." /Users/oorjitchowdhary/Code/replicant/replicant/cli.py
```

If `os` is only used for the removed bearer token check, remove the `import os` line.

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest --tb=short -q
```
Expected: 143 pass, 2 known failures in test_paper.py

- [ ] **Step 3: Commit and push**

```bash
git add replicant/cli.py replicant/utils/llm_config.py
git commit -m "chore: remove AWS_BEARER_TOKEN_BEDROCK, clean up unused imports"
git push
```
