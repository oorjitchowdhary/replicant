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
    return cfg.get("bedrock_model_id") or os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


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


test_bedrock_connection.__test__ = False  # noqa: F405


# Backward-compat aliases used by analyzers/dependencies.py and analyzers/paper.py
BEDROCK_MODEL_ID: str = get_model_id()
AWS_REGION: str = get_region()


def check_bedrock_setup() -> tuple[bool, str]:
    """Legacy check — now delegates to test_bedrock_connection with config values."""
    cfg = _cfg()
    model = cfg.get("bedrock_model_id") or os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    region = cfg.get("aws_region") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    profile = cfg.get("aws_profile")
    if not model:
        return False, "No Bedrock model configured. Run: replicant init"
    return test_bedrock_connection(model, region, profile)


def get_config_instructions() -> str:
    return "Run `replicant init` to configure replicant."
