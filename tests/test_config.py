"""Test config and metadata."""
import pytest
import tempfile
import shutil
from pathlib import Path
from replicant.utils.config import env_id, EnvMeta, ENVS, ensure_dirs

def test_env_id_deterministic():
    """Test that env_id is deterministic."""
    id1 = env_id("arxiv:2301.12345", "https://github.com/user/repo")
    id2 = env_id("arxiv:2301.12345", "https://github.com/user/repo")
    assert id1 == id2
    assert len(id1) == 8

def test_env_id_different():
    """Test that different inputs produce different IDs."""
    id1 = env_id("arxiv:2301.12345", "https://github.com/user/repo1")
    id2 = env_id("arxiv:2301.12345", "https://github.com/user/repo2")
    assert id1 != id2

def test_env_meta_save_load():
    """Test EnvMeta save and load."""
    ensure_dirs()
    meta = EnvMeta(
        env_id="test123",
        source="test",
        github_url="https://github.com/test/test",
        status="ready",
    )
    meta.save()
    
    loaded = EnvMeta.load("test123")
    assert loaded.env_id == "test123"
    assert loaded.source == "test"
    assert loaded.status == "ready"
    
    # cleanup
    loaded.delete()

def test_env_meta_all():
    """Test EnvMeta.all() returns sorted list."""
    ensure_dirs()
    meta1 = EnvMeta(env_id="a", source="test1", github_url="url1")
    meta2 = EnvMeta(env_id="b", source="test2", github_url="url2")
    meta1.save()
    meta2.save()
    
    all_envs = EnvMeta.all()
    assert len(all_envs) >= 2
    # newest first
    assert all_envs[0].created_at >= all_envs[-1].created_at
    
    # cleanup
    meta1.delete()
    meta2.delete()

def test_env_meta_latest():
    """Test EnvMeta.latest() returns most recent."""
    ensure_dirs()
    meta = EnvMeta(env_id="latest", source="test", github_url="url")
    meta.save()
    
    latest = EnvMeta.latest()
    assert latest is not None
    assert latest.env_id == "latest"
    
    meta.delete()
