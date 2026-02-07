"""Analyze a repo (and optionally a paper PDF) to produce a full EnvironmentSpec.

Scans for: env files, packages, datasets to download, entrypoint scripts,
hardware hints (GPU/TPU/RAM), and python version.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

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

# Env file priority
ENV_FILES = [
    "Dockerfile", "docker/Dockerfile",
    "environment.yml", "environment.yaml", "conda_environment.yml",
    "requirements.txt", "requirements/requirements.txt",
    "setup.py", "pyproject.toml",
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
    entrypoints: list[str] = field(default_factory=list)     # likely main scripts
    needs_gpu: bool = False
    needs_tpu: bool = False
    gpu_detail: str | None = None                            # e.g. "8 x A100"
    ram_hint: str | None = None                              # e.g. "32 GB"
    readme_setup: str = ""                                   # setup section from README


def analyze(repo: str | Path, pdf_path: str | Path | None = None) -> EnvironmentSpec:
    repo = Path(repo)
    spec = EnvironmentSpec(repo_path=repo)

    # 1. env files
    for name in ENV_FILES:
        p = repo / name
        if p.exists(): spec.env_files[name] = p
    for df in repo.rglob("Dockerfile"):
        key = str(df.relative_to(repo))
        if key not in spec.env_files: spec.env_files[key] = df

    for name in ENV_FILES:
        if name in spec.env_files:
            spec.primary_env = name
            spec.primary_env_path = spec.env_files[name]
            break

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

# 3. merge paper PDF context
    if pdf_path:
        try:
            from replicant.parsers.pdf import parse_paper
            paper = parse_paper(pdf_path)
            # datasets from paper (named + download URLs)
            for d in paper.datasets:
                if d.lower() not in {x.lower() for x in spec.datasets}:
                    spec.datasets.append(d)
            for u in paper.download_urls:
                if u not in spec.download_urls: spec.download_urls.append(u)
            for u in paper.checkpoint_urls:
                if u not in spec.checkpoint_urls: spec.checkpoint_urls.append(u)
            # frameworks
            for f in paper.frameworks:
                if f not in spec.frameworks: spec.frameworks.append(f)
            # hardware — paper overrides repo if more specific
            spec.needs_gpu = spec.needs_gpu or paper.needs_gpu
            spec.needs_tpu = spec.needs_tpu or paper.needs_tpu
            if paper.gpu_detail: spec.gpu_detail = paper.gpu_detail
            if paper.ram_hint: spec.ram_hint = paper.ram_hint
            # python version from paper (only if repo didn't have one)
            if spec.python_version == "3.10" and paper.python_version:
                spec.python_version = paper.python_version
        except Exception:
            pass

    return spec


# ── helpers ─────────────────────────────────────────────────────────────────

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
