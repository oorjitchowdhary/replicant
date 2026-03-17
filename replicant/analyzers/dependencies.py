"""AI-powered dependency resolution that prevents dependency hell.

This module uses LLM intelligence to deeply analyze repository code and produce
bulletproof, version-pinned dependency specifications that just work.

The LLM understands:
- Framework API evolution (what was removed/added across versions)
- Common compatibility issues and how to avoid them
- Transitive dependency conflicts
- The era/vintage of code based on API patterns
- Best practices for pinning versions

This is the core intelligence that makes replicant "just work" - users should
never encounter dependency hell because the AI proactively solves it.
"""
from __future__ import annotations
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

try:
    import boto3
except ImportError:
    raise ImportError("boto3 is required. Install with: pip install boto3")

from replicant.utils.llm_config import BEDROCK_MODEL_ID, get_bedrock_client


class DependencySpec(BaseModel):
    """A single dependency with version constraints and reasoning."""
    package: str = Field(description="The pip package name")
    version_spec: str = Field(description="Version specifier (e.g., '==1.15.0', '>=2.0,<3.0', '~=1.4.0')")
    reason: str = Field(default="", description="Brief explanation of why this version constraint was chosen")
    is_critical: bool = Field(default=False, description="True if this is a core framework dependency")

    @field_validator("reason")
    @classmethod
    def truncate_reason(cls, v: str) -> str:
        return v[:100] if v else ""


class ResolvedDependencies(BaseModel):
    """Complete resolved dependency specification for a repository."""
    python_version: str = Field(description="Recommended Python version (e.g., '3.8', '3.10')")
    python_reason: str = Field(description="Why this Python version was chosen")
    dependencies: List[DependencySpec] = Field(default_factory=list, description="All resolved dependencies with versions")
    compatibility_notes: List[str] = Field(default_factory=list, description="Important compatibility notes or warnings")
    install_order_matters: bool = Field(default=False, description="True if packages must be installed in specific order")
    install_commands: List[str] = Field(default_factory=list, description="Special install commands if needed (e.g., for CUDA)")


def resolve_dependencies(
    repo_path: Path,
    existing_requirements: str = "",
    existing_env_yml: str = "",
    setup_py_content: str = "",
    code_samples: str = "",
    readme_content: str = "",
    repo_created_year: Optional[int] = None,
) -> ResolvedDependencies:
    """Use LLM to analyze repository and produce working dependency specifications.
    
    This is the core function that prevents dependency hell by:
    1. Understanding the era of the code
    2. Detecting framework API patterns that indicate version requirements
    3. Resolving conflicts between declared and actual requirements
    4. Producing bulletproof version pins that will actually work
    
    Args:
        repo_path: Path to the repository
        existing_requirements: Content of requirements.txt if present
        existing_env_yml: Content of environment.yml if present
        setup_py_content: Content of setup.py or pyproject.toml if present
        code_samples: Representative code snippets showing framework usage
        readme_content: README content with setup instructions
        repo_created_year: Year the repo was created/last updated
    
    Returns:
        ResolvedDependencies with all packages properly version-pinned
    """
    client = get_bedrock_client()
    
    # Get repo vintage if not provided
    if repo_created_year is None:
        repo_created_year = _get_repo_year(repo_path)
    
    prompt = _build_dependency_prompt(
        existing_requirements=existing_requirements,
        existing_env_yml=existing_env_yml,
        setup_py_content=setup_py_content,
        code_samples=code_samples,
        readme_content=readme_content,
        repo_year=repo_created_year,
    )
    
    schema = json.dumps(ResolvedDependencies.model_json_schema(), indent=2)
    full_prompt = (
        f"{prompt}\n\n"
        f"Respond with ONLY a valid JSON object matching this schema. "
        f"Keep ALL reason fields under 10 words. No markdown, no commentary.\n\n{schema}"
    )

    response = client.converse(
        modelId=BEDROCK_MODEL_ID,
        inferenceConfig={"maxTokens": 8192},
        messages=[{"role": "user", "content": [{"text": full_prompt}]}],
    )

    raw = response["output"]["message"]["content"][0]["text"].strip()
    # Strip optional markdown code fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return ResolvedDependencies.model_validate_json(raw)
    except Exception as e:
        recovered = _try_recover_truncated_json(raw)
        if recovered:
            return recovered
        raise ValueError(f"Failed to parse dependency resolution: {e}\nResponse: {raw[:500]}")


def _try_recover_truncated_json(raw: str) -> "ResolvedDependencies | None":
    """Attempt to recover a truncated JSON response by closing open structures."""
    for end_marker in ['}\n  ]', '}\n    ]', '}']:
        last_complete = raw.rfind(end_marker)
        if last_complete > 0:
            truncated = raw[:last_complete + len(end_marker)]
            open_brackets = truncated.count('[') - truncated.count(']')
            open_braces = truncated.count('{') - truncated.count('}')
            truncated += ']' * open_brackets + '}' * open_braces
            try:
                return ResolvedDependencies.model_validate_json(truncated)
            except Exception:
                continue
    return None


def _build_dependency_prompt(
    existing_requirements: str,
    existing_env_yml: str,
    setup_py_content: str,
    code_samples: str,
    readme_content: str,
    repo_year: int,
) -> str:
    """Build the comprehensive prompt for dependency resolution."""
    
    return f"""You are a Python dependency resolver. Analyze this repository and produce working, version-pinned dependency specifications.

GOALS:
1. Choose the correct Python version based on the code era and package requirements
2. Pin all packages to specific compatible versions
3. Anticipate common conflicts (numpy 2.0 breaking changes, protobuf version conflicts, etc.)
4. Respect existing version pins in requirements files — only override if they're clearly wrong

REPOSITORY INFORMATION:

Repository Year/Era: {repo_year}

Existing requirements.txt:
```
{existing_requirements if existing_requirements else "Not present"}
```

Existing environment.yml:
```
{existing_env_yml if existing_env_yml else "Not present"}
```

setup.py / pyproject.toml:
```
{setup_py_content if setup_py_content else "Not present"}
```

Code Samples:
```python
{code_samples if code_samples else "No code samples provided"}
```

README Setup Instructions:
```
{readme_content[:2000] if readme_content else "Not present"}
```

VERSION SELECTION RULES:
- If requirements.txt has pinned versions, keep them unless they conflict
- If versions are unpinned, choose versions from the repo's era (use repo_year)
- For Python version: check .python-version, runtime.txt, environment.yml first; infer from package compatibility otherwise
- numpy>=2.0 breaks many pre-2024 packages — pin numpy<2.0 for repos before 2024
- protobuf>=4.0 breaks many older packages — pin protobuf<4.0 for pre-2023 repos

COMMON FRAMEWORK NOTES (apply only if relevant):
- TensorFlow 1.x (tf.Session, tf.placeholder, tf.contrib) requires tensorflow==1.15.0 + Python 3.7
- PyTorch version must match torchvision and torchaudio versions
- JAX/Flax versions must be compatible with jaxlib
- CUDA-dependent packages (flash-attn, apex, cupy) often need special install commands"""


def _get_repo_year(repo_path: Path) -> int:
    """Determine the year/era of the repository."""
    try:
        # Try git log for last commit
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            timestamp = int(result.stdout.strip())
            return datetime.fromtimestamp(timestamp).year
    except Exception:
        pass
    
    # Fallback to file timestamps
    try:
        years = []
        for f in repo_path.rglob("*.py"):
            if f.is_file() and ".git" not in str(f):
                years.append(datetime.fromtimestamp(f.stat().st_mtime).year)
        if years:
            return max(years)
    except Exception:
        pass
    
    return 2022  # Conservative default


def extract_code_samples(repo_path: Path, max_chars: int = 15000) -> str:
    """Extract representative code samples that show framework usage patterns.
    
    Focuses on:
    - Import statements (show what's being used)
    - Framework API calls (show how it's being used)
    - Main training/inference scripts
    """
    samples = []
    total_chars = 0
    
    # Priority files to check
    priority_patterns = [
        "train*.py", "main*.py", "run*.py", "model*.py",
        "**/train*.py", "**/model*.py", "**/main*.py"
    ]
    
    seen_files = set()
    
    # Collect priority files first
    for pattern in priority_patterns:
        for f in repo_path.glob(pattern):
            if f.is_file() and str(f) not in seen_files:
                seen_files.add(str(f))
                try:
                    content = f.read_text(errors="ignore")
                    # Extract imports and key framework calls
                    extracted = _extract_key_patterns(content, str(f.relative_to(repo_path)))
                    if extracted:
                        samples.append(extracted)
                        total_chars += len(extracted)
                        if total_chars > max_chars:
                            break
                except Exception:
                    continue
        if total_chars > max_chars:
            break
    
    # Also check other Python files
    if total_chars < max_chars:
        for f in repo_path.rglob("*.py"):
            if str(f) not in seen_files and ".git" not in str(f):
                try:
                    content = f.read_text(errors="ignore")
                    extracted = _extract_key_patterns(content, str(f.relative_to(repo_path)))
                    if extracted:
                        samples.append(extracted)
                        total_chars += len(extracted)
                        if total_chars > max_chars:
                            break
                except Exception:
                    continue
    
    return "\n\n".join(samples)


def _extract_key_patterns(content: str, filename: str) -> str:
    """Extract imports and framework-specific API patterns from code."""
    lines = content.split("\n")
    key_lines = []
    
    # Patterns that indicate framework usage
    framework_patterns = [
        # Imports
        r"^import\s+",
        r"^from\s+\w+\s+import",
        # TensorFlow patterns
        r"tf\.",
        r"tensorflow\.",
        r"keras\.",
        # PyTorch patterns
        r"torch\.",
        r"nn\.",
        # JAX patterns
        r"jax\.",
        r"flax\.",
        # Other frameworks
        r"transformers\.",
        r"huggingface",
        r"sklearn\.",
        r"scipy\.",
        r"numpy\s+as\s+np",
        r"pandas\s+as\s+pd",
    ]
    
    import re
    combined_pattern = re.compile("|".join(framework_patterns), re.IGNORECASE)
    
    for i, line in enumerate(lines):
        if combined_pattern.search(line):
            # Include some context
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            for j in range(start, end):
                if lines[j].strip() and lines[j] not in key_lines:
                    key_lines.append(lines[j])
    
    if key_lines:
        return f"# === {filename} ===\n" + "\n".join(key_lines[:100])  # Limit per file
    return ""


def generate_requirements_txt(resolved: ResolvedDependencies) -> str:
    """Generate a requirements.txt from resolved dependencies."""
    lines = [
        "# Auto-generated by replicant AI dependency resolver",
        "# These versions have been specifically chosen for compatibility",
        "",
    ]
    
    # Critical dependencies first
    critical = [d for d in resolved.dependencies if d.is_critical]
    other = [d for d in resolved.dependencies if not d.is_critical]
    
    if critical:
        lines.append("# === Core Framework Dependencies ===")
        for dep in critical:
            lines.append(f"{dep.package}{dep.version_spec}  # {dep.reason}")
        lines.append("")
    
    if other:
        lines.append("# === Other Dependencies ===")
        for dep in other:
            lines.append(f"{dep.package}{dep.version_spec}  # {dep.reason}")
    
    if resolved.compatibility_notes:
        lines.append("")
        lines.append("# === Compatibility Notes ===")
        for note in resolved.compatibility_notes:
            lines.append(f"# {note}")
    
    return "\n".join(lines)
