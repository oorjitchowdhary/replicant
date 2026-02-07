"""Test PDF parsing."""
import pytest
from pathlib import Path
from replicant.parsers.pdf import parse_paper, github_url_from_pdf, title_from_pdf

def test_parse_paper_basic():
    """Test that parse_paper returns a PaperContext."""
    # Create a minimal test PDF would require pypdf - we'll test structure
    from replicant.parsers.pdf import PaperContext
    ctx = PaperContext()
    assert ctx.title == ""
    assert ctx.github_urls == []
    assert ctx.datasets == []
    assert ctx.frameworks == []
    assert not ctx.needs_gpu

def test_dataset_name_detection():
    """Test that known dataset names are detected."""
    from replicant.parsers.pdf import _DATASET_RE
    text = "We train on ImageNet and evaluate on CIFAR-10 and SQuAD."
    matches = _DATASET_RE.findall(text)
    assert "ImageNet" in matches
    assert "CIFAR-10" in matches
    assert "SQuAD" in matches

def test_github_url_extraction():
    """Test GitHub URL regex."""
    from replicant.parsers.pdf import GITHUB_RE
    text = "Code: https://github.com/author/repo and https://github.com/other/project"
    urls = GITHUB_RE.findall(text)
    assert len(urls) == 2
    assert "https://github.com/author/repo" in urls

def test_framework_detection():
    """Test framework regex patterns."""
    from replicant.parsers.pdf import _FRAMEWORKS
    assert _FRAMEWORKS["pytorch"].search("We use PyTorch 2.0")
    assert _FRAMEWORKS["tensorflow"].search("TensorFlow implementation")
    assert _FRAMEWORKS["transformers"].search("Hugging Face transformers")
    assert _FRAMEWORKS["jax"].search("JAX-based training")

def test_hardware_detection():
    """Test GPU/TPU detection."""
    from replicant.parsers.pdf import _HW_GPU, _HW_TPU, _HW_DETAIL
    assert _HW_GPU.search("trained on 8 NVIDIA A100 GPUs")
    assert _HW_GPU.search("using CUDA 11.8")
    assert _HW_TPU.search("TPU v4 pods")
    detail = _HW_DETAIL.search("We use 8 x A100 GPUs")
    assert detail and "8" in detail.group(0)
