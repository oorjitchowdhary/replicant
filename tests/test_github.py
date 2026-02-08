"""Test GitHub parsing."""
import pytest
from replicant.sources.github import _GH_RE

def test_github_url_parsing():
    """Test GitHub URL regex."""
    urls = [
        "https://github.com/user/repo",
        "http://github.com/org/project",
        "https://github.com/user/repo.git",
    ]
    for url in urls:
        m = _GH_RE.search(url)
        assert m is not None
        assert m.group(1)  # owner
        assert m.group(2)  # repo

def test_github_url_invalid():
    """Test that non-GitHub URLs don't match."""
    assert _GH_RE.search("https://gitlab.com/user/repo") is None
    assert _GH_RE.search("not a url") is None
