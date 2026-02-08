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
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

try:
    import google.genai as genai
except ImportError:
    raise ImportError("google-genai is required. Install with: pip install google-genai")


class DependencySpec(BaseModel):
    """A single dependency with version constraints and reasoning."""
    package: str = Field(description="The pip package name")
    version_spec: str = Field(description="Version specifier (e.g., '==1.15.0', '>=2.0,<3.0', '~=1.4.0')")
    reason: str = Field(description="Brief explanation of why this version constraint was chosen")
    is_critical: bool = Field(default=False, description="True if this is a core framework dependency")


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
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY required for dependency resolution")
    
    client = genai.Client(api_key=api_key)
    
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
    
    response = client.models.generate_content(
        model='gemini-3-flash-preview',
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": ResolvedDependencies.model_json_schema(),
        }
    )
    
    try:
        return ResolvedDependencies.model_validate_json(response.text)
    except Exception as e:
        raise ValueError(f"Failed to parse dependency resolution: {e}\nResponse: {response.text[:500]}")


def _build_dependency_prompt(
    existing_requirements: str,
    existing_env_yml: str,
    setup_py_content: str,
    code_samples: str,
    readme_content: str,
    repo_year: int,
) -> str:
    """Build the comprehensive prompt for dependency resolution."""
    
    return f"""You are an expert Python dependency resolver. Your job is to analyze this repository and produce WORKING dependency specifications that will install and run without errors.

## YOUR CRITICAL MISSION
Users of this tool should NEVER encounter dependency hell. You must:
1. Analyze the actual code to understand what framework versions are needed
2. Detect API patterns that indicate specific version requirements
3. Pin versions precisely enough to ensure compatibility
4. Anticipate and prevent common conflicts

## FRAMEWORK API KNOWLEDGE YOU MUST APPLY

### TensorFlow Version Detection
- `tf.train.Optimizer`, `tf.Session`, `tf.placeholder`, `tf.get_variable`, `tf.contrib` → TensorFlow 1.x (use tensorflow==1.15.0)
- These APIs were REMOVED in TensorFlow 2.0 and WILL crash if you install TF 2.x
- `tf.keras`, `@tf.function`, `tf.GradientTape` → TensorFlow 2.x compatible
- If code uses TF 1.x APIs, you MUST pin to tensorflow==1.15.0 (the last 1.x version)

### PyTorch Version Detection  
- `torch.cuda.amp` → PyTorch >= 1.6
- `torch.nn.TransformerEncoder` → PyTorch >= 1.2
- Old-style `Variable` wrapping → PyTorch < 0.4
- `torch.compile` → PyTorch >= 2.0

### Other Common Issues
- numpy>=2.0 breaks many older packages - pin to numpy<2.0 for pre-2024 repos
- scipy and numpy version compatibility matters
- transformers library versions must match model compatibility
- CUDA toolkit version must match PyTorch/TensorFlow builds

## REPOSITORY INFORMATION

### Repository Year/Era: {repo_year}
This tells you approximately when the code was written. Use this to inform version choices.

### Existing requirements.txt:
```
{existing_requirements if existing_requirements else "Not present"}
```

### Existing environment.yml:
```
{existing_env_yml if existing_env_yml else "Not present"}
```

### setup.py / pyproject.toml:
```
{setup_py_content if setup_py_content else "Not present"}
```

### Code Samples (showing actual framework usage):
```python
{code_samples if code_samples else "No code samples provided"}
```

### README Setup Instructions:
```
{readme_content[:3000] if readme_content else "Not present"}
```

## YOUR TASK

Analyze all the information above and produce a ResolvedDependencies object that:

1. **python_version**: Choose the right Python version
   - TensorFlow 1.x works best with Python 3.7
   - Very old repos may need Python 3.6
   - Most modern repos work with Python 3.10
   - Consider framework compatibility

2. **dependencies**: For EACH dependency:
   - **package**: Exact pip package name
   - **version_spec**: Precise version constraint that WILL work
   - **reason**: Brief explanation (e.g., "Code uses tf.Session which requires TF 1.x")
   - **is_critical**: True for core frameworks (tensorflow, torch, jax)

3. **compatibility_notes**: Any important warnings or notes

4. **install_order_matters**: True if order matters (rare)

5. **install_commands**: Special commands if needed

## CRITICAL RULES

1. NEVER leave core frameworks unpinned - tensorflow, torch, jax MUST have specific versions
2. If you see TensorFlow 1.x API patterns, pin to tensorflow==1.15.0 with Python 3.7
3. If requirements.txt says just "tensorflow" but code uses TF 1.x APIs, OVERRIDE it with the correct version
4. For TensorFlow 1.x projects: use RANGE constraints for non-TF packages (e.g., numpy>=1.16,<1.19 instead of numpy==1.18.5)
   - The official tensorflow/tensorflow:1.15.0-py3 Docker image uses Python 3.6, so exact pins may not be available
   - Use flexible ranges that will resolve in older Python environments
5. When in doubt about version, pin conservatively to known-working versions
6. Include transitive dependencies that commonly cause issues (numpy, scipy, protobuf)
7. For repos from 2018-2020, assume they need older package versions
8. For protobuf with TF 1.x, use protobuf>=3.8,<4.0 (not exact pins)

## OUTPUT

Return a complete ResolvedDependencies JSON object. Every framework dependency MUST have a specific version pin. The user should be able to pip install these and have the code JUST WORK."""


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


def extract_code_samples(repo_path: Path, max_chars: int = 30000) -> str:
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
