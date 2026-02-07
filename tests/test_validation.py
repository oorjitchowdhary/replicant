"""Test validation utilities."""
import pytest
from replicant.utils.validation import Check

def test_check_dataclass():
    """Test Check dataclass structure."""
    check = Check(name="test", passed=True, msg="success")
    assert check.name == "test"
    assert check.passed
    assert check.msg == "success"

def test_check_failed():
    """Test failed check."""
    check = Check(name="build", passed=False, msg="Image not found")
    assert not check.passed
    assert "not found" in check.msg
