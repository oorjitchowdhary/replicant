"""Clone GitHub repos."""
from __future__ import annotations
import re
from pathlib import Path
from git import Repo
from replicant.utils.config import REPOS, ensure_dirs

_GH_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)")

def clone(url: str, dest: Path | None = None) -> Path:
    """Clone a GitHub repository and return the local path."""
    ensure_dirs()
    m = _GH_RE.search(url)
    if not m: raise ValueError(f"Bad GitHub URL: {url}")
    owner, name = m.group(1), m.group(2).removesuffix(".git")
    dest = dest or REPOS / f"{owner}__{name}"
    clone_url = f"https://github.com/{owner}/{name}.git"
    if dest.exists() and (dest / ".git").exists():
        try: Repo(dest).remotes.origin.pull()
        except Exception: pass
    else:
        dest.mkdir(parents=True, exist_ok=True)
        Repo.clone_from(clone_url, str(dest))
    return dest