"""Tests for build log parsing and retry field (1C)."""
import tempfile
from pathlib import Path

import pytest

from replicant.utils.build_errors import parse_build_failure
from replicant.benchmark import PaperResult


# ── parse_build_failure ───────────────────────────────────────────────────────

def test_returns_empty_for_missing_log():
    assert parse_build_failure(Path("/nonexistent/path/build.log")) == ""


def test_returns_empty_for_empty_log():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("")
        f.flush()
        assert parse_build_failure(Path(f.name)) == ""


def test_extracts_error_line():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(
            "Step 1/4 : FROM python:3.10-slim\n"
            "Step 2/4 : RUN pip install torch\n"
            "ERROR: No matching distribution found for ghost-pkg==99.0\n"
            "Step 3/4 : WORKDIR /workspace\n"
        )
        f.flush()
        result = parse_build_failure(Path(f.name))
    assert "No matching distribution found" in result


def test_extracts_context_around_error():
    lines = ["line1\n", "line2\n", "line3\n", "ERROR: bad version\n", "line5\n", "line6\n"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.writelines(lines)
        f.flush()
        result = parse_build_failure(Path(f.name))
    # Should include lines before the error too
    assert "ERROR: bad version" in result
    assert "line2" in result or "line3" in result


def test_uses_last_error_line_when_multiple():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(
            "ERROR: first error (minor)\n"
            "Step 3/5 : RUN pip install -r requirements.txt\n"
            "Collecting packages...\n"
            "ERROR: No matching distribution found for bad-pkg==1.0\n"
            "exit code: 1\n"
        )
        f.flush()
        result = parse_build_failure(Path(f.name))
    # Should capture context around the LAST error
    assert "bad-pkg" in result


def test_falls_back_to_tail_when_no_error_token():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        content = "\n".join(f"line{i}" for i in range(100))
        f.write(content)
        f.flush()
        result = parse_build_failure(Path(f.name))
    # Should return something (last N lines) rather than empty
    assert result != ""
    assert "line99" in result


def test_version_conflict_token_detected():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(
            "Collecting numpy==1.99.0\n"
            "Could not find a version that satisfies numpy==1.99.0\n"
        )
        f.flush()
        result = parse_build_failure(Path(f.name))
    assert "Could not find a version" in result


def test_result_is_string():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("some build output\n")
        f.flush()
        result = parse_build_failure(Path(f.name))
    assert isinstance(result, str)


# ── PaperResult.retry_attempted ───────────────────────────────────────────────

def test_paper_result_retry_attempted_defaults_false():
    r = PaperResult(paper_id="2301.00001")
    assert r.retry_attempted is False


def test_paper_result_retry_attempted_serializes():
    r = PaperResult(paper_id="2301.00001", retry_attempted=True)
    data = r.model_dump()
    assert data["retry_attempted"] is True


def test_paper_result_retry_attempted_roundtrips_json():
    r = PaperResult(paper_id="2301.00001", retry_attempted=True)
    json_str = r.model_dump_json()
    r2 = PaperResult.model_validate_json(json_str)
    assert r2.retry_attempted is True


def test_paper_result_retry_attempted_false_roundtrips():
    r = PaperResult(paper_id="2301.00001", retry_attempted=False)
    r2 = PaperResult.model_validate_json(r.model_dump_json())
    assert r2.retry_attempted is False
