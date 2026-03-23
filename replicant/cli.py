"""Replicant CLI."""
from __future__ import annotations
import os
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

    # Check for Bedrock bearer token
    if not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        _abort(
            "AWS_BEARER_TOKEN_BEDROCK is required.\n"
            "Set it with: export AWS_BEARER_TOKEN_BEDROCK=your_token\n"
            "Or run: replicant llm-config for help"
        )

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
    with _spin("Analyzing with AI…") as p:
        p.add_task("Analyzing with AI…")
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
    
    # Show Python version with reasoning if from AI
    python_info = spec.python_version
    if spec.resolved_deps and spec.resolved_deps.python_reason:
        python_info += f"  [dim]({spec.resolved_deps.python_reason})[/]"
    t.add_row("Python", python_info)
    
    if spec.frameworks:
        t.add_row("Frameworks", ", ".join(spec.frameworks))
    
    # Show AI-resolved dependencies with reasoning
    if spec.resolved_deps and spec.resolved_deps.dependencies:
        critical_deps = [d for d in spec.resolved_deps.dependencies if d.is_critical]
        other_deps = [d for d in spec.resolved_deps.dependencies if not d.is_critical]
        
        if critical_deps:
            dep_lines = []
            for d in critical_deps[:8]:
                dep_lines.append(f"[bold]{d.package}{d.version_spec}[/]  [dim]{d.reason}[/]")
            if len(critical_deps) > 8:
                dep_lines.append(f"… +{len(critical_deps)-8} more")
            t.add_row("🎯 Core deps", "\n".join(dep_lines))
        
        if other_deps:
            other_summary = ", ".join(f"{d.package}{d.version_spec}" for d in other_deps[:10])
            if len(other_deps) > 10:
                other_summary += f" … +{len(other_deps)-10} more"
            t.add_row("📦 Other deps", other_summary)
        
        # Show compatibility notes prominently
        if spec.resolved_deps.compatibility_notes:
            notes = "\n".join(f"⚠️  {n}" for n in spec.resolved_deps.compatibility_notes)
            t.add_row("[yellow]Compat notes[/]", notes)
    else:
        # Fallback to old package display
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
@click.argument("env_id", required=False, default=None)
@click.option("-y","--yes", is_flag=True, help="Skip confirmation prompt.")
@click.option("--keep-code", is_flag=True, help="Keep cloned repository code.")
@click.option("--all", "delete_all", is_flag=True, help="Delete all environments.")
def delete(env_id, yes, keep_code, delete_all):
    """Delete an environment (or all environments with --all)."""
    
    # Validate: need either env_id or --all
    if not env_id and not delete_all:
        _abort("Provide an environment ID or use --all to delete all environments.")
    
    if env_id and delete_all:
        _abort("Cannot specify both environment ID and --all flag.")
    
    if delete_all:
        # Delete all environments
        envs = EnvMeta.all()
        if not envs:
            con.print("[yellow]No environments to delete.[/]")
            return
        
        # Show what will be deleted
        con.print(f"[bold yellow]⚠ About to delete {len(envs)} environment(s):[/]")
        for m in envs:
            con.print(f"  • {m.env_id} ({m.source})")
        
        if not yes:
            click.confirm(f"Delete all {len(envs)} environment(s)?", abort=True)
        
        # Delete each environment
        from replicant.executors.local import remove_image
        deleted_count = 0
        for m in envs:
            try:
                remove_image(m.docker_image)
                if not keep_code and m.code_path:
                    p = Path(m.code_path)
                    if p.exists():
                        shutil.rmtree(p, ignore_errors=True)
                m.delete()
                deleted_count += 1
            except Exception as e:
                err.print(f"[yellow]Warning:[/] Failed to delete {m.env_id}: {e}")
        
        con.print(f"[green]✔[/] Deleted {deleted_count}/{len(envs)} environment(s).")
    else:
        # Delete single environment
        m = _env(env_id)
        if not yes:
            click.confirm(f"Delete '{env_id}'?", abort=True)
        from replicant.executors.local import remove_image
        remove_image(m.docker_image)
        if not keep_code and m.code_path:
            p = Path(m.code_path)
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
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


@main.command()
@click.argument("corpus_file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, type=click.Path(), help="Output directory for results (default: ~/.replicant/benchmark/).")
@click.option("--timeout", "-t", default=600, type=int, show_default=True, help="Max seconds per paper Docker build.")
@click.option("--workers", "-w", default=4, type=int, show_default=True, help="Number of parallel workers.")
@click.option("--resume", is_flag=True, help="Skip papers that already have result files.")
@click.option("--no-llm", "no_llm", is_flag=True, help="Baseline mode: skip LLM inference and build directly from raw spec files.")
@click.pass_context
def benchmark(ctx, corpus_file, output, timeout, workers, resume, no_llm):
    """Batch-run setup across a corpus of papers and collect structured failure data."""
    if not no_llm and not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        _abort("AWS_BEARER_TOKEN_BEDROCK is required. Set it with: export AWS_BEARER_TOKEN_BEDROCK=your_token")

    with _spin("Checking Docker…") as p:
        p.add_task("Checking Docker…")
        try:
            from replicant.executors.local import check_docker; check_docker()
        except RuntimeError as e: _abort(str(e))

    from replicant.benchmark import load_corpus, run_benchmark
    try:
        corpus = load_corpus(corpus_file)
    except Exception as e:
        _abort(f"Failed to load corpus: {e}")

    con.print(f"  Corpus: [cyan]{corpus_file}[/] ({len(corpus)} papers)")
    if no_llm:
        con.print("  Mode: [yellow]baseline (no LLM)[/]")
    else:
        con.print("  Mode: [green]LLM-assisted[/]")
    if resume:
        con.print("  [dim]Resume mode: skipping papers with existing results[/]")
    con.print(f"  Workers: {workers} parallel | Timeout: {timeout}s per paper\n")

    def _print_result(idx: int, total: int, pid: str, status: str, duration: float = 0):
        if status == "cached":
            con.print(f"  [{idx}/{total}] [cyan]{pid}[/] — [dim]cached (skipped)[/]")
        elif status == "success":
            con.print(f"  [{idx}/{total}] [cyan]{pid}[/] — [green]✓ success[/] [dim]({duration:.1f}s)[/]")
        else:
            con.print(f"  [{idx}/{total}] [cyan]{pid}[/] — [red]✗ {status}[/] [dim]({duration:.1f}s)[/]")

    try:
        output_dir = run_benchmark(corpus, output_dir=output, timeout=timeout, resume=resume, max_workers=workers, result_callback=_print_result, no_llm=no_llm)
    except Exception as e:
        _abort(f"Benchmark failed: {e}")

    import json as _json
    summary_path = output_dir / "summary.json"
    if summary_path.exists():
        con.print()
        _print_benchmark_summary(_json.loads(summary_path.read_text()), output_dir)


def _print_benchmark_summary(s: dict, output_dir):
    """Pretty-print the benchmark summary."""
    t = Table(title="Benchmark Summary", show_lines=True)
    t.add_column("Metric", style="bold cyan", min_width=20)
    t.add_column("Value")
    total_done = s["outcomes"]["success"] + s["outcomes"]["failure"]
    rate = (s["outcomes"]["success"] / total_done * 100) if total_done else 0
    mode_val = "[green]LLM-assisted[/]" if s.get("llm_assisted", True) else "[yellow]baseline (no LLM)[/]"
    for label, val in [
        ("Corpus size", s["corpus_size"]), ("Completed", s["completed"]),
        ("Mode", mode_val),
        ("Skipped (cached)", s["skipped"]), ("Duration", f"{s['total_duration_seconds']:.0f}s"),
        ("", ""), ("[green]Successes[/]", f"{s['outcomes']['success']}  ({rate:.0f}%)"),
        ("[red]Failures[/]", s["outcomes"]["failure"]),
    ]:
        t.add_row(str(label), str(val))
    for section, data in [("Failure breakdown", s.get("failure_breakdown")),
                          ("Failure by stage", s.get("failure_by_stage"))]:
        if data:
            t.add_row(section, "\n".join(f"{k}: {v}" for k, v in data.items()))
    if s.get("by_subfield"):
        t.add_row("By subfield", "\n".join(f"{sf}: ✔{c['success']} ✘{c['failure']}" for sf, c in s["by_subfield"].items()))
    con.print(t)
    con.print(f"\n  Results: [bold]{output_dir}[/]")
    con.print(f"  Summary: [bold]{output_dir / 'summary.json'}[/]")


@main.command(name="llm-config")
def llm_config():
    """Check and configure LLM integration."""
    from replicant.utils.llm_config import check_bedrock_setup, get_config_instructions

    is_configured, message = check_bedrock_setup()

    if is_configured:
        con.print(f"[green]✔[/] {message}")
    else:
        con.print(f"[red]✗[/] {message}")
        con.print(get_config_instructions())
        sys.exit(1)


if __name__ == "__main__":
    main()
