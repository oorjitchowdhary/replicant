"""Cloud provider protocol and shared data types."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from replicant.analyzers.repo import EnvironmentSpec


class CloudProvider(Protocol):
    def provision(self, spec: "EnvironmentSpec", env_id: str) -> "CloudResources": ...
    def teardown(self, env_id: str) -> None: ...


@dataclass
class CloudResources:
    instance_ip: str
    ssh_key_path: Path
    s3_bucket: str
    instance_id: str
    region: str
