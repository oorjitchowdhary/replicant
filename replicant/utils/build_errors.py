"""Parse Docker build logs to extract actionable failure context for LLM retry."""
from __future__ import annotations

from pathlib import Path

_PRIORITY_TOKENS = (
    "No matching distribution found",
    "Could not find a version",
    "ResolutionImpossible",
    "ERROR:",
    "error:",
    "Failed to",
    "failed to",
    "Exception",
    "Traceback",
)


def parse_build_failure(log_path: Path) -> str:
    """Extract the most relevant failure lines from a Docker build log.

    Returns a concise string (≤50 lines) suitable for appending to an LLM prompt.
    """
    if not log_path.exists():
        return ""
    lines = log_path.read_text(errors="ignore").splitlines()
    if not lines:
        return ""

    # Find the last high-signal error line
    error_idx = -1
    for i, line in enumerate(lines):
        if any(tok in line for tok in _PRIORITY_TOKENS):
            error_idx = i

    if error_idx >= 0:
        start = max(0, error_idx - 5)
        end = min(len(lines), error_idx + 15)
        context = lines[start:end]
    else:
        context = lines[-30:]

    return "\n".join(context)
