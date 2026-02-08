"""Fetch paper metadata + PDF from arXiv."""
from __future__ import annotations
import re
import arxiv
from replicant.utils.config import HOME, ensure_dirs

_ID_RE = re.compile(r"(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)

def is_arxiv(s: str) -> bool: 
    """Check if string looks like an arXiv ID."""
    return bool(_ID_RE.search(s))

def parse_id(s: str) -> str:
    """Extract clean arXiv ID from input string."""
    m = _ID_RE.search(s)
    if not m: raise ValueError(f"Bad arXiv ID: {s}")
    return m.group(1)

def fetch(source: str) -> dict:
    """Fetch paper PDF and metadata from arXiv."""
    aid = parse_id(source)
    ensure_dirs()
    
    paper = next(arxiv.Client().results(arxiv.Search(id_list=[aid])), None)
    if not paper: raise RuntimeError(f"No paper for '{aid}'")

    pdf_dir = HOME / "papers" 
    pdf_dir.mkdir(exist_ok=True)
    pdf_path = pdf_dir / f"{aid}.pdf"
    
    if not pdf_path.exists():
        paper.download_pdf(dirpath=str(pdf_dir), filename=f"{aid}.pdf")

    return {
        "arxiv_id": aid,
        "title": paper.title,
        "abstract": paper.summary or "",
        "comment": paper.comment or "",
        "pdf_path": str(pdf_path),
        "authors": [str(author) for author in paper.authors],
        "published": paper.published,
    }