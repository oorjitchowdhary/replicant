"""Test arXiv parsing."""
import pytest
from replicant.parsers.arxiv import is_arxiv, parse_id

def test_is_arxiv():
    """Test arXiv ID detection."""
    assert is_arxiv("2301.12345")
    assert is_arxiv("arxiv:2301.12345")
    assert is_arxiv("https://arxiv.org/abs/2301.12345")
    assert not is_arxiv("github.com/user/repo")
    assert not is_arxiv("random text")

def test_parse_id():
    """Test arXiv ID extraction."""
    assert parse_id("2301.12345") == "2301.12345"
    assert parse_id("arxiv:2301.12345") == "2301.12345"
    assert parse_id("arxiv:2301.12345v2") == "2301.12345v2"
    
def test_parse_id_invalid():
    """Test that invalid IDs raise ValueError."""
    with pytest.raises(ValueError):
        parse_id("not-an-arxiv-id")
