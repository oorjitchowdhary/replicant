"""Pytest configuration - customize test collection."""
import pytest


def pytest_collection_modifyitems(items):
    """Filter out non-test items from non-test modules."""
    # pytest will try to collect test_bedrock_connection from llm_config.py
    # We need to remove it since it's a helper function, not a test
    items[:] = [item for item in items if not (
        "llm_config" in str(item.fspath) and "test_bedrock_connection" in item.name
    )]


def pytest_pycollect_makeitem(collector, name, obj):
    """Skip test_bedrock_connection from non-test modules."""
    # If this is test_bedrock_connection from llm_config, skip collection
    if name == "test_bedrock_connection" and hasattr(obj, "__module__"):
        if "llm_config" in obj.__module__:
            return None
    return None
