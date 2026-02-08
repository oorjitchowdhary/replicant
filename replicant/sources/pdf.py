"""Extract raw text and basic structure from PDF files."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from pypdf import PdfReader

@dataclass
class PDFContent:
    """Raw content extracted from a PDF."""
    title: str = ""
    pages: list[str] = field(default_factory=list)
    full_text: str = ""
    hyperlinks: list[str] = field(default_factory=list)

def extract_text(path: str | Path) -> PDFContent:
    """Extract raw text content from a PDF file."""
    reader = PdfReader(str(path))
    pages_text = [p.extract_text() or "" for p in reader.pages]
    full = "\n".join(pages_text)
    
    content = PDFContent(
        pages=pages_text,
        full_text=full
    )
    
    # Extract title from first substantial line of page 1
    if pages_text:
        for line in pages_text[0].splitlines():
            if len(line.strip()) > 5:
                content.title = line.strip()
                break
    
    # Extract hyperlinks from PDF annotations
    content.hyperlinks = _extract_hyperlinks(reader)
    
    return content

def _extract_hyperlinks(reader: PdfReader) -> list[str]:
    """Extract all hyperlink URLs from PDF annotations."""
    links = []
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            try:
                obj = annot.get_object()
                if "/A" in obj and "/URI" in obj["/A"]:
                    uri = obj["/A"]["/URI"]
                    if isinstance(uri, str) and uri.startswith(("http://", "https://")):
                        links.append(uri)
            except Exception:
                continue  # Skip malformed annotations
    return links