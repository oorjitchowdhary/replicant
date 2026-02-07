"""Fetch paper metadata + PDF from arXiv."""
from __future__ import annotations
import re
import arxiv
from replicant.parsers.pdf import GITHUB_RE, github_url_from_pdf
from replicant.utils.config import HOME, ensure_dirs

_ID_RE = re.compile(r"(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)

def is_arxiv(s: str) -> bool: return bool(_ID_RE.search(s))

def parse_id(s: str) -> str:
    m = _ID_RE.search(s)
    if not m: raise ValueError(f"Bad arXiv ID: {s}")
    return m.group(1)

def fetch(source: str) -> dict:
    aid = parse_id(source)
    ensure_dirs()
    paper = next(arxiv.Client().results(arxiv.Search(id_list=[aid])), None)
    if not paper: raise RuntimeError(f"No paper for '{aid}'")

    pdf_dir = HOME / "papers"; pdf_dir.mkdir(exist_ok=True)
    pdf_path = pdf_dir / f"{aid}.pdf"
    if not pdf_path.exists():
        paper.download_pdf(dirpath=str(pdf_dir), filename=f"{aid}.pdf")

    # hunt for github url: abstract → comment → pdf body
    gh = None
    for text in [paper.summary or "", paper.comment or ""]:
        if urls := GITHUB_RE.findall(text):
            gh = urls[0].rstrip("/."); break
    if not gh:
        gh = github_url_from_pdf(pdf_path)

    return {"arxiv_id": aid, "title": paper.title, "pdf_path": str(pdf_path), "github_url": gh}
