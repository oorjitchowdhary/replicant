"""Executor protocol definition."""
from __future__ import annotations
from pathlib import Path
from typing import Protocol

from replicant.utils.config import EnvMeta


class Executor(Protocol):
    def build(self, build_dir: Path, tag: str, verbose: bool) -> bool: ...
    def shell(self, meta: EnvMeta, gpu: bool) -> None: ...
    def remove_image(self, tag: str) -> None: ...
