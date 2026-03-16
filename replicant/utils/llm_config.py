"""LLM configuration utilities."""
from __future__ import annotations
import os


BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-west-2")


def get_bedrock_client():
    """Return a boto3 bedrock-runtime client with a generous read timeout."""
    import boto3
    from botocore.config import Config
    return boto3.client(
        "bedrock-runtime",
        region_name=AWS_REGION,
        config=Config(read_timeout=300, connect_timeout=10),
    )


def check_bedrock_setup() -> tuple[bool, str]:
    """Check if AWS Bedrock is properly configured.

    Returns:
        (is_configured, message)
    """
    if not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        return False, (
            "AWS_BEARER_TOKEN_BEDROCK environment variable is not set.\n"
            "Set it with: export AWS_BEARER_TOKEN_BEDROCK=your_token"
        )

    try:
        import boto3
    except ImportError:
        return False, "boto3 package not installed. Run: pip install boto3"

    try:
        client = get_bedrock_client()
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            inferenceConfig={"maxTokens": 16},
            messages=[{"role": "user", "content": [{"text": "Hi"}]}],
        )
        response["output"]["message"]["content"][0]["text"]
        return True, f"AWS Bedrock configured successfully (model: {BEDROCK_MODEL_ID}) - replicant is ready to use!"
    except Exception as e:
        return False, f"AWS Bedrock test failed: {e}"


def get_config_instructions() -> str:
    """Get instructions for configuring AWS Bedrock."""
    return f"""
Replicant: AI-Powered Research Environment Setup

Replicant uses Anthropic's Claude (via AWS Bedrock) to intelligently analyze
research papers and automatically create working environments. This provides:

• Smart GitHub repository detection
• Intelligent framework and library identification
• Advanced dataset recognition
• Context-aware hardware requirement extraction
• Intelligent download URL classification

Setup:
1. Set your Bedrock bearer token:
     export AWS_BEARER_TOKEN_BEDROCK=your_token

2. (Optional) Override defaults:
     export BEDROCK_MODEL_ID={BEDROCK_MODEL_ID}
     export AWS_DEFAULT_REGION={AWS_REGION}

3. Run replicant normally - it will use Claude via Bedrock automatically.

Without a valid AWS_BEARER_TOKEN_BEDROCK, replicant cannot function.
"""