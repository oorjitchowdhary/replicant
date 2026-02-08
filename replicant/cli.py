"""Replicant CLI."""
from __future__ import annotations
import shutil, sys
from pathlib import Path
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from replicant.utils.config import EnvMeta, ensure_dirs, env_id

con = Console()
err = Console(stderr=True)

def _abort(msg): err.print(f"[bold red]Error:[/] {msg}"); sys.exit(1)

def _env(eid: str | None) -> EnvMeta:
    if eid:
        try: return EnvMeta.load(eid)
        except FileNotFoundError: _abort(f"No environment '{eid}'.")
    m = EnvMeta.latest()
    if not m: _abort("No environments. Run [bold]replicant setup <source>[/].")
    return m

def _spin(msg):
    from rich.progress import Progress, SpinnerColumn, TextColumn
    return Progress(SpinnerColumn(), TextColumn("{task.description}"), console=con, transient=True)


@click.group()
@click.option("--verbose", is_flag=True)
@click.pass_context
def main(ctx, verbose):
    """Replicant – turn research papers into working local environments."""
    ctx.ensure_object(dict); ctx.obj["verbose"] = verbose


@main.command()
@click.argument("source")
@click.option("--github", default=None, help="Explicit GitHub URL.")
@click.pass_context
def setup(ctx, source, github):
    """Setup environment from arXiv ID, PDF, or GitHub URL."""
    verbose = ctx.obj["verbose"]

    # docker check
    with _spin("Checking Docker…") as p:
        p.add_task("Checking Docker…")
        try:
            from replicant.executors.local import check_docker; check_docker()
        except RuntimeError as e: _abort(str(e))

    # resolve github url
    paper_title, label = "", source
    from replicant.utils.patterns import GITHUB_RE
    if github:
        pass
    elif GITHUB_RE.match(source):
        github = source.rstrip("/.")
    else:
        from replicant.sources.arxiv import is_arxiv
        if is_arxiv(source):
            with _spin("Fetching from arXiv…") as p:
                p.add_task("Fetching from arXiv…")
                from replicant.sources.arxiv import fetch
                from replicant.analyzers.paper import analyze_paper
                info = fetch(source)
                paper_ctx = analyze_paper(source)
                paper_title = info.get("title", "")
                label = f"arxiv:{info['arxiv_id']}"
                github = paper_ctx.github_urls[0] if paper_ctx.github_urls else None
        elif Path(source).expanduser().exists():
            with _spin("Reading PDF…") as p:
                p.add_task("Reading PDF…")
                from replicant.analyzers.paper import analyze_paper
                pdf = Path(source).expanduser().resolve()
                paper_ctx = analyze_paper(pdf)
                paper_title, label = paper_ctx.title, str(pdf)
                github = paper_ctx.github_urls[0] if paper_ctx.github_urls else None
        else:
            _abort(f"Can't interpret '{source}'. Use arXiv ID, PDF path, GitHub URL, or --github.")

    if not github:
        _abort("No GitHub URL found. Use [bold]--github <url>[/].")
    con.print(f"  Repo: [cyan]{github}[/]")

    # dedupe
    eid = env_id(label, github)
    try:
        existing = EnvMeta.load(eid)
        if existing.status == "ready":
            con.print(Panel(f"Already set up. Run [bold]replicant shell {eid}[/].", title="✔"))
            return
    except FileNotFoundError: pass

    # clone
    with _spin("Cloning…") as p:
        p.add_task("Cloning…")
        from replicant.sources.github import clone
        code_path = clone(github)
    con.print(f"  Cloned: [dim]{code_path}[/]")

    # resolve PDF path for analysis (arXiv download or user-supplied)
    pdf_for_analysis = None
    if label.startswith("arxiv:"):
        from replicant.utils.config import HOME
        candidate = HOME / "papers" / f"{label.split(':')[1]}.pdf"
        if candidate.exists(): pdf_for_analysis = candidate
    elif Path(source).expanduser().resolve().suffix == ".pdf":
        pdf_for_analysis = Path(source).expanduser().resolve()

    # analyze – full environment spec including paper context
    with _spin("Analyzing…") as p:
        p.add_task("Analyzing…")
        from replicant.analyzers.repo import analyze
        spec = analyze(code_path, pdf_path=pdf_for_analysis)

    if not spec.env_files:
        _abort("No environment files found (Dockerfile, environment.yml, requirements.txt, …).")

    # display full spec
    con.print()
    _print_spec(spec)
    con.print()

    # generate dockerfile
    with _spin("Generating Dockerfile…") as p:
        p.add_task("Generating Dockerfile…")
        from replicant.generators.docker import generate
        build_dir = generate(spec, eid)

    # save metadata
    tag = f"replicant-{eid}"
    meta = EnvMeta(
        env_id=eid, source=label, github_url=github,
        docker_image=tag, environment_file=spec.primary_env or "",
        paper_title=paper_title, status="building", code_path=str(code_path),
    )
    meta.save()

    # build
    con.print("[bold]Building Docker image…[/]")
    from replicant.executors.local import build
    if build(build_dir, tag, verbose=verbose):
        meta.status = "ready"; meta.save()
        con.print(Panel(
            f"[bold green]✔ Ready![/]\n  ID: [bold]{eid}[/]  Image: {tag}\n\n"
            f"  [bold cyan]replicant shell {eid}[/]",
            title="Success", border_style="green",
        ))
    else:
        meta.status = "failed"; meta.save()
        _abort(f"Build failed. Check ~/.replicant/logs/{tag}.log")


def _print_spec(spec):
    """Pretty-print the full EnvironmentSpec."""
    t = Table(title="Environment Specification", show_lines=True)
    t.add_column("Category", style="bold cyan", min_width=16)
    t.add_column("Details")

    def _trunc(items, n=15):
        s = "\n".join(items[:n])
        if len(items) > n: s += f"\n… +{len(items)-n} more"
        return s

    t.add_row("Env file", f"[green]{spec.primary_env}[/]" + (f"  (also: {', '.join(k for k in spec.env_files if k != spec.primary_env)})" if len(spec.env_files) > 1 else ""))
    t.add_row("Python", spec.python_version)
    if spec.frameworks:
        t.add_row("Frameworks", ", ".join(spec.frameworks))
    t.add_row("Packages", _trunc(spec.packages, 30) if spec.packages else "[dim]none detected[/]")
    t.add_row("Datasets", _trunc(spec.datasets) if spec.datasets else "[dim]none detected[/]")
    if spec.download_urls:
        t.add_row("Data downloads", _trunc(spec.download_urls, 10))
    if spec.checkpoint_urls:
        t.add_row("Model weights", _trunc(spec.checkpoint_urls, 10))
    if spec.download_commands:
        t.add_row("Download cmds", _trunc(spec.download_commands, 10))
    t.add_row("Entrypoints", "\n".join(spec.entrypoints) if spec.entrypoints else "[dim]none detected[/]")

    hw = []
    if spec.needs_gpu: hw.append(f"🖥  GPU" + (f" ({spec.gpu_detail})" if spec.gpu_detail else " (CUDA)"))
    if spec.needs_tpu: hw.append("⚡ TPU")
    if spec.ram_hint: hw.append(f"💾 {spec.ram_hint}")
    if not hw: hw.append("[dim]standard[/]")
    t.add_row("Hardware", "  ".join(hw))

    if spec.readme_setup:
        t.add_row("README setup", spec.readme_setup[:500] + ("…" if len(spec.readme_setup) > 500 else ""))

    con.print(t)


@main.command()
@click.argument("env_id", required=False, default=None)
@click.option("--gpu/--no-gpu", default=False)
def shell(env_id, gpu):
    """Enter an environment shell."""
    meta = _env(env_id)
    if meta.status != "ready": _abort(f"Not ready (status: {meta.status}).")
    con.print(f"Entering [bold]{meta.env_id}[/] …")
    from replicant.executors.local import shell as sh; sh(meta, gpu=gpu)


@main.command(name="list")
def list_envs():
    """List environments."""
    envs = EnvMeta.all()
    if not envs: con.print("No environments."); return
    t = Table(title="Environments")
    t.add_column("ID", style="bold"); t.add_column("Status"); t.add_column("Source"); t.add_column("Created")
    for e in envs:
        st = {"ready":"green","building":"yellow","failed":"red"}.get(e.status,"dim")
        t.add_row(e.env_id, f"[{st}]{e.status}[/]", e.source[:50], e.created_at[:19])
    con.print(t)


@main.command()
@click.argument("env_id", required=False, default=None)
def info(env_id):
    """Show environment details."""
    m = _env(env_id)
    t = Table(show_header=False, box=None)
    t.add_column("K", style="bold cyan", min_width=16); t.add_column("V")
    for k,v in [("ID",m.env_id),("Status",m.status),("Source",m.source),("GitHub",m.github_url),
                ("Title",m.paper_title or "-"),("Image",m.docker_image),("Env file",m.environment_file),
                ("Code",m.code_path),("Created",m.created_at)]:
        t.add_row(k,v)
    con.print(Panel(t, title=f"Environment {m.env_id}", border_style="cyan"))


@main.command()
@click.argument("env_id")
@click.option("-y","--yes", is_flag=True)
@click.option("--keep-code", is_flag=True)
def delete(env_id, yes, keep_code):
    """Delete an environment."""
    m = _env(env_id)
    if not yes: click.confirm(f"Delete '{env_id}'?", abort=True)
    from replicant.executors.local import remove_image
    remove_image(m.docker_image)
    if not keep_code and m.code_path:
        p = Path(m.code_path)
        if p.exists(): shutil.rmtree(p, ignore_errors=True)
    m.delete()
    con.print(f"[green]✔[/] Deleted [bold]{env_id}[/].")


@main.command()
@click.argument("env_id", required=False, default=None)
def validate(env_id):
    """Validate an environment."""
    m = _env(env_id)
    from replicant.utils.validation import validate as val
    results = val(m)
    ok = True
    for r in results:
        icon = "[green]✔[/]" if r.passed else "[red]✘[/]"
        con.print(f"  {icon} [bold]{r.name}[/]: {r.msg}")
        if not r.passed: ok = False
    con.print("[bold green]All passed.[/]" if ok else "[bold red]Some failed.[/]")
    if not ok: sys.exit(1)


if __name__ == "__main__":
    main()
