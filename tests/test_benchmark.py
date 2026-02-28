"""Tests for the benchmark module — corpus loading, failure categorization, summary generation."""
import json
import tempfile
from pathlib import Path

import pytest

from replicant.benchmark import (
    CorpusEntry,
    PaperResult,
    categorize_failure,
    generate_summary,
    load_corpus,
    _classify_no_env_file,
    _has_runnable_code,
    _detect_external_imports,
)


def test_load_csv_corpus():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("paper_arxiv_id,paper_title,repo_url,framework,year,subfield,conference,is_official,mentioned_in_paper\n")
        f.write("2405.12299,Test Paper,https://github.com/user/repo,pytorch,2024.0,nlp,,True,True\n")
        f.write("2303.02437,Another Paper,https://github.com/user/repo2,tf,2023.0,computer_vision,CVPR,True,False\n")
        f.flush()
        corpus = load_corpus(f.name)

    assert len(corpus) == 2
    assert corpus[0].paper_arxiv_id == "2405.12299"
    assert corpus[0].framework == "pytorch"
    assert corpus[0].year == 2024
    assert corpus[1].year == 2023
    assert corpus[1].subfield == "computer_vision"


def test_load_json_corpus():
    data = [{"paper_arxiv_id": "2405.12299", "paper_title": "Test", "year": 2024, "subfield": "nlp"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        f.flush()
        corpus = load_corpus(f.name)
    assert len(corpus) == 1
    assert corpus[0].year == 2024


def test_load_corpus_missing_file():
    with pytest.raises(FileNotFoundError):
        load_corpus("/nonexistent/path.csv")


def test_load_corpus_bad_extension():
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        f.write(b"<data/>")
        f.flush()
        with pytest.raises(ValueError, match="Unsupported corpus format"):
            load_corpus(f.name)


def test_csv_handles_float_year():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("paper_arxiv_id,year\n2405.12299,2024.0\n")
        f.flush()
        assert load_corpus(f.name)[0].year == 2024


def test_csv_handles_missing_optional_fields():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("paper_arxiv_id,repo_url\n2405.12299,https://github.com/user/repo\n")
        f.flush()
        corpus = load_corpus(f.name)
    assert corpus[0].paper_arxiv_id == "2405.12299"
    assert corpus[0].framework == ""


# Failure categorization

def test_categorize_phantom_dependency():
    cat, detail, _ = categorize_failure("ERROR: No matching distribution found for fake_pkg==0.1.0")
    assert cat == "phantom_dependency"
    assert "No matching distribution" in detail


def test_categorize_build_order_dependency():
    cat, detail, _ = categorize_failure("ModuleNotFoundError: No module named 'torch'")
    assert cat == "build_order_dependency"


def test_categorize_version_conflict():
    assert categorize_failure("ERROR: ResolutionImpossible: requirements conflict")[0] == "version_conflict"


def test_categorize_platform_mismatch():
    assert categorize_failure("flash_attn.whl is not a supported wheel on this platform")[0] == "platform_mismatch"


def test_categorize_missing_system_dep():
    assert categorize_failure("fatal error: GL/gl.h: No such file or directory")[0] == "missing_system_dep"


def test_categorize_unknown_fallback():
    cat, _, stage = categorize_failure("Some random error")
    assert cat == "unknown_build_error"
    assert stage == "docker_build"


def test_categorize_with_build_log():
    cat, _, _ = categorize_failure("build failed",
        build_log="RUN pip install\nERROR: No matching distribution found for fake_pkg==0.1")
    assert cat == "phantom_dependency"


def test_categorize_preserves_explicit_stage():
    _, _, stage = categorize_failure("ModuleNotFoundError: No module named 'torch'", stage="llm_analysis")
    assert stage == "llm_analysis"


# PaperResult schema

def test_paper_result_roundtrip():
    result = PaperResult(
        paper_id="2405.12299", year=2024, subfield="nlp", framework="pytorch",
        github_found=True, build_attempted=True, build_success=False,
        failure_category="phantom_dependency", failure_detail="fake_pkg not found",
        failure_stage="docker_build", duration_seconds=42.5, timestamp="2026-02-27T15:30:00Z",
    )
    loaded = PaperResult.model_validate_json(result.model_dump_json())
    assert loaded.paper_id == "2405.12299"
    assert loaded.failure_category == "phantom_dependency"
    assert loaded.duration_seconds == 42.5


def test_paper_result_defaults():
    r = PaperResult()
    assert r.paper_id == "" and not r.github_found and not r.build_success


# Summary generation

def test_generate_summary_basic():
    results = [
        PaperResult(paper_id="a", subfield="nlp", framework="pytorch", build_success=True, failure_category="success", duration_seconds=10),
        PaperResult(paper_id="b", subfield="nlp", framework="tf", build_success=False, failure_category="phantom_dependency", failure_stage="docker_build", duration_seconds=20),
        PaperResult(paper_id="c", subfield="cv", framework="pytorch", build_success=False, failure_category="version_conflict", failure_stage="docker_build", duration_seconds=30),
        PaperResult(paper_id="d", subfield="cv", framework="pytorch", build_success=True, failure_category="success", duration_seconds=15),
    ]
    s = generate_summary(results, skipped=1)
    assert s["corpus_size"] == 5 and s["completed"] == 4 and s["skipped"] == 1
    assert s["total_duration_seconds"] == 75.0
    assert s["outcomes"] == {"success": 2, "failure": 2}
    assert s["failure_breakdown"]["phantom_dependency"] == 1
    assert s["failure_by_stage"]["docker_build"] == 2
    assert s["by_subfield"]["nlp"] == {"success": 1, "failure": 1}


def test_generate_summary_all_success():
    results = [PaperResult(paper_id="a", build_success=True, failure_category="success", duration_seconds=10)]
    s = generate_summary(results)
    assert s["outcomes"]["success"] == 1 and s["failure_breakdown"] == {}


def test_generate_summary_empty():
    s = generate_summary([])
    assert s["corpus_size"] == 0 and s["outcomes"]["success"] == 0


def test_generate_summary_includes_by_framework():
    results = [
        PaperResult(paper_id="a", framework="pytorch", build_success=True, failure_category="success"),
        PaperResult(paper_id="b", framework="tf", build_success=False, failure_category="no_env_file"),
    ]
    s = generate_summary(results)
    assert s["by_framework"]["pytorch"]["success"] == 1
    assert s["by_framework"]["tf"]["failure"] == 1


def test_resume_loads_cached_result():
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir)
        cached = PaperResult(paper_id="2405.12299", build_success=True, failure_category="success",
                             duration_seconds=50.0, timestamp="2026-01-01T00:00:00Z")
        (output / "2405.12299.json").write_text(cached.model_dump_json(indent=2))
        loaded = PaperResult.model_validate_json((output / "2405.12299.json").read_text())
        assert loaded.paper_id == "2405.12299" and loaded.build_success


# No env file classification tests

def test_classify_no_runnable_code():
    """Test classification when repo has no substantial Python code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "README.md").write_text("# My Project")
        (repo / "data.csv").write_text("a,b,c\n1,2,3")
        # Small __init__.py doesn't count as runnable code
        (repo / "__init__.py").write_text("")
        
        category, detail = _classify_no_env_file(repo)
        assert category == "no_runnable_code"
        assert "no substantial executable" in detail


def test_classify_missing_env_spec():
    """Test classification when code exists with dependencies but no env file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        # Substantial code with external dependencies
        (repo / "model.py").write_text("""
import torch
import transformers
import numpy as np

def train_model():
    model = transformers.AutoModel.from_pretrained('bert-base')
    return model
""")
        
        category, detail = _classify_no_env_file(repo)
        assert category == "missing_env_spec"
        assert "dependencies" in detail
        assert "torch" in detail or "transformers" in detail


def test_classify_self_contained():
    """Test classification when code is self-contained with only stdlib."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        # Code using only standard library
        (repo / "script.py").write_text("""
import os
import sys
import json
from pathlib import Path

def main():
    data = json.loads(Path("config.json").read_text())
    print(f"Loaded {len(data)} items")

if __name__ == "__main__":
    main()
""")
        
        category, detail = _classify_no_env_file(repo)
        assert category == "self_contained"
        assert "self-contained" in detail
        assert "stdlib only" in detail


def test_has_runnable_code_positive():
    """Test detection of runnable code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        # Substantial Python file
        (repo / "main.py").write_text("import os\n" + "print('hello')\n" * 20)
        assert _has_runnable_code(repo)


def test_has_runnable_code_negative():
    """Test no runnable code when only small files or non-code files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "README.md").write_text("# Project")
        (repo / "__init__.py").write_text("")  # Too small
        assert not _has_runnable_code(repo)


def test_has_runnable_code_ignores_hidden():
    """Test that hidden directories are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        hidden_dir = repo / ".venv"
        hidden_dir.mkdir()
        (hidden_dir / "script.py").write_text("import torch\n" * 20)
        assert not _has_runnable_code(repo)


def test_detect_external_imports():
    """Test detection of external imports."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "main.py").write_text("""
import os
import json
import torch
import transformers
from sklearn import datasets
""")
        imports = _detect_external_imports(repo)
        assert "torch" in imports
        assert "transformers" in imports
        assert "sklearn" in imports
        assert "os" not in imports  # stdlib should be filtered
        assert "json" not in imports  # stdlib should be filtered


def test_detect_external_imports_excludes_numpy():
    """Test that numpy is considered trivially obvious and excluded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "script.py").write_text("""
import numpy as np
import os
""")
        imports = _detect_external_imports(repo)
        # numpy/np are in the "trivial" list
        assert "numpy" not in imports
        assert "np" not in imports


def test_classify_handles_multiple_files():
    """Test classification works across multiple Python files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "module1.py").write_text("import os\n" * 20)
        (repo / "module2.py").write_text("import json\n" * 20)
        
        category, _ = _classify_no_env_file(repo)
        assert category == "self_contained"


def test_classify_mixed_imports():
    """Test classification when some files have stdlib only, others have external."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "utils.py").write_text("import os\nimport sys\n" * 20)
        (repo / "model.py").write_text("import tensorflow as tf\n" * 20)
        
        category, detail = _classify_no_env_file(repo)
        assert category == "missing_env_spec"
        assert "tensorflow" in detail

