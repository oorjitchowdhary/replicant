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


def _step_terraform() -> bool:
    """Wizard step 2: ensure Terraform is installed. Returns True if available (or installed)."""
    from replicant.providers.aws import _find_terraform
    try:
        _find_terraform()
        _con.print("  [green]✔[/] Terraform ready")
        return True
    except RuntimeError as e:
        _con.print(
            f"  [yellow]⚠[/] {e}\n"
            "    Cloud execution will be unavailable until Terraform is installed."
        )
        return False


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
                region = click.prompt("  AWS region", default=region)
                return region, session.profile_name
        except (botocore.exceptions.NoCredentialsError, botocore.exceptions.ClientError):
            pass

    _con.print("  [yellow]![/] No valid AWS credentials found — launching setup…")
    region = click.prompt("  AWS region (must match where Bedrock is enabled)", default=default_region)
    from replicant.providers.aws import _prompt_iam_credentials
    _prompt_iam_credentials(region)
    return region, None


_MODELS = [
    ("claude-sonnet-4-6",     "us.anthropic.claude-sonnet-4-6",   "Anthropic — latest Sonnet, recommended"),
    ("claude-opus-4-7",       "us.anthropic.claude-opus-4-7",     "Anthropic — most capable"),
    ("gpt-oss-120b",          "openai.gpt-oss-120b-1:0",          "OpenAI — GPT 120B"),
    ("qwen3-coder-next",      "qwen.qwen3-coder-next",             "Qwen — latest coder model"),
]


def _step_model_select() -> str:
    """Wizard step 4: pick a Bedrock model. Returns the full model ID."""
    import click
    _con.print(
        "\n  Browse all available models: "
        "[link=https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html]"
        "https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards.html[/link]"
    )
    _con.print("  Featured models:")
    for i, (name, _, desc) in enumerate(_MODELS, 1):
        _con.print(f"    {i}. {name}  ({desc})")
    _con.print("    or enter any Bedrock model ID directly")
    choice = click.prompt("  Select model", default="1")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(_MODELS):
            model_id = _MODELS[idx][1]
            _con.print(f"  [green]✔[/] Selected {_MODELS[idx][0]}")
            return model_id
    except ValueError:
        # Treat non-integer input as a raw model ID
        if choice.strip():
            _con.print(f"  [green]✔[/] Using model: {choice.strip()}")
            return choice.strip()
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
