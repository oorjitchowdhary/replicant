"""Tests for pre-build PyPI validation (1B)."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from replicant.utils.preflight import _check_pypi, validate_packages, revalidate_with_llm


# ── _check_pypi ───────────────────────────────────────────────────────────────

def _mock_urlopen(status: int):
    """Return a context-manager mock that yields a response with the given status."""
    resp = MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: resp
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_check_pypi_exists():
    with patch("replicant.utils.preflight.urllib.request.urlopen", return_value=_mock_urlopen(200)):
        assert _check_pypi("numpy") is True


def test_check_pypi_not_found():
    import urllib.error
    with patch("replicant.utils.preflight.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(None, 404, "Not Found", {}, None)):
        assert _check_pypi("ghost-pkg-xyz") is False


def test_check_pypi_network_error_assumes_exists():
    """A network failure should not block the build — assume the package exists."""
    with patch("replicant.utils.preflight.urllib.request.urlopen",
               side_effect=OSError("no network")):
        assert _check_pypi("numpy") is True


def test_check_pypi_non_404_http_error_assumes_exists():
    """A 500 error is transient — don't flag the package as phantom."""
    import urllib.error
    with patch("replicant.utils.preflight.urllib.request.urlopen",
               side_effect=urllib.error.HTTPError(None, 500, "Server Error", {}, None)):
        assert _check_pypi("numpy") is True


# ── validate_packages ─────────────────────────────────────────────────────────

def _make_resolved(packages: list[str]):
    """Build a minimal ResolvedDependencies-like object."""
    from replicant.analyzers.dependencies import DependencySpec, ResolvedDependencies
    deps = [DependencySpec(package=p, version_spec=">=1.0") for p in packages]
    return ResolvedDependencies(
        python_version="3.10",
        python_reason="default",
        dependencies=deps,
    )


def test_validate_packages_all_real():
    resolved = _make_resolved(["numpy", "torch"])
    with patch("replicant.utils.preflight._check_pypi", return_value=True):
        phantoms = validate_packages(resolved)
    assert phantoms == []


def test_validate_packages_detects_phantom():
    resolved = _make_resolved(["numpy", "ghost-pkg-xyz123"])

    def _fake_check(pkg):
        return pkg != "ghost-pkg-xyz123"

    with patch("replicant.utils.preflight._check_pypi", side_effect=_fake_check):
        phantoms = validate_packages(resolved)
    assert "ghost-pkg-xyz123" in phantoms
    assert "numpy" not in phantoms


def test_validate_packages_empty_deps():
    resolved = _make_resolved([])
    phantoms = validate_packages(resolved)
    assert phantoms == []


def test_validate_packages_all_phantom():
    resolved = _make_resolved(["fake-a", "fake-b"])
    with patch("replicant.utils.preflight._check_pypi", return_value=False):
        phantoms = validate_packages(resolved)
    assert set(phantoms) == {"fake-a", "fake-b"}


def test_validate_packages_network_error_returns_empty():
    """If all checks raise, no packages should be flagged as phantom."""
    resolved = _make_resolved(["numpy"])
    with patch("replicant.utils.preflight._check_pypi", side_effect=OSError):
        phantoms = validate_packages(resolved)
    assert phantoms == []


# ── revalidate_with_llm ───────────────────────────────────────────────────────

def test_revalidate_appends_phantom_note_to_requirements():
    """The phantom package names must appear in the re-invoked prompt context."""
    captured = {}

    def _fake_resolve(**kwargs):
        captured["existing_requirements"] = kwargs.get("existing_requirements", "")
        from replicant.analyzers.dependencies import ResolvedDependencies
        return ResolvedDependencies(python_version="3.10", python_reason="test", dependencies=[])

    with patch("replicant.analyzers.dependencies.resolve_dependencies", side_effect=_fake_resolve):
        revalidate_with_llm(
            phantoms=["ghost-pkg", "another-fake"],
            repo_path=Path("/tmp/fake"),
            existing_requirements="numpy\nghost-pkg\n",
        )

    assert "ghost-pkg" in captured["existing_requirements"]
    assert "another-fake" in captured["existing_requirements"]
    assert "PHANTOM" in captured["existing_requirements"].upper()


def test_revalidate_passes_all_context():
    """All context args must be forwarded to resolve_dependencies."""
    captured = {}

    def _fake_resolve(**kwargs):
        captured.update(kwargs)
        from replicant.analyzers.dependencies import ResolvedDependencies
        return ResolvedDependencies(python_version="3.10", python_reason="test", dependencies=[])

    with patch("replicant.analyzers.dependencies.resolve_dependencies", side_effect=_fake_resolve):
        revalidate_with_llm(
            phantoms=["bad-pkg"],
            repo_path=Path("/tmp/repo"),
            existing_requirements="bad-pkg\n",
            existing_env_yml="name: env\n",
            setup_py_content="setup(name='x')\n",
            code_samples="import bad_pkg\n",
            readme_content="Install bad-pkg first.\n",
        )

    assert captured["existing_env_yml"] == "name: env\n"
    assert captured["setup_py_content"] == "setup(name='x')\n"
    assert captured["code_samples"] == "import bad_pkg\n"
    assert "Install bad-pkg" in captured["readme_content"]
