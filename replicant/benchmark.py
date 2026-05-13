"""Batch-run replicant setup across a corpus of papers and collect structured failure data."""
from __future__ import annotations

import csv
import json
import logging
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from replicant.utils.config import HOME, ensure_dirs, env_id

DEFAULT_TIMEOUT = 600


class CorpusEntry(BaseModel):
    """A single row from the corpus file."""
    paper_arxiv_id: str
    paper_title: str = ""
    repo_url: str = ""
    framework: str = ""
    year: float | int = 0
    subfield: str = ""
    conference: str = ""
    is_official: bool = True
    mentioned_in_paper: bool = True


def load_corpus(path: str | Path) -> list[CorpusEntry]:
    """Load corpus from CSV or JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Corpus file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_csv(path)
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [CorpusEntry(**row) for row in data]
        raise ValueError("JSON corpus must be a list of objects")
    raise ValueError(f"Unsupported corpus format: {suffix}. Use .csv or .json")


def _load_csv(path: Path) -> list[CorpusEntry]:
    entries = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            c = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            raw_year = c.get("year", "0")
            try:
                year = int(float(raw_year)) if raw_year else 0
            except (ValueError, TypeError):
                year = 0
            entries.append(CorpusEntry(
                paper_arxiv_id=c.get("paper_arxiv_id", ""),
                paper_title=c.get("paper_title", ""),
                repo_url=c.get("repo_url", ""),
                framework=c.get("framework", ""),
                subfield=c.get("subfield", ""),
                conference=c.get("conference", ""),
                year=year,
                is_official=c.get("is_official", "true").lower() in ("true", "1", "yes", ""),
                mentioned_in_paper=c.get("mentioned_in_paper", "true").lower() in ("true", "1", "yes", ""),
            ))
    return entries


class PaperResult(BaseModel):
    """Structured result for a single paper benchmark run."""
    paper_id: str = ""
    paper_title: str = ""
    venue: str = ""
    year: int = 0
    subfield: str = ""
    framework: str = ""
    github_found: bool = False
    github_url: str = ""
    github_accessible: bool = False
    env_file_found: bool = False
    env_file_type: str = ""
    llm_assisted: bool = True
    llm_inferences_made: int = 0
    python_version_inferred: str = ""
    dependencies_detected: int = 0
    dependencies_inferred_by_llm: int = 0
    build_attempted: bool = False
    build_success: bool = False
    failure_category: str = ""
    failure_detail: str = ""
    failure_stage: str = ""
    secondary_failure: str = ""
    secondary_detail: str = ""
    dataset_access: str = ""
    hardware_required: str = ""
    fixability: str = ""
    retry_attempted: bool = False
    duration_seconds: float = 0.0
    timestamp: str = ""


# Failure pattern matching: (category, default_stage, compiled_regex)
_FAILURE_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("missing_env_spec", "env_detection", re.compile(
        r"No environment file found in repo|No environment specification found|"
        r"COPY\s+requirements\.txt.*not found|"
        r"Invalid requirement:|requirements\.txt.*does not exist|"
        r"failed to calculate checksum.*requirements\.txt", re.I)),
    ("build_order_dependency", "docker_build", re.compile(
        r"ModuleNotFoundError:\s*No module named|ImportError.*No module named|"
        r"setup\.py.*import.*failed|ModuleNotFoundError.*at metadata generation", re.I)),
    ("phantom_dependency", "docker_build", re.compile(
        r"No matching distribution found for|ERROR: Could not find a version that satisfies the requirement|"
        r"Package .* is not available|No such package|404.*simple/\w+/|not installable via pip", re.I)),
    ("version_conflict", "docker_build", re.compile(
        r"Could not find a version that satisfies|has requirement .* but you|"
        r"ResolutionImpossible|incompatible versions|VersionConflict|"
        r"THESE PACKAGES DO NOT MATCH THE HASHES|pip.*backtracking", re.I)),
    ("platform_mismatch", "docker_build", re.compile(
        r"no matching distribution.*platform|is not a supported wheel on this platform|"
        r"aarch64|not supported.*platform|Failed building wheel for", re.I)),
    ("missing_system_dep", "docker_build", re.compile(
        r"fatal error:.*\.h.*No such file|cannot find -l|"
        r"Package .* was not found in the pkg-config search path|error: command 'gcc' failed|"
        r"libgl|libglib|ffmpeg|libsm|libxext|OSError:.*libcudnn|Could not find library", re.I)),
]


def categorize_failure(error_msg: str, build_log: str = "", stage: str = "") -> tuple[str, str, str]:
    """Categorize a failure. Returns (category, detail, stage)."""
    combined = f"{error_msg}\n{build_log}"
    if not stage:
        stage = _infer_stage(error_msg)
    for category, default_stage, pattern in _FAILURE_PATTERNS:
        if m := pattern.search(combined):
            # Find the matching line for a concise detail
            for line in combined[max(0, m.start()-100):m.end()+200].splitlines():
                if pattern.search(line):
                    return category, line.strip()[:300], stage or default_stage
    return "unknown_build_error", _extract_failure_detail(combined), stage or "docker_build"


def _extract_failure_detail(text: str) -> str:
    """Extract a concise and useful failure detail from noisy build output."""
    if not text:
        return "Unknown error"

    lines = [ln.strip() for ln in text.splitlines() if ln and ln.strip()]
    if not lines:
        return "Unknown error"

    priority = ("ERROR", "error:", "failed to", "Traceback", "Exception", "No environment file")
    for line in reversed(lines):
        if any(token in line for token in priority):
            return line[:500]

    tail = "\n".join(lines[-5:])
    return tail[:500]


def _infer_stage(error_msg: str) -> str:
    lower = error_msg.lower()
    for keywords, stage in [
        (("arxiv", "paper", "pdf"), "paper_parse"),
        (("clone", "git", "repository not found"), "github_discovery"),
        (("no environment file", "no env file", "no runnable code", "missing env spec", "self contained"), "env_detection"),
        (("bedrock", "claude", "boto3", "llm", "dependency resolution"), "llm_analysis"),
        (("docker", "build", "pip install"), "docker_build"),
    ]:
        if any(k in lower for k in keywords):
            return stage
    return ""


def _has_runnable_code(repo_path: Path) -> bool:
    """Check if the repo contains actual executable Python code (not just README/data)."""
    python_files = list(repo_path.rglob("*.py"))
    # Filter out common non-code patterns
    code_files = [
        f for f in python_files
        if not any(part.startswith(".") for part in f.relative_to(repo_path).parts)
        and f.name not in ("setup.py", "conf.py", "__init__.py")
        and "test" not in f.name.lower()
        and f.stat().st_size > 100  # At least 100 bytes
    ]
    # Check if we have substantial Python files (excluding just __init__.py)
    return len(code_files) > 0


def _detect_external_imports(repo_path: Path) -> set[str]:
    """Scan Python files for import statements, return non-stdlib package names."""
    # Common stdlib modules (not exhaustive, but covers common cases)
    stdlib = {
        "os", "sys", "re", "json", "csv", "math", "random", "time", "datetime",
        "collections", "itertools", "functools", "pathlib", "typing", "argparse",
        "logging", "unittest", "pickle", "io", "tempfile", "shutil", "glob",
        "subprocess", "threading", "multiprocessing", "socket", "urllib", "http",
        "email", "copy", "abc", "dataclasses", "enum", "warnings", "traceback",
    }
    # Trivially obvious packages that are essentially standard
    trivial = {"numpy", "np"}
    
    imports = set()
    for py_file in repo_path.rglob("*.py"):
        if any(part.startswith(".") for part in py_file.relative_to(repo_path).parts):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            # Match import statements
            import_pattern = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)
            for match in import_pattern.finditer(content):
                module = match.group(1).split(".")[0]
                if module not in stdlib and module not in trivial:
                    imports.add(module)
        except Exception:
            continue
    return imports


def _classify_no_env_file(repo_path: Path) -> tuple[str, str]:
    """Classify repos without env files into three categories.
    
    When no environment specification file (requirements.txt, environment.yml, etc.)
    is found, this function distinguishes between three distinct cases:
    
    1. **no_runnable_code**: Repository contains no substantial executable Python code.
       Often just a project page, documentation, or data files. The "code" link from
       Papers with Code may have been a project landing page, not a runnable codebase.
       This is similar to no_code but discovered after repo cloning.
    
    2. **missing_env_spec**: Actual Python code exists with external dependencies
       (imports beyond stdlib), but the authors never provided any environment
       specification. This is the "author negligence" case — a reproducibility gap
       where the code cannot be reliably run without reverse-engineering dependencies.
       This is the key finding for reproducibility research.
    
    3. **self_contained**: Code exists and runs with only standard library imports
       (or trivially obvious packages like numpy). No environment specification is
       needed. Replicant marking this as a "failure" would be a false negative —
       it's arguably a success case since the code can run without setup.
    
    Returns (failure_category, failure_detail).
    """
    # Case 1: No runnable code at all
    if not _has_runnable_code(repo_path):
        return "no_runnable_code", "Repository contains no substantial executable Python code"
    
    # Case 2: Check for external dependencies
    external_imports = _detect_external_imports(repo_path)
    
    if external_imports:
        # Before giving up, do a broader scan — env files may exist in non-standard locations
        # that the main detector didn't pick up.
        hidden_files: list[str] = []
        for p in repo_path.rglob("requirements*.txt"):
            hidden_files.append(str(p.relative_to(repo_path)))
        for p in repo_path.rglob("environment*.y*ml"):
            hidden_files.append(str(p.relative_to(repo_path)))
        for p in repo_path.rglob("setup.py"):
            hidden_files.append(str(p.relative_to(repo_path)))
        for p in repo_path.rglob("Pipfile"):
            hidden_files.append(str(p.relative_to(repo_path)))

        deps_str = ", ".join(sorted(external_imports)[:10])
        if len(external_imports) > 10:
            deps_str += f" (+{len(external_imports) - 10} more)"

        if hidden_files:
            note = "; env-like files found at unexpected paths: " + ", ".join(hidden_files[:5])
        else:
            note = ""
        return "missing_env_spec", f"Code has dependencies ({deps_str}) but no requirements file{note}"
    
    # Case 3: Self-contained code with only stdlib
    return "self_contained", "Code is self-contained (stdlib only, no env spec needed)"


class _BuildTimeout(Exception):
    pass


def _fail(result: PaperResult, cat: str, detail: str, stage: str):
    """Set failure fields on a result."""
    result.failure_category = cat
    result.failure_detail = detail
    result.failure_stage = stage


def run_single_paper(
    entry: CorpusEntry,
    timeout: int = DEFAULT_TIMEOUT,
    logger: logging.Logger | None = None,
    no_llm: bool = False,
) -> PaperResult:
    """Run the full setup pipeline for a single paper. Never raises."""
    log = logger or logging.getLogger("replicant.benchmark")
    start = time.monotonic()
    result = PaperResult(
        paper_id=entry.paper_arxiv_id, paper_title=entry.paper_title,
        venue=entry.conference or "arxiv", year=int(entry.year) if entry.year else 0,
        subfield=entry.subfield, framework=entry.framework,
        timestamp=datetime.now(timezone.utc).isoformat(),
        llm_assisted=not no_llm,
    )
    github_url: str | None = entry.repo_url.strip() or None

    try:
        # Step 1: Resolve GitHub URL
        if not github_url:
            log.info("[%s] No repo_url, attempting arXiv discovery", entry.paper_arxiv_id)
            try:
                from replicant.sources.arxiv import is_arxiv, fetch
                from replicant.analyzers.paper import analyze_paper
                if not is_arxiv(entry.paper_arxiv_id):
                    _fail(result, "no_code", f"'{entry.paper_arxiv_id}' is not a valid arXiv ID and no repo_url provided", "github_discovery")
                    return result
                _info = fetch(entry.paper_arxiv_id)
                result.llm_inferences_made += 1
                paper_ctx = analyze_paper(entry.paper_arxiv_id)
                result.llm_inferences_made += 1
                result.paper_title = result.paper_title or _info.get("title", "")
                if paper_ctx.github_urls:
                    github_url = paper_ctx.github_urls[0]
            except Exception as exc:
                log.warning("[%s] Paper parse failed: %s", entry.paper_arxiv_id, exc)
                _fail(result, "no_code", str(exc)[:500], "paper_parse")
                return result

        if not github_url:
            _fail(result, "no_code", "No GitHub repository found in paper or corpus", "github_discovery")
            return result

        result.github_found = True
        result.github_url = github_url

        # Step 2: Clone
        log.info("[%s] Cloning %s", entry.paper_arxiv_id, github_url)
        try:
            from replicant.sources.github import clone
            code_path = clone(github_url)
            result.github_accessible = True
        except Exception as exc:
            log.warning("[%s] Clone failed: %s", entry.paper_arxiv_id, exc)
            _fail(result, "repo_inaccessible", str(exc)[:500], "github_discovery")
            return result

        # Step 3: PDF path for analysis (skipped in no-LLM mode)
        pdf_for_analysis = None
        if not no_llm:
            from replicant.sources.arxiv import is_arxiv
            if is_arxiv(entry.paper_arxiv_id):
                candidate = HOME / "papers" / f"{entry.paper_arxiv_id}.pdf"
                if candidate.exists():
                    pdf_for_analysis = candidate

        # Step 4: Analyze repo
        log.info("[%s] Analyzing repo", entry.paper_arxiv_id)
        try:
            from replicant.analyzers.repo import analyze
            spec = analyze(code_path, pdf_path=pdf_for_analysis, resolve_deps=not no_llm)
            if pdf_for_analysis:
                result.llm_inferences_made += 1
            if spec.resolved_deps:
                result.llm_inferences_made += 1
        except Exception as exc:
            log.warning("[%s] Analysis failed: %s", entry.paper_arxiv_id, exc)
            _fail(result, "unknown_build_error", str(exc)[:500], "llm_analysis")
            return result

        if not spec.primary_env:
            # Classify into three more granular categories
            category, detail = _classify_no_env_file(code_path)
            _fail(result, category, detail, "env_detection")
            # For self_contained, mark it as a partial success (we could run the code)
            if category == "self_contained":
                result.build_success = True  # Arguably a success case
            return result

        result.env_file_found = True
        result.env_file_type = spec.primary_env or ""
        result.python_version_inferred = spec.python_version
        result.dependencies_detected = len(spec.packages)
        if spec.resolved_deps:
            result.dependencies_inferred_by_llm = len(spec.resolved_deps.dependencies)
        if spec.needs_gpu:
            result.hardware_required = (spec.gpu_detail or "GPU").replace(" ", "_")

        # Step 5: Generate Dockerfile
        log.info("[%s] Generating Dockerfile", entry.paper_arxiv_id)
        try:
            eid = env_id(entry.paper_arxiv_id, github_url)
            if no_llm:
                from replicant.generators.docker import generate_baseline
                build_dir = generate_baseline(spec, eid)
            else:
                from replicant.generators.docker import generate
                build_dir = generate(spec, eid)
        except Exception as exc:
            log.warning("[%s] Dockerfile generation failed: %s", entry.paper_arxiv_id, exc)
            message = str(exc)
            inferred_stage = _infer_stage(message) or "docker_build"
            if "no environment file" in message.lower():
                # No usable env file — correct the fields set above before generate() was called
                result.env_file_found = False
                result.env_file_type = ""
                category, detail = _classify_no_env_file(code_path)
                _fail(result, category, detail, "env_detection")
            else:
                _fail(result, "unknown_build_error", message[:500], inferred_stage)
            return result

        # Step 6: Build Docker image
        tag = f"replicant-{eid}"
        log.info("[%s] Building %s (timeout=%ds)", entry.paper_arxiv_id, tag, timeout)
        result.build_attempted = True
        try:
            build_success, build_log = _build_with_timeout(build_dir, tag, timeout)
        except _BuildTimeout:
            _fail(result, "build_timeout", f"Docker build exceeded {timeout}s timeout", "docker_build")
            return result
        except Exception as exc:
            log.warning("[%s] Build error: %s", entry.paper_arxiv_id, exc)
            _fail(result, "unknown_build_error", str(exc)[:500], "docker_build")
            return result

        if build_success:
            result.build_success = True
            result.failure_category = "success"
        else:
            cat, detail, stg = categorize_failure(build_log, build_log, "docker_build")
            _fail(result, cat, detail, stg)

            # One-shot retry for dependency failures when LLM is available
            _retryable = ("phantom_dependency", "version_conflict", "unknown_build_error")
            if not no_llm and cat in _retryable and spec.primary_env and not spec.primary_env.endswith("Dockerfile"):
                log.info("[%s] Retrying after %s with corrected deps", entry.paper_arxiv_id, cat)
                result.retry_attempted = True
                try:
                    from replicant.utils.build_errors import parse_build_failure
                    from replicant.utils.config import LOGS
                    from replicant.analyzers.dependencies import resolve_dependencies, extract_code_samples
                    from replicant.generators.docker import generate

                    failure_ctx = parse_build_failure(LOGS / f"{tag}.log")
                    req_content = spec.primary_env_path.read_text(errors="ignore") if spec.primary_env_path else ""
                    code_samps = extract_code_samples(code_path)

                    spec.resolved_deps = resolve_dependencies(
                        repo_path=code_path,
                        existing_requirements=(
                            req_content +
                            f"\n\n# PREVIOUS BUILD FAILURE — use this to fix the dependency set:\n"
                            + "\n".join(f"# {ln}" for ln in failure_ctx.splitlines())
                        ),
                        code_samples=code_samps,
                        readme_content=spec.readme_setup or "",
                    )
                    result.llm_inferences_made += 1
                    build_dir = generate(spec, eid)
                    build_success, build_log = _build_with_timeout(build_dir, tag, timeout)
                    if build_success:
                        result.build_success = True
                        result.failure_category = "success"
                    else:
                        cat2, detail2, stg2 = categorize_failure(build_log, build_log, "docker_build")
                        _fail(result, cat2, detail2, stg2)
                except Exception as retry_exc:
                    log.warning("[%s] Retry failed: %s", entry.paper_arxiv_id, retry_exc)

        # Save EnvMeta
        from replicant.utils.config import EnvMeta
        EnvMeta(
            env_id=eid, source=entry.paper_arxiv_id, github_url=github_url,
            docker_image=tag, environment_file=spec.primary_env or "",
            paper_title=result.paper_title, status="ready" if build_success else "failed",
            code_path=str(code_path),
        ).save()

    except Exception as exc:
        log.error("[%s] Unexpected: %s\n%s", entry.paper_arxiv_id, exc, traceback.format_exc())
        if not result.failure_category:
            _fail(result, "unknown_build_error", str(exc)[:500], _infer_stage(str(exc)) or "docker_build")
    finally:
        result.duration_seconds = round(time.monotonic() - start, 2)

    return result


def _build_with_timeout(build_dir: Path, tag: str, timeout: int) -> tuple[bool, str]:
    """Build a Docker image with a timeout. Returns (success, log_text)."""
    import os
    import subprocess
    from replicant.utils.config import LOGS

    log_path = LOGS / f"{tag}.log"
    
    # Use regular docker build with platform flag and BuildKit enabled
    env = os.environ.copy()
    env['DOCKER_BUILDKIT'] = '1'
    
    cmd = [
        "docker", "build",
        "--platform", "linux/amd64",
        "-t", tag,
        "-f", str(build_dir / "Dockerfile"),
        str(build_dir)
    ]

    def _as_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env
        )
        
        output = _as_text(result.stdout) + _as_text(result.stderr)
        log_path.write_text(output)
        
        return result.returncode == 0, output
        
    except subprocess.TimeoutExpired as e:
        output = _as_text(e.stdout) + _as_text(e.stderr) + f"\n[TIMEOUT] Build exceeded {timeout}s limit.\n"
        log_path.write_text(output)
        raise _BuildTimeout()
    except Exception as e:
        output = f"Build error: {e}\n"
        log_path.write_text(output)
        return False, output


def _tally(results: list[PaperResult], field: str) -> dict[str, dict[str, int]]:
    """Count success/failure by a given field (subfield, framework, etc.)."""
    out: dict[str, dict[str, int]] = {}
    for r in results:
        key = getattr(r, field, "") or "unknown"
        if key not in out:
            out[key] = {"success": 0, "failure": 0}
        out[key]["success" if r.build_success else "failure"] += 1
    return out


def generate_summary(results: list[PaperResult], skipped: int = 0, no_llm: bool = False) -> dict:
    """Generate an aggregate summary from all paper results."""
    successes = sum(1 for r in results if r.build_success)
    failure_breakdown: dict[str, int] = {}
    failure_by_stage: dict[str, int] = {}
    for r in results:
        if r.failure_category and r.failure_category != "success":
            failure_breakdown[r.failure_category] = failure_breakdown.get(r.failure_category, 0) + 1
        if r.failure_stage:
            failure_by_stage[r.failure_stage] = failure_by_stage.get(r.failure_stage, 0) + 1
    return {
        "llm_assisted": not no_llm,
        "corpus_size": len(results) + skipped,
        "completed": len(results),
        "skipped": skipped,
        "total_duration_seconds": round(sum(r.duration_seconds for r in results), 2),
        "outcomes": {"success": successes, "failure": len(results) - successes},
        "failure_breakdown": dict(sorted(failure_breakdown.items(), key=lambda x: -x[1])),
        "failure_by_stage": dict(sorted(failure_by_stage.items(), key=lambda x: -x[1])),
        "by_subfield": _tally(results, "subfield"),
        "by_framework": _tally(results, "framework"),
    }


def run_benchmark(
    corpus: list[CorpusEntry],
    output_dir: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    resume: bool = False,
    max_workers: int = 1,
    result_callback=None,
    no_llm: bool = False,
) -> Path:
    """Run the full benchmark. Returns the output directory path."""
    if not corpus:
        raise ValueError("Corpus is empty")

    output = Path(output_dir) if output_dir else HOME / "benchmark"
    output.mkdir(parents=True, exist_ok=True)

    logger = _setup_logging()
    logger.info("Benchmark started: %d papers, timeout=%ds, workers=%d, output=%s", len(corpus), timeout, max_workers, output)

    results: list[PaperResult] = []
    total = len(corpus)
    skipped = 0

    # Pre-load cached results if in resume mode
    to_process: list[tuple[int, CorpusEntry]] = []
    
    for idx, entry in enumerate(corpus, 1):
        pid = entry.paper_arxiv_id
        result_file = output / f"{pid}.json"

        if resume and result_file.exists():
            try:
                result = PaperResult.model_validate_json(result_file.read_text())
                results.append(result)
                skipped += 1
                logger.info("[%d/%d] %s — skipped (cached)", idx, total, pid)
                if result_callback:
                    result_callback(idx, total, pid, "cached", 0.0)
                continue
            except Exception:
                pass
        to_process.append((idx, entry))

    # Process papers with controlled parallelism
    if to_process:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            queue = to_process.copy()
            
            # Submit initial batch
            while queue and len(futures) < max_workers:
                idx, entry = queue.pop(0)
                logger.info("[%d/%d] %s — starting", idx, total, entry.paper_arxiv_id)
                future = executor.submit(run_single_paper, entry, timeout=timeout, logger=logger, no_llm=no_llm)
                futures[future] = (idx, entry)

            # Process completions and submit new work
            while futures:
                for future in as_completed(futures):
                    idx, entry = futures.pop(future)
                    pid = entry.paper_arxiv_id
                    result_file = output / f"{pid}.json"

                    try:
                        result = future.result()
                        results.append(result)
                        result_file.write_text(result.model_dump_json(indent=2))
                        status = "success" if result.build_success else result.failure_category or "unknown"
                        logger.info("[%d/%d] %s — %s (%.1fs)", idx, total, pid, status, result.duration_seconds)
                        if result_callback:
                            result_callback(idx, total, pid, status, result.duration_seconds)
                    except Exception as e:
                        logger.error("[%d/%d] %s — crashed: %s", idx, total, pid, e)
                        if result_callback:
                            result_callback(idx, total, pid, "crashed", 0.0)

                    # Submit next paper from queue
                    if queue:
                        next_idx, next_entry = queue.pop(0)
                        logger.info("[%d/%d] %s — starting", next_idx, total, next_entry.paper_arxiv_id)
                        next_future = executor.submit(run_single_paper, next_entry, timeout=timeout, logger=logger, no_llm=no_llm)
                        futures[next_future] = (next_idx, next_entry)
                    break

    summary = generate_summary(results, skipped=skipped, no_llm=no_llm)
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    logger.info("Benchmark complete. Summary: %s", output / "summary.json")
    return output


def _setup_logging() -> logging.Logger:
    ensure_dirs()
    log_dir = HOME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("replicant.benchmark")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(
        log_dir / f"benchmark-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    return logger
