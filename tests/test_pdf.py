"""Test PDF text extraction."""
import pytest
from pathlib import Path
from replicant.sources.pdf import extract_text, PDFContent

def test_pdf_content_basic():
    """Test that PDFContent data structure works correctly."""
    content = PDFContent()
    assert content.title == ""
    assert content.pages == []
    assert content.full_text == ""
    assert content.hyperlinks == []

def test_pdf_content_with_data():
    """Test PDFContent with actual data."""
    content = PDFContent(
        title="Test Paper",
        pages=["Page 1 content", "Page 2 content"], 
        full_text="Page 1 content\nPage 2 content",
        hyperlinks=["https://example.com", "https://github.com/user/repo"]
    )
    assert content.title == "Test Paper"
    assert len(content.pages) == 2
    assert "Page 1 content" in content.full_text
    assert len(content.hyperlinks) == 2

# TODO: Add tests for actual PDF file processing once we have test fixtures
# Analysis functionality (datasets, frameworks, hardware detection) should be tested
# in the analyzer modules, not in the source extraction layer
