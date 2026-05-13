"""Pre-build PyPI validation: catch phantom packages before wasting a Docker build."""
from __future__ import annotations

import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from replicant.analyzers.dependencies import ResolvedDependencies


def validate_packages(deps: "ResolvedDependencies") -> list[str]:
    """Check each resolved package exists on PyPI. Returns names that don't."""
    phantoms: list[str] = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_check_pypi, dep.package): dep.package
                   for dep in deps.dependencies}
        for future in as_completed(futures):
            pkg = futures[future]
            try:
                if not future.result():
                    phantoms.append(pkg)
            except Exception:
                pass  # network error — don't block the build
    return phantoms


def _check_pypi(package: str) -> bool:
    """Returns True if the package exists on PyPI."""
    try:
        url = f"https://pypi.org/pypi/{package}/json"
        req = urllib.request.Request(url, headers={"User-Agent": "replicant/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code != 404
    except Exception:
        return True  # assume it exists if we can't reach PyPI


def revalidate_with_llm(
    phantoms: list[str],
    repo_path: Path,
    existing_requirements: str = "",
    existing_env_yml: str = "",
    setup_py_content: str = "",
    code_samples: str = "",
    readme_content: str = "",
) -> "ResolvedDependencies":
    """Re-invoke resolve_dependencies() with phantom package list as context."""
    from replicant.analyzers.dependencies import resolve_dependencies

    phantom_note = (
        f"\n\n# PHANTOM PACKAGES — these do not exist on PyPI and must be "
        f"replaced with correct names or removed: {', '.join(phantoms)}"
    )
    return resolve_dependencies(
        repo_path=repo_path,
        existing_requirements=existing_requirements + phantom_note,
        existing_env_yml=existing_env_yml,
        setup_py_content=setup_py_content,
        code_samples=code_samples,
        readme_content=readme_content,
    )
