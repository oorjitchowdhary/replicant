"""Parse a research paper PDF for everything useful to env setup.

Extracts: title, GitHub URLs, named datasets, download URLs, framework/library
mentions, hardware requirements, model checkpoints, and setup instructions.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from pypdf import PdfReader

GITHUB_RE = re.compile(r"https?://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+")

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
    """Structured context extracted from a research paper PDF."""
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


def parse_paper(path: str | Path) -> PaperContext:
    """Extract everything useful from a PDF for environment setup."""
    reader = PdfReader(str(path))
    pages_text = [p.extract_text() or "" for p in reader.pages]
    full = "\n".join(pages_text)
    ctx = PaperContext()

    # title = first substantial line of page 1
    for line in pages_text[0].splitlines():
        if len(line.strip()) > 5:
            ctx.title = line.strip(); break

    # github
    seen_urls: set[str] = set()
    for url in GITHUB_RE.findall(full):
        clean = url.rstrip("/.")
        if clean not in seen_urls:
            seen_urls.add(clean); ctx.github_urls.append(clean)
    # also from hyperlink annotations
    for page in reader.pages:
        for annot in (page.get("/Annots") or []):
            obj = annot.get_object()
            if "/A" in obj and "/URI" in obj["/A"]:
                uri = obj["/A"]["/URI"]
                if GITHUB_RE.match(uri):
                    clean = uri.rstrip("/.")
                    if clean not in seen_urls:
                        seen_urls.add(clean); ctx.github_urls.append(clean)

    # named datasets
    seen_ds: set[str] = set()
    for m in _DATASET_RE.finditer(full):
        name = m.group(1)
        key = name.lower()
        if key not in seen_ds:
            seen_ds.add(key); ctx.datasets.append(name)

    # URLs — classify into data downloads vs checkpoints vs ignore
    for url in _URL_RE.findall(full):
        url = url.rstrip(".,;:)\"'")
        if "github.com" in url: continue
        if _WEIGHT_HINTS.search(url):
            if url not in ctx.checkpoint_urls: ctx.checkpoint_urls.append(url)
        elif _DATA_EXTENSIONS.search(url):
            if url not in ctx.download_urls: ctx.download_urls.append(url)
        elif "drive.google.com" in url or "huggingface.co" in url:
            if url not in ctx.download_urls: ctx.download_urls.append(url)

    # frameworks
    for name, pat in _FRAMEWORKS.items():
        if pat.search(full): ctx.frameworks.append(name)

    # hardware
    ctx.needs_gpu = bool(_HW_GPU.search(full))
    ctx.needs_tpu = bool(_HW_TPU.search(full))
    if m := _HW_DETAIL.search(full):
        ctx.gpu_detail = m.group(0)
    if m := _HW_RAM.search(full):
        ctx.ram_hint = m.group(0)

    # python version (rare but some papers mention it)
    if m := re.search(r"Python\s+(\d+\.\d+)", full):
        ctx.python_version = m.group(1)

    return ctx


# ── Convenience wrappers (used by parsers/arxiv.py and cli.py) ──────────────

def github_url_from_pdf(path: str | Path) -> str | None:
    ctx = parse_paper(path)
    return ctx.github_urls[0] if ctx.github_urls else None

def title_from_pdf(path: str | Path) -> str:
    ctx = parse_paper(path)
    return ctx.title
