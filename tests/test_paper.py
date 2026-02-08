"""Test paper analyzer."""
import pytest
from replicant.analyzers.paper import analyze_paper, PaperContext, _extract_context


def test_paper_context_basic():
    """Test that PaperContext data structure works correctly."""
    ctx = PaperContext()
    assert ctx.title == ""
    assert ctx.github_urls == []
    assert ctx.datasets == []
    assert ctx.frameworks == []
    assert ctx.download_urls == []
    assert ctx.checkpoint_urls == []
    assert not ctx.needs_gpu
    assert not ctx.needs_tpu
    assert ctx.gpu_detail is None
    assert ctx.ram_hint is None
    assert ctx.python_version is None


def test_extract_context_github_urls():
    """Test GitHub URL extraction from text."""
    text = "Code available at https://github.com/user/repo and see https://github.com/org/project"
    hyperlinks = ["https://github.com/other/link"]
    
    ctx = _extract_context(text, "Test Paper", hyperlinks)
    
    assert len(ctx.github_urls) == 3
    assert "https://github.com/user/repo" in ctx.github_urls
    assert "https://github.com/org/project" in ctx.github_urls
    assert "https://github.com/other/link" in ctx.github_urls


def test_extract_context_datasets():
    """Test named dataset detection."""
    text = "We evaluated on ImageNet, CIFAR-10, and SQuAD datasets for comprehensive analysis."
    
    ctx = _extract_context(text, "Test Paper", [])
    
    assert "ImageNet" in ctx.datasets
    assert "CIFAR-10" in ctx.datasets  
    assert "SQuAD" in ctx.datasets


def test_extract_context_frameworks():
    """Test framework detection."""
    text = "We used PyTorch 2.0 with transformers from Hugging Face, plus TensorFlow for comparison."
    
    ctx = _extract_context(text, "Test Paper", [])
    
    assert "pytorch" in ctx.frameworks
    assert "transformers" in ctx.frameworks
    assert "tensorflow" in ctx.frameworks


def test_extract_context_hardware():
    """Test hardware requirement detection."""
    text = "Training was performed on 8 x A100 GPUs with 40GB VRAM each using CUDA 11.8."
    
    ctx = _extract_context(text, "Test Paper", [])
    
    assert ctx.needs_gpu
    assert not ctx.needs_tpu
    assert ctx.gpu_detail == "8 x A100"


def test_extract_context_python_version():
    """Test Python version extraction."""
    text = "Our implementation requires Python 3.9 or higher for compatibility."
    
    ctx = _extract_context(text, "Test Paper", [])
    
    assert ctx.python_version == "3.9"


def test_extract_context_urls():
    """Test URL classification."""
    text = """
    Download data from https://example.com/data.tar.gz
    Model weights: https://huggingface.co/model/pytorch_model.bin
    Dataset: https://drive.google.com/file/xyz
    """
    
    ctx = _extract_context(text, "Test Paper", [])
    
    # Should categorize URLs correctly
    assert any("data.tar.gz" in url for url in ctx.download_urls)
    assert any("pytorch_model.bin" in url for url in ctx.checkpoint_urls)
    assert any("drive.google.com" in url for url in ctx.download_urls)