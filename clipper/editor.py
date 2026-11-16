"""Manual editing of a finished clip (the web editor).

The editor works on a *draft*: a copy of the clip's EDL and caption tracks that a person changes
in the browser. Nothing here asks a model for anything. A draft becomes the clip only when it is
rendered: same FFmpeg renderer, same deterministic guards, a new package, and the clip goes back
to the approval queue marked as edited by hand."""
from __future__ import annotations

import functools
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np

from .agents import output
from .agents.base import Context
from .agents.metadata import load_spoiler_terms
from .agents.reviewer import ReviewerAgent, ReviewInput
from .config import Settings
from .llm import OfflineLLM
from .media import audio as audio_lib
from .media import captions as cap
from .media import ffmpeg
from .media import render as renderer
from .media import studio
from .schemas import (EDL, CaptionResult, CaptionTrack, CaptionWord, Check, Cue, MetadataSet, RenderResult,
                      ReviewVerdict, SourceRecord, Transcript)
from .store import Store, now

EDITABLE = {"pending_approval", "needs_human", "approved", "rejected", "rejected_by_human"}
PAD = 60.0                    # seconds of source shown around the clip, to extend it
MIN_DUR, MAX_DUR = 3.0, 180.0
TEXT_MAX = 200
FRAME_HEIGHTS = (72, 120, 240, 480)
_ffmpeg_slots = threading.Semaphore(3)
_proxy_lock = threading.Lock()


class EditError(ValueError):
    pass


# ---------- loading ----------
def load(store: Store, clip_id: str) -> tuple[dict, SourceRecord]:
    clip = store.get_clip(clip_id)
    if clip is None:
        raise KeyError(clip_id)
    if not clip["edl"] or clip["status"] not in EDITABLE:
        raise EditError(f"Este clip todavía no se puede editar (estado: {clip['status']}).")
    record = store.get_source(clip["edl"]["source"]["id"])
    if record is None or not Path(record["path"]).exists():
        raise EditError("No se encuentra el video fuente de este clip.")
    return clip, SourceRecord(**record)


def _step(store: Store, clip: dict, agent: str, key: str) -> dict | None:
    st = store.get_done_step(clip["job_id"], clip["id"], agent, key)
    return st["output"] if st else None


def current_tracks(store: Store, clip: dict) -> dict:
    """Caption tracks of the packaged clip: the last manual render, else the Captions subagent's."""
    out = _step(store, clip, "captions", "captions:manual") or \
        _step(store, clip, "captions", f"captions:r{clip['edl'].get('revision', 0)}")
    return (out or {"tracks": {}})["tracks"]


def current_metadata(store: Store, clip: dict) -> MetadataSet:
    out = _step(store, clip, "metadata", f"metadata:r{clip['edl'].get('revision', 0)}")
    if not out:
        raise EditError("Faltan los títulos y la metadata de este clip.")
    return MetadataSet.model_validate(out)


@functools.lru_cache(maxsize=4)
def _transcript_cached(path: str, mtime: float) -> Transcript:
    return Transcript.model_validate_json(Path(path).read_text(encoding="utf-8"))


def transcript_for(store: Store, job_id: str) -> Transcript | None:
    st = store.get_done_step(job_id, None, "analysis", "analysis")
    path = Path(st["output"]["transcript_path"]) if st else None
    if not path or not path.exists():
        return None
    return _transcript_cached(str(path), path.stat().st_mtime)


def _css(ass_colour: str) -> str:
    """ASS &HAABBGGRR -> #RRGGBB."""
    h = ass_colour[-6:]
    return f"#{h[4:6]}{h[2:4]}{h[0:2]}"


def _font_scale(family: str, bold: bool) -> float:
    """ASS font sizes are line heights (ascent + descent); CSS font sizes are the em square.
    This is the factor from one to the other, so the live preview draws text as big as libass does."""
    try:
        return studio.font_scale(cap.font_file(family, bold))
    except Exception:  # no fontconfig (e.g. running outside Docker): a typical value
        return 0.83


def state(s: Settings, store: Store, clip_id: str) -> dict:
    """Everything the editor needs to draw the clip and its surroundings."""
    clip, src = load(store, clip_id)
    draft = clip.get("draft") or {}
    edl = draft.get("edl") or clip["edl"]
    tracks = draft.get("tracks") or current_tracks(store, clip)
    lo = min(edl["source"]["start"], clip["edl"]["source"]["start"])
    hi = max(edl["source"]["end"], clip["edl"]["source"]["end"])
    a, b = max(0.0, lo - PAD), min(src.duration, hi + PAD)
    tr = transcript_for(store, clip["job_id"])
    words = [w.model_dump() for w in tr.words() if w.w and w.end >= a and w.start <= b] if tr else []
    geometry = {layout: cap.geometry(SimpleNamespace(layout=layout), src.width, src.height, s)
                for layout in ("gameplay_blur_bg", "center_crop")}
    cat = studio.catalog()
    fonts = {}
    for fid, f in studio.fonts().items():
        family, bold = {"caption": (s.caption_font, False), "text": (s.text_font, True)}.get(fid, (f["family"], bool(f["bold"])))
        fonts[fid] = {"label": f["label"], "scale": _font_scale(family, bold)}
    pkg = Path(clip["package_dir"]) if clip["package_dir"] else None
    renders = {lang: f"/api/clips/{clip_id}/file/{lang}/video" for lang in clip["edl"]["languages"]
               if pkg and (pkg / lang / "clip.mp4").is_file()}
    return {
        "clip": {"id": clip_id, "status": clip["status"], "job_id": clip["job_id"], "review": clip["review"]},
        "edl": edl, "tracks": tracks, "has_draft": bool(draft), "draft_saved_at": draft.get("saved_at"),
        "source": {"id": src.id, "duration": src.duration, "width": src.width, "height": src.height,
                   "has_audio": src.has_audio, "video_url": f"/api/sources/{src.id}/video"},
        "window": {"a": round(a, 3), "b": round(b, 3)}, "words": words,
        "library": [{k: e.get(k) for k in ("id", "kind", "description", "duration", "gain")}
                    for e in audio_lib.load_library(s.sfx_dir).values()],
        "frame": {"width": s.width, "height": s.height, "fps": s.fps,
                  "safe": {"top": s.safe.top, "bottom": s.safe.bottom, "side": s.safe.side, "left": s.safe.side, "right": s.safe.side, "center_x": s.width // 2}},
        "geometry": geometry, "styles": cap.STYLE_SPECS, "fonts": fonts,
        "catalog": {k: cat[k] for k in ("looks", "effects", "fx", "text_presets", "anim_in", "anim_out", "anim",
                                         "transitions", "color_params")},
        "text_layout": {"margin": cap.TEXT_MARGIN, "box_pad": cap.TEXT_BOX_PAD},
        "limits": {"min": MIN_DUR, "max": MAX_DUR, "recommended_max": s.clip_max_s},
        "renders": renders,
    }


# ---------- draft ----------
def _clean_text(text: dict, languages: list[str]) -> dict[str, str]:
    return {lang: " ".join(str((text or {}).get(lang, "")).split())[:TEXT_MAX] for lang in languages}


def sanitize(s: Settings, clip: dict, src: SourceRecord, payload: dict) -> tuple[EDL, CaptionResult]:
    """Turn what the browser sent into a valid EDL and caption tracks. Fields a person may not
    change (source, languages, risk, revision) always come from the stored clip."""
    base = clip["edl"]
    raw = dict(payload.get("edl") or {})
    langs = base["languages"]
    try:
        start = max(0.0, float(raw["source"]["start"]))
        end = min(src.duration, float(raw["source"]["end"]))
    except (KeyError, TypeError, ValueError):
        raise EditError("Falta el rango del clip (source.start / source.end).")
    dur = end - start
    if not (MIN_DUR <= dur <= MAX_DUR):
        raise EditError(f"El clip duraría {dur:.1f} s; debe durar entre {MIN_DUR:.0f} y {MAX_DUR:.0f} s.")

    def num(value, default: float, lo: float, hi: float) -> float:
        try:
            return round(min(hi, max(lo, float(value))), 3)
        except (TypeError, ValueError):
            return default

    def position(o):
        return {k: None if o.get(k) is None else num(o[k], 0.5, 0, 1) for k in ("x", "y")}

    hook = raw.get("hook") or {}
    notes = []
    for n in sorted((raw.get("commentary") or {}).get("notes") or [], key=lambda n: float(n.get("t", 0))):
        t = num(n.get("t"), 0.0, 0.0, dur)
        d = num(n.get("duration"), 3.0, 0.0, dur - t)
        text = _clean_text(n.get("text"), langs)
        if d >= 0.5 and any(text.values()):
            notes.append({"t": t, "duration": d, "text": text, **position(n)})
    library = audio_lib.load_library(s.sfx_dir)
    audio = raw.get("audio") or {}
    def inside(x) -> bool:
        try:
            return isinstance(x, dict) and 0 <= float(x.get("t", -1)) < dur
        except (TypeError, ValueError):
            return False

    sfx = sorted(({"t": num(x.get("t"), 0.0, 0.0, dur), "id": x.get("id"), "gain": num(x.get("gain"), 1.0, 0.0, 3.0)}
                  for x in (audio.get("sfx") or [])[:40] if inside(x) and library.get(x.get("id"), {}).get("kind") == "sfx"),
                 key=lambda x: x["t"])
    music = audio.get("music_id")
    effects = []
    for x in (raw.get("effects") or [])[:40]:
        spec = studio.effect_spec(x.get("type", "punch_in")) if inside(x) else None
        if spec:
            t = num(x.get("t"), 0.0, 0.0, dur)
            effects.append({"t": t, "type": spec["id"], "intensity": num(x.get("intensity"), 1.0, 0.2, 2.0),
                            "duration": num(x.get("duration"), spec["d"], spec["min"], min(spec["max"], max(spec["min"], dur - t)))})
    effects.sort(key=lambda x: x["t"])
    known_fonts = studio.fonts()
    texts = []
    for x in (raw.get("texts") or [])[:30]:
        if not inside(x):
            continue
        t = num(x.get("t"), 0.0, 0.0, dur)
        d = num(x.get("duration"), 3.0, 0.0, dur - t)
        text = {lang: "\n".join(" ".join(line.split()) for line in str((x.get("text") or {}).get(lang, "")).splitlines())[:TEXT_MAX].strip()
                for lang in langs}
        if d < 0.2 or not any(text.values()):
            continue
        texts.append({**{k: x[k] for k in ("color", "stroke", "box", "anim_in", "anim_out") if isinstance(x.get(k), str)},
                      "t": t, "duration": d, "text": text, "x": num(x.get("x"), 0.5, 0.0, 1.0), "y": num(x.get("y"), 0.3, 0.0, 1.0),
                      "font": x.get("font") if x.get("font") in known_fonts else "anton",
                      "size": int(num(x.get("size"), 80, 16, 300)), "stroke_w": num(x.get("stroke_w"), 6.0, 0.0, 24.0),
                      "box_opacity": num(x.get("box_opacity"), 1.0, 0.1, 1.0), "opacity": num(x.get("opacity"), 1.0, 0.1, 1.0),
                      "glow": num(x.get("glow"), 0.0, 0.0, 12.0), "upper": bool(x.get("upper")),
                      "rotate": num(x.get("rotate"), 0.0, -45.0, 45.0)})
    texts.sort(key=lambda x: x["t"])
    col = raw.get("color") or {}
    color = {k: num(col.get(k), 0.0, 0.0 if k in ("fade", "vignette") else -1.0, 1.0)
             for k in ("brightness", "contrast", "saturation", "temperature", "tint", "fade", "vignette")}
    color["look"] = col.get("look") if any(l["id"] == col.get("look") for l in studio.catalog()["looks"]) else "none"
    color["look_amount"] = num(col.get("look_amount"), 1.0, 0.0, 1.0)
    tr = raw.get("transitions") or {}
    prog = raw.get("progress") or {}
    captions = raw.get("captions") or {}
    cap_y = captions.get("y")
    try:
        edl = EDL.model_validate({
            "clip_id": clip["id"],
            "source": {"id": src.id, "start": round(start, 3), "end": round(end, 3)},
            "source_language": base["source_language"], "languages": langs,
            "layout": raw.get("layout", base["layout"]), "crop_x": num(raw.get("crop_x"), 0.5, 0.0, 1.0),
            "hook": {**position(hook), "text": _clean_text(hook.get("text"), langs), "duration": num(hook.get("duration"), 2.0, 0.0, min(dur, 8.0))},
            "commentary": {"mode": "onscreen", "notes": notes},
            "captions": {"x": position(captions)["x"], "style": captions.get("style", base["captions"]["style"]),
                         "highlight_keywords": base["captions"].get("highlight_keywords", []),
                         "y": None if cap_y is None else num(cap_y, 0.7, 0.05, 0.95),
                         "scale": num(captions.get("scale"), 1.0, 0.5, 1.6)},
            "audio": {"normalize_lufs": num(audio.get("normalize_lufs"), s.target_lufs, -24.0, -8.0),
                      "music_id": music if library.get(music, {}).get("kind") == "music" else None,
                      "duck_music": bool(audio.get("duck_music", True)), "sfx": sfx,
                      "voice_gain": num(audio.get("voice_gain"), 1.0, 0.0, 3.0),
                      "music_gain": num(audio.get("music_gain"), 1.0, 0.0, 3.0),
                      "voice_enhance": bool(audio.get("voice_enhance"))},
            "effects": effects, "color": color, "texts": texts,
            "transitions": {"intro": tr.get("intro", "none"), "intro_d": num(tr.get("intro_d"), 0.4, 0.1, 2.0),
                            "outro": tr.get("outro", "none"), "outro_d": num(tr.get("outro_d"), 0.4, 0.1, 2.0)},
            "progress": {"on": bool(prog.get("on")), "position": prog.get("position", "top"),
                         "height": int(num(prog.get("height"), 12, 4, 40)),
                         **({"color": prog["color"]} if isinstance(prog.get("color"), str) else {})},
            "risk": base["risk"], "revision": base.get("revision", 0),
        })
    except ValueError as e:
        raise EditError(f"Edición no válida: {str(e)[:300]}")

    tracks: dict[str, CaptionTrack] = {}
    incoming = payload.get("tracks") or {}
    for lang in langs:
        t_raw = incoming.get(lang) or {}
        cues: list[Cue] = []
        for c in sorted(t_raw.get("cues") or [], key=lambda c: float(c.get("start", 0))):
            c0, c1 = num(c.get("start"), 0.0, 0.0, dur), num(c.get("end"), 0.0, 0.0, dur)
            floor = cues[-1].end if cues else 0.0
            c0 = max(c0, floor)                       # no overlaps: the renderer shows one cue at a time
            texts = [(w, " ".join(str(w.get("w", "")).split())[:60]) for w in (c.get("words") or [])]
            texts = [(w, t) for w, t in texts if t]
            if c1 - c0 < 0.08 or not texts:
                continue
            words, n = [], len(texts)
            for i, (w, text) in enumerate(texts):
                # Word times stay inside the cue and in order; the first word starts with the cue.
                lo = c0 if i == 0 else words[-1].start
                w0 = c0 if i == 0 else num(w.get("start"), c0 + (c1 - c0) * i / n, lo, c1)
                w1 = num(w.get("end"), c0 + (c1 - c0) * (i + 1) / n, w0, c1)
                words.append(CaptionWord(w=text, start=w0, end=w1, hl=bool(w.get("hl"))))
            cues.append(Cue(start=c0, end=c1, words=words))
        tracks[lang] = CaptionTrack(lang=lang, style=edl.captions.style,
                                    word_timed=bool(t_raw.get("word_timed", lang == edl.source_language)), cues=cues)
    return edl, CaptionResult(tracks=tracks)


def save_draft(s: Settings, store: Store, clip_id: str, payload: dict) -> dict:
    clip, src = load(store, clip_id)
    edl, caps = sanitize(s, clip, src, payload)
    saved_at = now().isoformat()
    store.update_clip(clip_id, draft={"edl": edl.model_dump(), "tracks": caps.model_dump()["tracks"], "saved_at": saved_at})
    return {"saved_at": saved_at, "duration": round(edl.duration, 3)}


def discard_draft(store: Store, clip_id: str) -> None:
    load(store, clip_id)
    store.update_clip(clip_id, draft=None)


# ---------- render ----------
def manual_review(s: Settings, store: Store, clip: dict, edl: EDL, src: SourceRecord, caps: CaptionResult,
                  meta: MetadataSet, renders: RenderResult) -> ReviewVerdict:
    """The deterministic guards, run again on the edited clip. Claude's judgement is not repeated,
    and the verdict says so: a hand-edited clip always waits for a person."""
    tr = transcript_for(store, clip["job_id"])
    spoken = " ".join(w.w for w in cap.clip_words(tr, edl.source.start, edl.source.end)) if tr else ""
    agent = ReviewerAgent(Context(settings=s, store=store, llm=OfflineLLM(), log=lambda m: None))
    checks = agent.deterministic_checks(ReviewInput(
        edl=edl, source=src, spoken_text=spoken, captions=caps, metadata=meta, renders=renders,
        recent=store.recent_hooks(exclude_clip=clip["id"]), spoiler_terms=load_spoiler_terms(s.spoilers_file)))
    checks.append(Check(name="manual_edit", status="warn",
                        detail="Clip editado a mano. La revisión de Claude (spoilers y valor propio) no se repitió sobre esta versión."))
    fails = [f"{c.name}: {c.detail}" for c in checks if c.status == "fail"]
    feedback = "Edición manual: mira el resultado antes de aprobar."
    if fails:
        feedback += " Guards que no pasan: " + "; ".join(fails)
    return ReviewVerdict(status="needs_human", checks=checks, feedback=feedback, reviewer="manual")


def render_draft(s: Settings, store: Store, clip_id: str, log: Callable[[str], None] = lambda m: None) -> dict:
    clip, src = load(store, clip_id)
    draft = clip.get("draft")
    if not draft:
        raise EditError("No hay cambios que renderizar.")
    edl = EDL.model_validate(draft["edl"])
    caps = CaptionResult.model_validate({"tracks": draft["tracks"]})
    meta = current_metadata(store, clip)
    job_id = clip["job_id"]
    job = store.get_job(job_id) or {}
    done = sum(1 for st in store.list_steps(job_id)
               if st["clip_id"] == clip_id and st["agent"] == "render" and st["key"].startswith("render:m"))
    tag = f"m{done + 1}"
    work = s.job_dir(job_id) / "clips" / clip_id / tag
    t0 = time.time()
    log(f"Render manual {clip_id} · {edl.duration:.1f} s · {', '.join(edl.languages)}")
    reports = {}
    for lang in edl.languages:
        log(f"  [Render] {lang}")
        reports[lang] = renderer.render_clip(edl, src, caps.tracks.get(lang), lang, work, s)
    renders = RenderResult(renders=reports)
    log("  [Guards] comprobaciones automáticas")
    review = manual_review(s, store, clip, edl, src, caps, meta, renders)
    common = {"job_id": job_id, "clip_id": clip_id, "status": "done", "attempts": 1}
    store.record_step(**common, agent="captions", key="captions:manual", model="manual", output=caps.model_dump(), seconds=0.0)
    store.record_step(**common, agent="render", key=f"render:{tag}", model="ffmpeg", output=renders.model_dump(),
                      seconds=round(time.time() - t0, 2))
    store.update_clip(clip_id, edl=edl.model_dump(), review=review.model_dump(), draft=None, schedule=None,
                      decided_by=None, decided_at=None, decision_note=None)
    pkg = output.build_package(s, store, job_id, clip_id, edl, src, caps, meta, renders, review,
                               offline=(job.get("options") or {}).get("llm") == "offline")
    log(f"  Listo en {time.time() - t0:.0f} s · {pkg.dir}")
    return {"clip_id": clip_id, "status": pkg.status, "dir": pkg.dir}


# ---------- media for the editor ----------
def frame(s: Settings, src: SourceRecord, t: float, height: int) -> Path:
    """One JPEG of the source, cached. Times are rounded to half a second so tiles are reused."""
    height = min(FRAME_HEIGHTS, key=lambda h: abs(h - height))
    t = max(0.0, min(src.duration - 0.1, round(t * 2) / 2))
    out = s.data_dir / "cache" / "frames" / src.id / f"{height}_{int(t * 10):07d}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".{threading.get_ident()}.tmp.jpg")
        with _ffmpeg_slots:
            ffmpeg.run(["-ss", f"{t:.3f}", "-i", src.path, "-frames:v", "1", "-vf", f"scale=-2:{height}", "-q:v", "6", str(tmp)])
        tmp.replace(out)
    return out


def clip_thumb(s: Settings, clip: dict, lang: str | None = None) -> Path | None:
    """Poster of the packaged clip (first language unless one is given)."""
    if not clip.get("package_dir") or not clip.get("edl"):
        return None
    lang = lang if lang in clip["edl"]["languages"] else clip["edl"]["languages"][0]
    video = Path(clip["package_dir"]) / lang / "clip.mp4"
    if not video.is_file():
        return None
    out = s.data_dir / "cache" / "thumbs" / f"{clip['id']}_{lang}_{int(video.stat().st_mtime)}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(f".{threading.get_ident()}.tmp.jpg")
        with _ffmpeg_slots:
            ffmpeg.run(["-ss", "0.6", "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", str(tmp)])
        tmp.replace(out)
    return out


def waveform(src: SourceRecord, a: float, b: float, per_second: int = 50) -> dict:
    """Peak level per 20 ms between a and b, 0..1, for the timeline's audio track."""
    if not src.has_audio or b <= a:
        return {"a": a, "per_second": per_second, "peaks": []}
    rate = 8000
    with _ffmpeg_slots:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                            "-i", src.path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], capture_output=True)
    data = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    hop = rate // per_second
    if p.returncode != 0 or len(data) < hop:
        return {"a": a, "per_second": per_second, "peaks": []}
    peaks = np.abs(data[: len(data) // hop * hop].reshape(-1, hop)).max(axis=1)
    top = float(peaks.max()) or 1.0
    return {"a": a, "per_second": per_second, "peaks": [round(float(x), 3) for x in np.sqrt(peaks / top)]}


def proxy(s: Settings, clip_id: str, src: SourceRecord, a: float, b: float) -> Path:
    """A small H.264 copy of the editing window, for sources the browser cannot play or seek well."""
    out = s.data_dir / "cache" / "proxy" / f"{clip_id}_{int(a * 10)}_{int(b * 10)}.mp4"
    with _proxy_lock:
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp.mp4")
            ffmpeg.run(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src.path, "-vf", "scale=-2:540", "-c:v", "libx264",
                        "-preset", "ultrafast", "-crf", "26", "-g", "15", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                        "-movflags", "+faststart", str(tmp)])
            tmp.replace(out)
    return out
