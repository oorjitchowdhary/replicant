"""Analyze research papers for environment setup information.

Extracts: title, GitHub URLs, named datasets, download URLs, framework/library
mentions, hardware requirements, model checkpoints, and setup instructions.
Uses LLM intelligence for smart paper analysis instead of brittle regex patterns.
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from replicant.sources.pdf import extract_text
from replicant.sources.arxiv import fetch
from replicant.utils.patterns import GITHUB_RE

# Import for LLM-based analysis
try:
    import google.genai as genai
except ImportError:
    genai = None

# ── Well-known dataset names (case-insensitive whole-word match) ────────────
_KNOWN_DATASETS = [
    "ImageNet", "CIFAR-10", "CIFAR-100", "MNIST", "Fashion-MNIST", "SVHN",
    "COCO", "MS-COCO", "VOC", "Pascal VOC", "ADE20K", "Cityscapes",
    "LSUN", "CelebA", "CelebA-HQ", "FFHQ", "LFW",
    "SQuAD", "GLUE", "SuperGLUE", "MNLI", "SST-2", "QNLI", "QQP", "MRPC",
    "WikiText", "WikiText-2", "WikiText-103", "C4", "The Pile", "OpenWebText",
    "BookCorpus", "CommonCrawl", "RedPajama",
    "LibriSpeech", "Common Voice", "AudioSet", "VoxCeleb",
    "Kinetics-400", "Kinetics-600", "Kinetics-700", "UCF101", "HMDB51",
    "WMT", "IWSLT", "Multi30k",
    "ShapeNet", "ModelNet", "ScanNet", "NYU Depth",
    "LAION", "LAION-5B", "LAION-400M", "CC3M", "CC12M",
    "nuScenes", "KITTI", "Waymo Open", "Argoverse",
]
_DATASET_RE = re.compile(
    r"\b(" + "|".join(re.escape(d) for d in _KNOWN_DATASETS) + r")\b", re.I
)

# ── Framework / library mentions ────────────────────────────────────────────
_FRAMEWORKS = {
    "pytorch": re.compile(r"\bPyTorch\b", re.I),
    "tensorflow": re.compile(r"\bTensorFlow\b", re.I),
    "jax": re.compile(r"\bJAX\b"),
    "keras": re.compile(r"\bKeras\b", re.I),
    "transformers": re.compile(r"\bHugging\s*Face\b|\btransformers\b", re.I),
    "diffusers": re.compile(r"\bdiffusers\b", re.I),
    "opencv": re.compile(r"\bOpenCV\b", re.I),
    "scipy": re.compile(r"\bSciPy\b", re.I),
    "sklearn": re.compile(r"\bscikit-learn\b|\bsklearn\b", re.I),
    "pandas": re.compile(r"\bpandas\b", re.I),
    "numpy": re.compile(r"\bNumPy\b", re.I),
    "wandb": re.compile(r"\bW&B\b|\bwandb\b|\bWeights\s*&\s*Biases\b", re.I),
    "detectron2": re.compile(r"\bDetectron2\b", re.I),
    "mmdet": re.compile(r"\bMMDetection\b|\bmmdet\b", re.I),
    "flash-attn": re.compile(r"\bFlashAttention\b|\bflash.attn\b", re.I),
    "deepspeed": re.compile(r"\bDeepSpeed\b", re.I),
    "accelerate": re.compile(r"\bAccelerate\b", re.I),
    "vllm": re.compile(r"\bvLLM\b", re.I),
}

# ── Hardware ────────────────────────────────────────────────────────────────
_HW_GPU = re.compile(
    r"\b(?:CUDA|NVIDIA|GPU|V100|A100|A6000|H100|RTX|P100|T4|"
    r"DGX|nccl|mixed.precision|fp16|bf16|apex)\b", re.I
)
_HW_TPU = re.compile(r"\bTPU\b|\bXLA\b|\bcloud.tpu\b", re.I)
_HW_DETAIL = re.compile(
    r"(\d+)\s*[×x]\s*(A100|V100|H100|A6000|TPU.v\d|RTX\s*\d+|P100|T4)", re.I
)
_HW_RAM = re.compile(r"(\d+)\s*(?:GB|TB)\s*(?:RAM|memory|VRAM|GPU\s*memory)", re.I)

# ── Download URLs / checkpoints ─────────────────────────────────────────────
_URL_RE = re.compile(r"https?://\S+")
_WEIGHT_HINTS = re.compile(
    r"checkpoint|pretrained|weight|model.zoo|\.pth|\.pt|\.ckpt|\.safetensors|\.bin", re.I
)
_DATA_EXTENSIONS = re.compile(
    r"\.tar\.gz|\.zip|\.h5|\.hdf5|\.csv|\.tsv|\.jsonl?|\.parquet|\.tfrecord|\.npz|\.npy"
)

# ── Well-known dataset names (case-insensitive whole-word match) ────────────
_KNOWN_DATASETS = [
    "ImageNet", "CIFAR-10", "CIFAR-100", "MNIST", "Fashion-MNIST", "SVHN",
    "COCO", "MS-COCO", "VOC", "Pascal VOC", "ADE20K", "Cityscapes",
    "LSUN", "CelebA", "CelebA-HQ", "FFHQ", "LFW",
    "SQuAD", "GLUE", "SuperGLUE", "MNLI", "SST-2", "QNLI", "QQP", "MRPC",
    "WikiText", "WikiText-2", "WikiText-103", "C4", "The Pile", "OpenWebText",
    "BookCorpus", "CommonCrawl", "RedPajama",
    "LibriSpeech", "Common Voice", "AudioSet", "VoxCeleb",
    "Kinetics-400", "Kinetics-600", "Kinetics-700", "UCF101", "HMDB51",
    "WMT", "IWSLT", "Multi30k",
    "ShapeNet", "ModelNet", "ScanNet", "NYU Depth",
    "LAION", "LAION-5B", "LAION-400M", "CC3M", "CC12M",
    "nuScenes", "KITTI", "Waymo Open", "Argoverse",
]
_DATASET_RE = re.compile(
    r"\b(" + "|".join(re.escape(d) for d in _KNOWN_DATASETS) + r")\b", re.I
)

# ── Framework / library mentions ────────────────────────────────────────────
_FRAMEWORKS = {
    "pytorch": re.compile(r"\bPyTorch\b", re.I),
    "tensorflow": re.compile(r"\bTensorFlow\b", re.I),
    "jax": re.compile(r"\bJAX\b"),
    "keras": re.compile(r"\bKeras\b", re.I),
    "transformers": re.compile(r"\bHugging\s*Face\b|\btransformers\b", re.I),
    "diffusers": re.compile(r"\bdiffusers\b", re.I),
    "opencv": re.compile(r"\bOpenCV\b", re.I),
    "scipy": re.compile(r"\bSciPy\b", re.I),
    "sklearn": re.compile(r"\bscikit-learn\b|\bsklearn\b", re.I),
    "pandas": re.compile(r"\bpandas\b", re.I),
    "numpy": re.compile(r"\bNumPy\b", re.I),
    "wandb": re.compile(r"\bW&B\b|\bwandb\b|\bWeights\s*&\s*Biases\b", re.I),
    "detectron2": re.compile(r"\bDetectron2\b", re.I),
    "mmdet": re.compile(r"\bMMDetection\b|\bmmdet\b", re.I),
    "flash-attn": re.compile(r"\bFlashAttention\b|\bflash.attn\b", re.I),
    "deepspeed": re.compile(r"\bDeepSpeed\b", re.I),
    "accelerate": re.compile(r"\bAccelerate\b", re.I),
    "vllm": re.compile(r"\bvLLM\b", re.I),
}

# ── Hardware ────────────────────────────────────────────────────────────────
_HW_GPU = re.compile(
    r"\b(?:CUDA|NVIDIA|GPU|V100|A100|A6000|H100|RTX|P100|T4|"
    r"DGX|nccl|mixed.precision|fp16|bf16|apex)\b", re.I
)
_HW_TPU = re.compile(r"\bTPU\b|\bXLA\b|\bcloud.tpu\b", re.I)
_HW_DETAIL = re.compile(
    r"(\d+)\s*[×x]\s*(A100|V100|H100|A6000|TPU.v\d|RTX\s*\d+|P100|T4)", re.I
)
_HW_RAM = re.compile(r"(\d+)\s*(?:GB|TB)\s*(?:RAM|memory|VRAM|GPU\s*memory)", re.I)

# ── Download URLs / checkpoints ─────────────────────────────────────────────
_URL_RE = re.compile(r"https?://\S+")
_WEIGHT_HINTS = re.compile(
    r"checkpoint|pretrained|weight|model.zoo|\.pth|\.pt|\.ckpt|\.safetensors|\.bin", re.I
)
_DATA_EXTENSIONS = re.compile(
    r"\.tar\.gz|\.zip|\.h5|\.hdf5|\.csv|\.tsv|\.jsonl?|\.parquet|\.tfrecord|\.npz|\.npy"
)


@dataclass
class PaperContext:
    """Structured environment context extracted from a research paper."""
    title: str = ""
    github_urls: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)          # named datasets
    download_urls: list[str] = field(default_factory=list)     # data download links
    checkpoint_urls: list[str] = field(default_factory=list)   # model weight links
    frameworks: list[str] = field(default_factory=list)        # pytorch, tensorflow, etc.
    needs_gpu: bool = False
    needs_tpu: bool = False
    gpu_detail: str | None = None                              # e.g. "8 x A100"
    ram_hint: str | None = None                                # e.g. "80 GB"
    python_version: str | None = None


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
    # Try LLM-based analysis first, fallback to regex if needed
    if genai and os.getenv("GEMINI_API_KEY"):
        try:
            return _extract_context_llm(full_text, title, hyperlinks)
        except Exception as e:
            print(f"Warning: LLM analysis failed ({e}), falling back to regex")
    
    # Fallback to original regex-based approach
    return _extract_context_regex(full_text, title, hyperlinks)


def _extract_context_llm(full_text: str, title: str, hyperlinks: list[str]) -> PaperContext:
    """Use Gemini LLM to intelligently extract context from paper."""
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    # Prepare the prompt with paper content
    prompt = _build_analysis_prompt(full_text, title, hyperlinks)
    
    response = client.models.generate_content(
        model='gemini-1.5-flash',
        contents=prompt
    )
    
    try:
        # Parse the JSON response
        result = json.loads(response.text)
        
        return PaperContext(
            title=result.get("title", title),
            github_urls=result.get("github_urls", []),
            datasets=result.get("datasets", []),
            download_urls=result.get("download_urls", []),
            checkpoint_urls=result.get("checkpoint_urls", []),
            frameworks=result.get("frameworks", []),
            needs_gpu=result.get("needs_gpu", False),
            needs_tpu=result.get("needs_tpu", False),
            gpu_detail=result.get("gpu_detail"),
            ram_hint=result.get("ram_hint"),
            python_version=result.get("python_version")
        )
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse LLM response as JSON: {response.text[:500]}")


def _build_analysis_prompt(full_text: str, title: str, hyperlinks: list[str]) -> str:
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
    
    return f"""Analyze this research paper and extract environment setup information. Return a JSON object with the following structure:

{{"title": "string",
"github_urls": ["list of GitHub repository URLs mentioned in the paper"],
"datasets": ["list of named datasets used (e.g., ImageNet, CIFAR-10, COCO, etc.)"],
"download_urls": ["list of URLs for downloading data files"],
"checkpoint_urls": ["list of URLs for downloading model weights/checkpoints"],
"frameworks": ["list of ML frameworks mentioned (pytorch, tensorflow, jax, etc.)"],
"needs_gpu": boolean,
"needs_tpu": boolean,
"gpu_detail": "string describing specific GPU requirements if mentioned",
"ram_hint": "string describing memory requirements if mentioned",
"python_version": "string with Python version if specified"
}}

Instructions:
- Look for GitHub repository links in the paper text, acknowledgments, and references
- Identify well-known datasets by name (ImageNet, CIFAR, COCO, etc.) as well as custom datasets
- Distinguish between data download URLs and model checkpoint URLs
- Detect ML frameworks and libraries mentioned (PyTorch, TensorFlow, Hugging Face, etc.)
- Look for hardware requirements - GPU mentions, specific GPU models, TPU usage
- Find memory/RAM requirements if specified
- Extract Python version if mentioned
- Be comprehensive but accurate - don't hallucinate information not in the paper

Paper Title: {title}

Hyperlinks from PDF: {hyperlink_text}

Paper Content:
{truncated_text}

Return only the JSON object, no other text."""


def _extract_context_regex(full_text: str, title: str, hyperlinks: list[str]) -> PaperContext:
    """Fallback regex-based context extraction (original implementation)."""
    ctx = PaperContext(title=title)

    # GitHub URLs from text and hyperlinks
    seen_urls: set[str] = set()
    
    # From text content
    for url in GITHUB_RE.findall(full_text):
        clean = url.rstrip("/.")
        if clean not in seen_urls:
            seen_urls.add(clean)
            ctx.github_urls.append(clean)
    
    # From PDF hyperlink annotations
    for url in hyperlinks:
        if GITHUB_RE.match(url):
            clean = url.rstrip("/.")
            if clean not in seen_urls:
                seen_urls.add(clean)
                ctx.github_urls.append(clean)

    # Named datasets
    seen_ds: set[str] = set()
    for m in _DATASET_RE.finditer(full_text):
        name = m.group(1)
        key = name.lower()
        if key not in seen_ds:
            seen_ds.add(key)
            ctx.datasets.append(name)

    # URLs — classify into data downloads vs checkpoints vs ignore
    for url in _URL_RE.findall(full_text):
        url = url.rstrip(".,;:)\"'")
        if "github.com" in url: 
            continue  # Already handled above
        if _WEIGHT_HINTS.search(url):
            if url not in ctx.checkpoint_urls: 
                ctx.checkpoint_urls.append(url)
        elif _DATA_EXTENSIONS.search(url):
            if url not in ctx.download_urls: 
                ctx.download_urls.append(url)
        elif "drive.google.com" in url or "huggingface.co" in url:
            if url not in ctx.download_urls: 
                ctx.download_urls.append(url)

    # Frameworks
    for name, pat in _FRAMEWORKS.items():
        if pat.search(full_text): 
            ctx.frameworks.append(name)

    # Hardware
    ctx.needs_gpu = bool(_HW_GPU.search(full_text))
    ctx.needs_tpu = bool(_HW_TPU.search(full_text))
    if m := _HW_DETAIL.search(full_text):
        ctx.gpu_detail = m.group(0)
    if m := _HW_RAM.search(full_text):
        ctx.ram_hint = m.group(0)

    # Python version (rare but some papers mention it)
    if m := re.search(r"Python\s+(\d+\.\d+)", full_text):
        ctx.python_version = m.group(1)

    return ctx