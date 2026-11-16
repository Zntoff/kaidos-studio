"""Command line entry point. Run `python -m clipper --help`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .agents import output
from .agents.base import Context
from .agents.orchestrator import Orchestrator
from .config import CAPTION_CHOICES, LAYOUT_CHOICES, TIERS, VALID_RIGHTS, Settings
from . import ai_settings
from .llm import LLMError, PendingAnswer, make_llm
from .media import download
from .rights import RightsError, register_source
from .store import Store

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Kairos Studio: AI clipping (Claude, OpenAI, Gemini and other providers).")
source_app = typer.Typer(no_args_is_help=True, help="Rights registry for source videos.")
app.add_typer(source_app, name="source")


def _env(offline: bool = False, languages: Optional[str] = None, **choices) -> tuple[Settings, Store]:
    """Settings from the environment plus the choices given on the command line (model, layout...)."""
    langs = [x.strip() for x in (languages or "").split(",") if x.strip()]
    try:
        s = Settings.from_env().apply_options({"llm": "offline" if offline else None, "languages": langs, **choices})
    except ValueError as e:
        _fail(str(e))
    return s, Store(s.database_url)


def _fail(msg: str) -> None:
    typer.secho(f"Error: {msg}", fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@source_app.command("add")
def source_add(
    path: str = typer.Argument(..., help="Local video file, or a YouTube / Twitch / Kick link."),
    rights: str = typer.Option(..., "--rights", help=f"Rights status: {' | '.join(VALID_RIGHTS)}"),
    evidence: str = typer.Option(..., "--evidence", help="Evidence: link to the permission, a file, or a description (e.g. 'my own recording, PS5, 2026-11-19')."),
    credit: Optional[str] = typer.Option(None, "--credit", help="Credit to the original creator; added to the descriptions."),
    language: Optional[str] = typer.Option(None, "--language", help="Spoken language (en, es...). If omitted, Whisper detects it."),
):
    """Register a video. Without a rights status and evidence, the video doesn't enter the pipeline."""
    s, store = _env()
    try:
        if download.is_url(path):
            if rights not in VALID_RIGHTS or len((evidence or "").strip()) < 8:  # fail before downloading
                _fail(f"Invalid rights status or missing evidence. Values: {', '.join(VALID_RIGHTS)}")
            file, meta = download.fetch(path, s.data_dir / "downloads", typer.echo)
            credit = credit or meta.get("uploader")
        else:
            file = Path(path)
        rec = register_source(store, file, rights_status=rights, evidence=evidence, credit=credit, language=language)
    except (RightsError, download.DownloadError) as e:
        _fail(str(e))
    typer.echo(f"{rec.id}  {rec.duration:.0f}s  {rec.width}x{rec.height}  {rec.rights_status}  {rec.path}")


@source_app.command("list")
def source_list():
    _, store = _env()
    for r in store.list_sources():
        typer.echo(f"{r['id']}  {r['duration']:.0f}s  {r['rights_status']}  {r['path']}")


@app.command()
def run(
    source: str = typer.Argument(..., help="Source id (src_...) returned by `source add`."),
    offline: bool = typer.Option(False, "--offline", help="No AI: heuristics to test the pipeline. Nothing is approved."),
    transcript: Optional[Path] = typer.Option(None, "--transcript", help="Existing JSON transcript (skips Whisper)."),
    max_clips: Optional[int] = typer.Option(None, "--max-clips"),
    languages: Optional[str] = typer.Option(None, "--languages", help="Output languages, e.g. en,es"),
    model: Optional[str] = typer.Option(None, "--model", help=f"Model for everything after the analysis: {' | '.join(TIERS)} (default: each subagent's own)."),
    analysis_model: Optional[str] = typer.Option(None, "--analysis-model", help=f"Analysis model: {' | '.join(TIERS)}"),
    layout: Optional[str] = typer.Option(None, "--layout", help=f"Framing: {' | '.join(LAYOUT_CHOICES)}"),
    caption_style: Optional[str] = typer.Option(None, "--caption-style", help=f"Captions: {' | '.join(CAPTION_CHOICES)}"),
):
    """Process a video end to end: analysis, editing, captions, metadata, render, review and package.
    To choose the moments yourself before generating, use `analyze` and then `generate`."""
    s, store = _env(offline, languages, model=model, analysis_model=analysis_model, layout=layout, caption_style=caption_style)
    _run(s, store, source, transcript=str(transcript) if transcript else None, max_clips=max_clips)


def _run(s: Settings, store: Store, source: str | None = None, **kw) -> None:
    try:
        ctx = Context(settings=s, store=store, llm=make_llm(s.llm_provider, s.api_key, s.data_dir / 'replay', on_usage=ai_settings.Ledger(s.data_dir, s.ai_provider).add, settings=s, log=typer.echo), log=typer.echo)
        summary = Orchestrator(ctx).run(source, **kw)
    except (ValueError, LLMError, PendingAnswer) as e:
        _fail(str(e))
    _print_summary(summary)


@app.command()
def analyze(
    source: str = typer.Argument(..., help="Source id (src_...)."),
    offline: bool = typer.Option(False, "--offline"),
    transcript: Optional[Path] = typer.Option(None, "--transcript", help="Existing JSON transcript (skips Whisper)."),
    analysis_model: Optional[str] = typer.Option(None, "--analysis-model", help=f"{' | '.join(TIERS)}"),
):
    """Find the key moments and stop: no clip is generated until you choose with `generate`."""
    s, store = _env(offline, analysis_model=analysis_model)
    _run(s, store, source, transcript=str(transcript) if transcript else None, review=True)
    job = max(store.list_jobs(), key=lambda j: j["created_at"])
    typer.echo(f"\nSuggested moments for job {job['id']}:")
    st = store.get_done_step(job["id"], None, "analysis", "analysis")
    for c in (st["output"]["candidates"] if st else []):
        typer.echo(f"  {c['id']}  {c['start']:.0f}-{c['end']:.0f}s  score {c['score']:.0f}  [{c['category']}] {c['reason'][:90]}")
    typer.echo(f"\nGenerate the ones you want:  clipper generate {job['id']} --pick cand00,cand02 --model standard")


@app.command()
def generate(
    job_id: str = typer.Argument(..., help="Job analyzed with `analyze`."),
    pick: str = typer.Option(..., "--pick", help="Moment ids, comma separated (cand00,cand02)."),
    model: str = typer.Option("standard", "--model", help=f"Model for everything after the analysis: {' | '.join(TIERS)}"),
    layout: str = typer.Option("auto", "--layout", help=f"{' | '.join(LAYOUT_CHOICES)}"),
    caption_style: str = typer.Option("auto", "--caption-style", help=f"{' | '.join(CAPTION_CHOICES)}"),
    languages: Optional[str] = typer.Option(None, "--languages"),
    offline: bool = typer.Option(False, "--offline"),
):
    """Generate the clips for the chosen moments, with the model and styles you specify."""
    _, store = _env()
    job = store.get_job(job_id)
    if not job:
        _fail(f"Job {job_id} does not exist")
    ids = [x.strip() for x in pick.split(",") if x.strip()]
    options = {**job["options"], "model": model, "layout": layout, "caption_style": caption_style, "selection": ids, "review": True}
    if languages:
        options["languages"] = [x.strip() for x in languages.split(",") if x.strip()]
    if offline:
        options["llm"] = "offline"
    s, store = _env(**{k: v for k, v in options.items() if k != "languages"}, languages=",".join(options.get("languages") or []))
    store.update_job(job_id, options=options)
    _run(s, store, job_id=job_id)


@app.command()
def resume(job_id: str, offline: bool = typer.Option(False, "--offline"), languages: Optional[str] = typer.Option(None, "--languages")):
    """Resume an interrupted job with the options it was created with; finished steps are not repeated."""
    _, store = _env()
    job = store.get_job(job_id)
    stored = (job or {}).get("options", {})
    s, store = _env(offline or stored.get("llm") == "offline", languages or ",".join(stored.get("languages") or []),
                    **{k: stored.get(k) for k in ("model", "analysis_model", "layout", "caption_style")})
    _run(s, store, job_id=job_id)


@app.command()
def status(job_id: Optional[str] = typer.Argument(None)):
    """List jobs, or the details of one: clips and which subagent did what."""
    _, store = _env()
    if not job_id:
        for j in store.list_jobs():
            typer.echo(f"{j['id']}  {j['status']}  source {j['source_id']}  {j['created_at']:%Y-%m-%d %H:%M}")
        return
    job = store.get_job(job_id)
    if not job:
        _fail(f"Job {job_id} does not exist")
    typer.echo(f"{job['id']}  {job['status']}")
    for c in store.list_clips(job_id):
        typer.echo(f"  {c['id']}  {c['status']}  {c['decision_note'] or ''}"[:160])
    typer.echo("  Steps:")
    for st in store.list_steps(job_id):
        typer.echo(f"    {st['agent']:<9} {st['key']:<12} {st['clip_id'] or '-':<16} {st['status']:<6} attempts={st['attempts']} "
                   f"{st['seconds'] or 0:>6.1f}s  {st['model'] or ''}  {st['prompt_version'] or ''}")


@app.command()
def queue():
    """Packaged clips waiting for your decision."""
    _, store = _env()
    rows = store.list_clips(status=output.QUEUE_STATES)
    if not rows:
        typer.echo("The queue is empty.")
    for c in rows:
        flag = "REVIEW" if c["status"] == "needs_human" else "ready "
        hook = next(iter((c["hook_text"] or {}).values()), "")
        typer.echo(f"{c['id']}  {flag}  «{hook}»  {c['package_dir']}")
        if c["status"] == "needs_human" and c["review"]:
            typer.echo(f"    reason: {c['review'].get('feedback', '')}")


@app.command()
def approve(clip_id: str, by: str = typer.Option(..., "--by", help="Who approves."), note: str = typer.Option("", "--note")):
    """Approve a clip from the queue and assign it the next posting slot."""
    s, store = _env()
    try:
        clip = output.decide(s, store, clip_id, approve=True, by=by, note=note)
    except ValueError as e:
        _fail(str(e))
    typer.echo(f"{clip_id} approved by {by}. Suggested posting time: {json.dumps(clip['schedule'])}")


@app.command()
def reject(clip_id: str, by: str = typer.Option(..., "--by"), note: str = typer.Option("", "--note")):
    """Reject a clip from the queue."""
    s, store = _env()
    try:
        output.decide(s, store, clip_id, approve=False, by=by, note=note)
    except ValueError as e:
        _fail(str(e))
    typer.echo(f"{clip_id} rejected by {by}.")


@app.command()
def web(host: str = typer.Option("127.0.0.1", "--host"), port: int = typer.Option(8000, "--port")):
    """Open the web panel (http://localhost:8000)."""
    import uvicorn

    from .web.app import create_app
    uvicorn.run(create_app(), host=host, port=port)


def _print_summary(summary: dict) -> None:
    typer.echo(f"\nJob {summary['job_id']} finished in {summary['seconds']:.0f}s · clips: {summary['clips']}")
    for p in summary["packages"]:
        typer.echo(f"  {p['clip_id']}  {p['status']}  {p['dir'] or p['note'] or ''}")
    u = summary["usage"]
    if u["input_tokens"] or u["output_tokens"]:
        typer.echo(f"  Tokens: {u['input_tokens']} input, {u['output_tokens']} output")


if __name__ == "__main__":
    app()
