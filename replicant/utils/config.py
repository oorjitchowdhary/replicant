"""Paths & metadata."""
from __future__ import annotations
import hashlib, json, os, shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("REPLICANT_HOME", Path.home() / ".replicant"))
REPOS, ENVS, LOGS, BUILD = HOME/"repos", HOME/"environments", HOME/"logs", HOME/"dockerfiles"

def ensure_dirs():
    for d in (HOME, REPOS, ENVS, LOGS, BUILD): d.mkdir(parents=True, exist_ok=True)

def env_id(source: str, github_url: str) -> str:
    return hashlib.sha256(f"{source}|{github_url}".encode()).hexdigest()[:8]

@dataclass
class EnvMeta:
    env_id: str
    source: str
    github_url: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    docker_image: str = ""
    environment_file: str = ""
    paper_title: str = ""
    status: str = "pending"
    code_path: str = ""
    cloud_provider: str | None = field(default=None)
    cloud_instance_id: str | None = field(default=None)
    cloud_region: str | None = field(default=None)
    cloud_bucket: str | None = field(default=None)

    def save(self):
        ensure_dirs()
        (ENVS / f"{self.env_id}.json").write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, eid: str):
        p = ENVS / f"{eid}.json"
        if not p.exists(): raise FileNotFoundError(f"No environment '{eid}'")
        return cls(**json.loads(p.read_text()))

    @classmethod
    def all(cls):
        ensure_dirs()
        out = []
        for p in ENVS.glob("*.json"):
            try: out.append(cls(**json.loads(p.read_text())))
            except Exception: pass
        return sorted(out, key=lambda e: e.created_at, reverse=True)

    @classmethod
    def latest(cls): return (cls.all() or [None])[0]

    def delete(self):
        for p in [ENVS/f"{self.env_id}.json", LOGS/f"{self.env_id}.log"]:
            if p.exists(): p.unlink()
        d = BUILD / self.env_id
        if d.exists(): shutil.rmtree(d, ignore_errors=True)
