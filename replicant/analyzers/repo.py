"""Analyze a repo (and optionally a paper PDF) to produce a full EnvironmentSpec.

Scans for: env files, packages, datasets to download, entrypoint scripts,
hardware hints (GPU/TPU/RAM), and python version.

Uses AI-powered dependency resolution to prevent dependency hell.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from replicant.analyzers.dependencies import ResolvedDependencies

# ── Patterns ────────────────────────────────────────────────────────────────

# Dataset URLs / loaders
_DATASET_PATTERNS = [
    # Direct download URLs in code
    re.compile(r"""(?:url|URL|path|download)\s*[:=]\s*['"]?(https?://\S+(?:\.tar\.gz|\.zip|\.h5|\.hdf5|\.csv|\.tsv|\.json|\.jsonl|\.parquet|\.pkl|\.pt|\.pth|\.bin|\.npz|\.npy|\.tfrecord))"""),
    # HuggingFace datasets
    re.compile(r"""load_dataset\s*\(\s*['"]([^'"]+)['"]"""),
    # torchvision / tensorflow datasets by class name
    re.compile(r"""(?:datasets|torchvision\.datasets)\.\s*(\w+)\s*\("""),
    # kaggle
    re.compile(r"""kaggle\s+(?:datasets\s+)?download\s+[^\n]+"""),
    # gdown / wget / curl in shell scripts or READMEs
    re.compile(r"""(?:gdown|wget|curl)\s+['"]?(https?://\S+)"""),
    # Google Drive links
    re.compile(r"""https://drive\.google\.com/\S+"""),
]

# Hardware hints
_GPU_HINTS = re.compile(r"""\bcuda\b|\.to\(['"]cuda['"]\)|torch\.device|nvidia|gpu|gpus|nccl|apex|--gpus""", re.I)
_TPU_HINTS = re.compile(r"""\btpu\b|xla|cloud_tpu""", re.I)
_LARGE_RAM = re.compile(r"""(?:RAM|memory)[:\s]*(\d+)\s*(?:GB|TB)""", re.I)

# Entrypoint scripts
_ENTRY_PATTERNS = re.compile(r"""(?:train|main|run|demo|test|eval|evaluate|infer|predict|generate)\.py""")

# Python version
_PY_VER = re.compile(r"""python[_\-]?(?:requires)?\s*[=><!]*\s*['"]?(\d+\.\d+)""", re.I)

# Env file priority (exact names only — globs are handled in _find_env_files)
ENV_FILES = [
    "Dockerfile", "docker/Dockerfile",
    "environment.yml", "environment.yaml", "conda_environment.yml", "conda.yml", "conda.yaml",
    "requirements.txt", "requirements/requirements.txt",
    "reqs.txt",
    "setup.py", "pyproject.toml", "setup.cfg", "Pipfile",
]


@dataclass
class EnvironmentSpec:
    repo_path: Path
    env_files: dict[str, Path] = field(default_factory=dict)
    primary_env: str | None = None
    primary_env_path: Path | None = None
    python_version: str = "3.10"
    packages: list[str] = field(default_factory=list)        # all pip/conda packages found
    datasets: list[str] = field(default_factory=list)        # URLs, HF dataset IDs, class names
    download_commands: list[str] = field(default_factory=list)  # wget/curl/gdown commands
    download_urls: list[str] = field(default_factory=list)   # data download links from paper
    checkpoint_urls: list[str] = field(default_factory=list)  # model weight URLs from paper
    frameworks: list[str] = field(default_factory=list)       # pytorch, tensorflow, etc.
    resolved_deps: "ResolvedDependencies | None" = None       # AI-resolved dependencies
    entrypoints: list[str] = field(default_factory=list)     # likely main scripts
    needs_gpu: bool = False
    needs_tpu: bool = False
    gpu_detail: str | None = None                            # e.g. "8 x A100"
    ram_hint: str | None = None                              # e.g. "32 GB"
    readme_setup: str = ""                                   # setup section from README

    def to_cache(self) -> dict:
        import json as _json
        from replicant.analyzers.dependencies import ResolvedDependencies
        d: dict = {
            "repo_path": str(self.repo_path),
            "env_files": {k: str(v) for k, v in self.env_files.items()},
            "primary_env": self.primary_env,
            "primary_env_path": str(self.primary_env_path) if self.primary_env_path else None,
            "python_version": self.python_version,
            "packages": self.packages,
            "datasets": self.datasets,
            "download_commands": self.download_commands,
            "download_urls": self.download_urls,
            "checkpoint_urls": self.checkpoint_urls,
            "frameworks": self.frameworks,
            "resolved_deps": self.resolved_deps.model_dump() if self.resolved_deps else None,
            "entrypoints": self.entrypoints,
            "needs_gpu": self.needs_gpu,
            "needs_tpu": self.needs_tpu,
            "gpu_detail": self.gpu_detail,
            "ram_hint": self.ram_hint,
            "readme_setup": self.readme_setup,
        }
        return d

    @classmethod
    def from_cache(cls, d: dict) -> "EnvironmentSpec":
        from replicant.analyzers.dependencies import ResolvedDependencies
        resolved = ResolvedDependencies(**d["resolved_deps"]) if d.get("resolved_deps") else None
        return cls(
            repo_path=Path(d["repo_path"]),
            env_files={k: Path(v) for k, v in d.get("env_files", {}).items()},
            primary_env=d.get("primary_env"),
            primary_env_path=Path(d["primary_env_path"]) if d.get("primary_env_path") else None,
            python_version=d.get("python_version", "3.10"),
            packages=d.get("packages", []),
            datasets=d.get("datasets", []),
            download_commands=d.get("download_commands", []),
            download_urls=d.get("download_urls", []),
            checkpoint_urls=d.get("checkpoint_urls", []),
            frameworks=d.get("frameworks", []),
            resolved_deps=resolved,
            entrypoints=d.get("entrypoints", []),
            needs_gpu=d.get("needs_gpu", False),
            needs_tpu=d.get("needs_tpu", False),
            gpu_detail=d.get("gpu_detail"),
            ram_hint=d.get("ram_hint"),
            readme_setup=d.get("readme_setup", ""),
        )


def analyze(repo: str | Path, pdf_path: str | Path | None = None, resolve_deps: bool = True) -> EnvironmentSpec:
    repo = Path(repo)
    spec = EnvironmentSpec(repo_path=repo)

    # 1. env files
    spec.env_files, spec.primary_env, spec.primary_env_path = _find_env_files(repo)

    # 2. scan all text files for packages, datasets, hardware, entrypoints
    all_text = _slurp_repo(repo)

    # packages from requirements/env files
    spec.packages = _extract_packages(repo, spec)

    # datasets
    seen_ds: set[str] = set()
    for pat in _DATASET_PATTERNS:
        for m in pat.finditer(all_text):
            val = m.group(1) if m.lastindex else m.group(0)
            val = val.strip().rstrip("'\")")
            if val and val not in seen_ds:
                seen_ds.add(val)
                if val.startswith("http") or "drive.google" in val:
                    spec.datasets.append(val)
                    # also save the full download command if present
                    line = _line_containing(all_text, val)
                    if line and any(c in line for c in ("wget", "curl", "gdown")):
                        spec.download_commands.append(line.strip())
                else:
                    spec.datasets.append(val)

    # frameworks from code imports
    _CODE_FRAMEWORKS = {
        "pytorch": re.compile(r"\bimport torch\b|\bfrom torch\b"),
        "tensorflow": re.compile(r"\bimport tensorflow\b|\bfrom tensorflow\b"),
        "jax": re.compile(r"\bimport jax\b|\bfrom jax\b"),
        "transformers": re.compile(r"\bfrom transformers\b|\bimport transformers\b"),
        "diffusers": re.compile(r"\bfrom diffusers\b|\bimport diffusers\b"),
        "detectron2": re.compile(r"\bimport detectron2\b|\bfrom detectron2\b"),
        "sklearn": re.compile(r"\bfrom sklearn\b|\bimport sklearn\b"),
        "opencv": re.compile(r"\bimport cv2\b"),
        "wandb": re.compile(r"\bimport wandb\b"),
        "deepspeed": re.compile(r"\bimport deepspeed\b"),
    }
    for name, pat in _CODE_FRAMEWORKS.items():
        if pat.search(all_text) and name not in spec.frameworks:
            spec.frameworks.append(name)

    # hardware
    spec.needs_gpu = bool(_GPU_HINTS.search(all_text))
    spec.needs_tpu = bool(_TPU_HINTS.search(all_text))
    if m := _LARGE_RAM.search(all_text):
        spec.ram_hint = m.group(0)

    # entrypoints
    for py in repo.rglob("*.py"):
        name = py.name
        if _ENTRY_PATTERNS.match(name):
            spec.entrypoints.append(str(py.relative_to(repo)))
    # also check README for "python <script>" patterns
    readme = _find_readme(repo)
    if readme:
        text = readme.read_text(errors="ignore")
        spec.readme_setup = _extract_setup_section(text)
        for m in re.finditer(r"python\s+([\w/]+\.py)", text):
            script = m.group(1)
            if script not in spec.entrypoints:
                spec.entrypoints.append(script)

    # python version
    spec.python_version = _infer_python(repo, spec, all_text)

    # Merge paper context if available
    if pdf_path:
        from replicant.analyzers.paper import analyze_paper
        paper_ctx = analyze_paper(pdf_path)
        
        # Merge datasets from paper (named + download URLs)
        for d in paper_ctx.datasets:
            if d.lower() not in {x.lower() for x in spec.datasets}:
                spec.datasets.append(d)
        for u in paper_ctx.download_urls:
            if u not in spec.download_urls: 
                spec.download_urls.append(u)
        for u in paper_ctx.checkpoint_urls:
            if u not in spec.checkpoint_urls: 
                spec.checkpoint_urls.append(u)
        
        # Merge frameworks
        for f in paper_ctx.frameworks:
            if f not in spec.frameworks: 
                spec.frameworks.append(f)
        
        # Merge hardware - paper overrides repo if more specific
        spec.needs_gpu = spec.needs_gpu or paper_ctx.needs_gpu
        spec.needs_tpu = spec.needs_tpu or paper_ctx.needs_tpu
        if paper_ctx.gpu_detail: 
            spec.gpu_detail = paper_ctx.gpu_detail
        if paper_ctx.ram_hint: 
            spec.ram_hint = paper_ctx.ram_hint
        
        # Python version from paper (only if repo didn't find one)
        if spec.python_version == "3.10" and paper_ctx.python_version:
            spec.python_version = paper_ctx.python_version

    # === AI-POWERED DEPENDENCY RESOLUTION ===
    # Only run if we have an env file — skip for repos that will fail at env_detection anyway
    if spec.primary_env and resolve_deps:
        spec.resolved_deps = _resolve_with_ai(repo, spec)
    
    # Update python version from AI resolution if provided
    if spec.resolved_deps and spec.resolved_deps.python_version:
        spec.python_version = spec.resolved_deps.python_version

    return spec


def _resolve_with_ai(repo: Path, spec: EnvironmentSpec) -> "ResolvedDependencies | None":
    """Use AI to resolve all dependencies with proper version pinning."""
    try:
        from replicant.analyzers.dependencies import (
            resolve_dependencies,
            extract_code_samples,
        )
        
        # Gather all the context for AI analysis
        requirements_content = ""
        if spec.primary_env == "requirements.txt" and spec.primary_env_path:
            requirements_content = spec.primary_env_path.read_text(errors="ignore")
        
        env_yml_content = ""
        for name in ("environment.yml", "environment.yaml"):
            if name in spec.env_files:
                env_yml_content = spec.env_files[name].read_text(errors="ignore")
                break
        
        setup_content = ""
        for name in ("setup.py", "pyproject.toml"):
            if name in spec.env_files:
                setup_content = spec.env_files[name].read_text(errors="ignore")
                break
        
        # Extract code samples showing framework usage
        code_samples = extract_code_samples(repo)
        
        # Get README content
        readme_content = spec.readme_setup or ""
        readme_file = _find_readme(repo)
        if readme_file:
            readme_content = readme_file.read_text(errors="ignore")
        
        # Call AI dependency resolver
        resolved = resolve_dependencies(
            repo_path=repo,
            existing_requirements=requirements_content,
            existing_env_yml=env_yml_content,
            setup_py_content=setup_content,
            code_samples=code_samples,
            readme_content=readme_content,
        )

        # Pre-build PyPI validation — catch phantom packages before Docker wastes time
        try:
            from replicant.utils.preflight import validate_packages, revalidate_with_llm
            phantoms = validate_packages(resolved)
            if phantoms:
                import sys
                print(f"[preflight] Phantom packages detected: {phantoms}. Re-resolving…", file=sys.stderr)
                resolved = revalidate_with_llm(
                    phantoms=phantoms,
                    repo_path=repo,
                    existing_requirements=requirements_content,
                    existing_env_yml=env_yml_content,
                    setup_py_content=setup_content,
                    code_samples=code_samples,
                    readme_content=readme_content,
                )
        except Exception as preflight_err:
            import sys
            print(f"Warning: preflight validation failed: {preflight_err}", file=sys.stderr)

        return resolved
    except Exception as e:
        # Log but don't fail - fall back to existing requirements
        import sys
        print(f"Warning: AI dependency resolution failed: {e}", file=sys.stderr)
        return None


# ── helpers ─────────────────────────────────────────────────────────────────

def _find_env_files(repo: Path) -> tuple[dict[str, Path], str | None, Path | None]:
    """Scan a repo for env/dependency files and return (all_found, primary_name, primary_path).

    Priority order:
      1. Dockerfile (root, then docker/)
      2. environment.yml / .yaml / conda variants
      3. requirements.txt (root)
      4. requirements-*.txt / requirements_*.txt at root (largest wins)
      5. requirements/*.txt (largest wins, requirements/requirements.txt preferred)
      6. setup.py
      7. pyproject.toml
      8. setup.cfg
      9. Pipfile
      10. One-level-deep fallbacks (*/requirements.txt, */setup.py, etc.)
    """
    found: dict[str, Path] = {}

    # --- exact paths ---
    for name in ENV_FILES:
        p = repo / name
        if p.exists():
            found[name] = p

    # --- glob patterns (depth 1-2) ---
    for p in repo.glob("requirements-*.txt"):
        found[p.name] = p
    for p in repo.glob("requirements_*.txt"):
        found[p.name] = p
    for p in repo.glob("requirements/*.txt"):
        found[str(p.relative_to(repo))] = p
    for p in repo.glob("docker/Dockerfile*"):
        found[str(p.relative_to(repo))] = p
    for p in repo.glob("*/requirements.txt"):
        key = str(p.relative_to(repo))
        if key not in found:
            found[key] = p
    for df in repo.rglob("Dockerfile"):
        key = str(df.relative_to(repo))
        if key not in found:
            found[key] = df

    # --- depth-2 patterns ---
    for pattern in (
        "*/*/requirements.txt",
        "*/*/requirements-*.txt",
        "*/*/requirements_*.txt",
        "*/*/environment.yml",
        "*/*/environment.yaml",
    ):
        for p in repo.glob(pattern):
            key = str(p.relative_to(repo))
            if key not in found:
                found[key] = p

    # --- depth-3 requirements ---
    for p in repo.glob("*/*/*/requirements.txt"):
        key = str(p.relative_to(repo))
        if key not in found:
            found[key] = p

    # --- multi-level fallbacks for setup files (depth 1-2) ---
    for child in repo.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        for name in ("setup.py", "pyproject.toml", "setup.cfg", "Pipfile",
                     "environment.yml", "environment.yaml"):
            p = child / name
            if p.exists():
                key = str(p.relative_to(repo))
                if key not in found:
                    found[key] = p
        # depth-2 setup files
        for grandchild in child.iterdir():
            if not grandchild.is_dir() or grandchild.name.startswith("."):
                continue
            for name in ("setup.py", "pyproject.toml", "setup.cfg", "Pipfile",
                         "environment.yml", "environment.yaml"):
                p = grandchild / name
                if p.exists():
                    key = str(p.relative_to(repo))
                    if key not in found:
                        found[key] = p

    # --- determine primary by priority ---
    primary: str | None = None
    primary_path: Path | None = None

    def _set(name: str) -> bool:
        nonlocal primary, primary_path
        if name in found:
            primary, primary_path = name, found[name]
            return True
        return False

    # 1. Dockerfile at root or docker/
    for name in ("Dockerfile", "docker/Dockerfile"):
        if _set(name):
            break

    # 2. Conda/environment files
    if primary is None:
        for name in ("environment.yml", "environment.yaml", "conda_environment.yml",
                     "conda.yml", "conda.yaml"):
            if _set(name):
                break

    # 3. requirements.txt at root
    if primary is None:
        _set("requirements.txt")

    # 4. requirements*.txt at root (largest wins)
    if primary is None:
        root_reqs = [
            (name, p) for name, p in found.items()
            if re.match(r"requirements[-_].+\.txt$", name) and "/" not in name
        ]
        if root_reqs:
            best_name, best_path = max(root_reqs, key=lambda x: x[1].stat().st_size)
            primary, primary_path = best_name, best_path

    # 5. requirements/*.txt (prefer requirements/requirements.txt, else largest)
    if primary is None:
        subdir_reqs = [
            (name, p) for name, p in found.items()
            if name.startswith("requirements/") and name.endswith(".txt")
        ]
        if subdir_reqs:
            base = next((x for x in subdir_reqs if x[0] == "requirements/requirements.txt"), None)
            if base:
                primary, primary_path = base
            else:
                best_name, best_path = max(subdir_reqs, key=lambda x: x[1].stat().st_size)
                primary, primary_path = best_name, best_path

    # 6–9. setup.py, pyproject.toml, setup.cfg, Pipfile
    if primary is None:
        for name in ("setup.py", "pyproject.toml", "setup.cfg", "Pipfile", "reqs.txt"):
            if _set(name):
                break

    # 10. Multi-level setup files (lowest priority, prefer shallowest + most .py files)
    if primary is None:
        _setup_suffixes = ("setup.py", "pyproject.toml", "setup.cfg", "Pipfile",
                           "environment.yml", "environment.yaml", "requirements.txt")
        candidates = [
            (name, p) for name, p in found.items()
            if "/" in name and any(name.endswith(s) for s in _setup_suffixes)
        ]
        if candidates:
            def _candidate_score(item: tuple[str, Path]) -> tuple[int, int]:
                name, p = item
                depth = name.count("/")
                py_count = sum(1 for _ in p.parent.glob("*.py"))
                return (depth, -py_count)
            best = min(candidates, key=_candidate_score)
            primary, primary_path = best[0], best[1]

    # Fallback: any Dockerfile found anywhere
    if primary is None:
        for name, p in found.items():
            if "Dockerfile" in name:
                primary, primary_path = name, p
                break

    return found, primary, primary_path


def _slurp_repo(repo: Path, max_bytes: int = 5_000_000) -> str:
    """Read all text files up to a budget. Skip binary/vendored."""
    skip = {".git", "node_modules", "__pycache__", ".egg-info", "venv", ".venv"}
    parts, total = [], 0
    for f in sorted(repo.rglob("*")):
        if any(s in f.parts for s in skip): continue
        if not f.is_file() or f.stat().st_size > 500_000: continue
        if f.suffix in (".py", ".sh", ".yml", ".yaml", ".toml", ".cfg", ".txt", ".md", ".rst", ".json", ""):
            try:
                text = f.read_text(errors="ignore")
                parts.append(text)
                total += len(text)
                if total > max_bytes: break
            except Exception: pass
    return "\n".join(parts)


def _extract_packages(repo: Path, spec: EnvironmentSpec) -> list[str]:
    pkgs: list[str] = []
    # requirements.txt style
    for name in ("requirements.txt", "requirements/requirements.txt"):
        p = repo / name
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    pkgs.append(re.split(r"[><=!~\[]", line)[0].strip())
    # environment.yml
    for name in ("environment.yml", "environment.yaml", "conda_environment.yml"):
        p = repo / name
        if p.exists():
            in_deps = False
            for line in p.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("dependencies:"):
                    in_deps = True; continue
                if in_deps:
                    if not stripped.startswith("-") and not stripped.startswith("#"):
                        in_deps = False; continue
                    if stripped.startswith("- pip:"):
                        continue
                    pkg = stripped.lstrip("- ").strip()
                    if pkg:
                        pkgs.append(re.split(r"[><=!~]", pkg)[0].strip())
    # setup.py / pyproject.toml install_requires
    for name in ("setup.py", "pyproject.toml"):
        p = repo / name
        if p.exists():
            text = p.read_text(errors="ignore")
            for m in re.finditer(r"""['"]([a-zA-Z][\w\-.]+)(?:[><=!~\[]|['"])""", text):
                pkg = m.group(1)
                if len(pkg) > 1 and pkg not in ("python", "setuptools", "wheel"):
                    pkgs.append(pkg)
    return list(dict.fromkeys(pkgs))  # dedup preserving order


def _infer_python(repo: Path, spec: EnvironmentSpec, text: str) -> str:
    for f in [repo / ".python-version", repo / "runtime.txt"]:
        if f.exists():
            v = f.read_text().strip().replace("python-", "")
            if re.match(r"\d+\.\d+", v): return v
    for name in ("environment.yml", "environment.yaml"):
        p = repo / name
        if p.exists():
            if m := re.search(r"python[=><!]*(\d+\.\d+)", p.read_text()): return m.group(1)
    if m := _PY_VER.search(text): return m.group(1)
    return "3.10"


def _find_readme(repo: Path) -> Path | None:
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = repo / name
        if p.exists(): return p
    return None


def _extract_setup_section(readme: str) -> str:
    """Pull the setup/installation section from a README."""
    lines = readme.splitlines()
    capture, buf = False, []
    for line in lines:
        lower = line.lower().strip()
        if re.match(r"^#{1,3}\s*(setup|install|getting.started|quick.start|usage|requirements)", lower):
            capture = True; buf = [line]; continue
        if capture:
            if re.match(r"^#{1,3}\s", line) and buf:
                break
            buf.append(line)
    return "\n".join(buf).strip()


def _line_containing(text: str, needle: str) -> str | None:
    for line in text.splitlines():
        if needle in line: return line
    return None
