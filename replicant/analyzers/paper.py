"""Analyze research papers for environment setup information using LLM intelligence.

Extracts: title, GitHub URLs, named datasets, download URLs, framework/library
mentions, hardware requirements, model checkpoints, and setup instructions.
Uses Google Gemini AI for intelligent paper analysis.
"""
from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from replicant.sources.pdf import extract_text
from replicant.sources.arxiv import fetch

try:
    import google.genai as genai
except ImportError:
    raise ImportError(
        "google-genai is required for paper analysis. Install with: pip install google-genai"
    )


class PaperContext(BaseModel):
    """Structured environment context extracted from a research paper."""
    title: str = Field(default="", description="The title of the research paper")
    github_urls: List[str] = Field(default_factory=list, description="GitHub repository URLs mentioned in the paper")
    datasets: List[str] = Field(default_factory=list, description="Named datasets used (e.g., ImageNet, CIFAR-10, COCO, etc.)")
    download_urls: List[str] = Field(default_factory=list, description="URLs for downloading data files")
    checkpoint_urls: List[str] = Field(default_factory=list, description="URLs for downloading model weights/checkpoints")
    frameworks: List[str] = Field(default_factory=list, description="ML frameworks mentioned (pytorch, tensorflow, jax, etc.)")
    needs_gpu: bool = Field(default=False, description="Whether the paper indicates GPU requirements")
    needs_tpu: bool = Field(default=False, description="Whether the paper indicates TPU requirements")
    gpu_detail: Optional[str] = Field(default=None, description="Specific GPU requirements if mentioned (e.g., '8 x A100')")
    ram_hint: Optional[str] = Field(default=None, description="Memory requirements if mentioned (e.g., '80 GB')")
    python_version: Optional[str] = Field(default=None, description="Python version if specified")


def analyze_paper(source: str | Path) -> PaperContext:
    """Analyze a paper from PDF file path or arXiv ID for environment information."""
    from replicant.sources.arxiv import is_arxiv
    
    if isinstance(source, str) and is_arxiv(source):
        return _analyze_from_arxiv(source)
    else:
        return _analyze_from_pdf(source)


def _analyze_from_arxiv(arxiv_id: str) -> PaperContext:
    """Analyze paper from arXiv ID."""
    arxiv_data = fetch(arxiv_id)
    
    # Extract text from the downloaded PDF
    pdf_content = extract_text(arxiv_data["pdf_path"])
    
    # Combine all available text sources
    all_text_sources = [
        pdf_content.full_text,
        arxiv_data.get("abstract", ""),
        arxiv_data.get("comment", "")
    ]
    full_text = "\n\n".join(s for s in all_text_sources if s)
    
    # Use arxiv metadata for title if available, fallback to PDF
    title = arxiv_data.get("title", "") or pdf_content.title
    
    # Combine hyperlinks from PDF with any URLs in arxiv metadata
    all_hyperlinks = pdf_content.hyperlinks[:]
    
    return _extract_context(full_text, title, all_hyperlinks)


def _analyze_from_pdf(pdf_path: str | Path) -> PaperContext:
    """Analyze paper from PDF file."""
    pdf_content = extract_text(pdf_path)
    return _extract_context(pdf_content.full_text, pdf_content.title, pdf_content.hyperlinks)


def _extract_context(full_text: str, title: str, hyperlinks: list[str]) -> PaperContext:
    """Extract structured context from paper text and hyperlinks using LLM intelligence."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is required for paper analysis.\n"
            "Get your API key from: https://aistudio.google.com/app/apikey\n"
            "Set it with: export GEMINI_API_KEY=your_key_here"
        )
    
    return _extract_context_llm(full_text, title, hyperlinks)


def _extract_context_llm(full_text: str, title: str, hyperlinks: List[str]) -> PaperContext:
    """Use Gemini LLM with structured output to extract context from paper."""
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    # Prepare the prompt with paper content
    prompt = _build_analysis_prompt(full_text, title, hyperlinks)
    
    response = client.models.generate_content(
        model='gemini-3-flash-preview',
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": PaperContext.model_json_schema(),
        }
    )

    # Parse and validate the structured response
    try:
        return PaperContext.model_validate_json(response.text)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM structured response: {str(e)}\nResponse: {response.text[:500]}")


def _build_analysis_prompt(full_text: str, title: str, hyperlinks: List[str]) -> str:
    """Build the analysis prompt for the LLM."""
    # Truncate text if too long to avoid token limits
    max_text_length = 50000  # Adjust based on model limits
    if len(full_text) > max_text_length:
        # Take first part and last part to get intro + conclusion
        mid_point = max_text_length // 2
        truncated_text = full_text[:mid_point] + "\n\n[... content truncated ...]\n\n" + full_text[-mid_point:]
    else:
        truncated_text = full_text
    
    hyperlink_text = "\n".join(hyperlinks) if hyperlinks else "None"
    
    return f"""Analyze this research paper and extract environment setup information. Focus on:

- GitHub repository links mentioned in the paper text, acknowledgments, and references
- Well-known datasets by name (ImageNet, CIFAR, COCO, etc.) as well as custom datasets
- URLs for downloading data files vs model checkpoint URLs
- ML frameworks and libraries mentioned (PyTorch, TensorFlow, Hugging Face, etc.)
- Hardware requirements - GPU mentions, specific GPU models, TPU usage
- Memory/RAM requirements if specified
- Python version if mentioned

Be comprehensive but accurate - don't hallucinate information not in the paper.

Paper Title: {title}

Hyperlinks from PDF: {hyperlink_text}

Paper Content:
{truncated_text}"""