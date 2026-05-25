"""First-run onboarding wizard and config file management."""
from __future__ import annotations
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from rich.console import Console

_CONFIG_PATH = Path.home() / ".replicant" / "config.json"
_con = Console()


def load_config() -> dict:
    """Load ~/.replicant/config.json. Returns {} if missing or malformed."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    """Write cfg to ~/.replicant/config.json atomically."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _install_terraform() -> bool:
    """Try to install terraform. Returns True on success."""
    from rich.progress import Progress, SpinnerColumn, TextColumn

    system = platform.system()

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=_con, transient=True) as p:
        p.add_task("Installing Terraform…")

        # macOS — brew
        if system == "Darwin" and shutil.which("brew"):
            r = subprocess.run(
                ["brew", "tap", "hashicorp/tap"],
                capture_output=True, text=True,
            )
            if r.returncode == 0:
                r2 = subprocess.run(
                    ["brew", "install", "hashicorp/tap/terraform"],
                    capture_output=True, text=True,
                )
                if r2.returncode == 0 and shutil.which("terraform"):
                    return True
            _con.print(f"    [dim]brew install failed: {r.stderr.strip() or r2.stderr.strip()}[/]")

        # Linux — apt
        if system == "Linux" and shutil.which("apt-get"):
            cmds = [
                ["bash", "-c",
                 "wget -O- https://apt.releases.hashicorp.com/gpg | "
                 "sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg"],
                ["bash", "-c",
                 'echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] '
                 'https://apt.releases.hashicorp.com $(lsb_release -cs) main" | '
                 "sudo tee /etc/apt/sources.list.d/hashicorp.list"],
                ["sudo", "apt-get", "update", "-qq"],
                ["sudo", "apt-get", "install", "-y", "terraform"],
            ]
            success = all(subprocess.run(c, capture_output=True).returncode == 0 for c in cmds)
            if success and shutil.which("terraform"):
                return True

        # Fallback — download binary to ~/.local/bin
        try:
            import urllib.request, zipfile, io, stat
            arch = "amd64" if platform.machine() in ("x86_64", "AMD64") else "arm64"
            version = "1.9.8"
            url = f"https://releases.hashicorp.com/terraform/{version}/terraform_{version}_{system.lower()}_{arch}.zip"
            local_bin = Path.home() / ".local" / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=60) as resp:
                z = zipfile.ZipFile(io.BytesIO(resp.read()))
                z.extract("terraform", local_bin)
            tf_path = local_bin / "terraform"
            tf_path.chmod(tf_path.stat().st_mode | stat.S_IEXEC)
            os.environ["PATH"] = str(local_bin) + os.pathsep + os.environ.get("PATH", "")
            for rc in [Path.home() / ".bashrc", Path.home() / ".zshrc"]:
                if rc.exists():
                    line = f'\nexport PATH="$HOME/.local/bin:$PATH"\n'
                    if line.strip() not in rc.read_text():
                        with rc.open("a") as f:
                            f.write(line)
            return shutil.which("terraform") is not None
        except Exception as e:
            _con.print(f"    [dim]fallback install failed: {e}[/]")
            return False


def _step_terraform() -> bool:
    """Wizard step 2: ensure Terraform is installed. Returns True if available (or installed)."""
    if shutil.which("terraform"):
        _con.print("  [green]✔[/] Terraform already installed")
        return True
    _con.print("  [yellow]![/] Terraform not found — attempting install…")
    if _install_terraform():
        _con.print("  [green]✔[/] Terraform installed")
        return True
    _con.print(
        "  [yellow]⚠[/] Could not install Terraform automatically.\n"
        "    Install manually: https://developer.hashicorp.com/terraform/install\n"
        "    Cloud execution will be unavailable until Terraform is installed."
    )
    return False
