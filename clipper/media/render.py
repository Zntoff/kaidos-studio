"""Renderer: executes an EDL with FFmpeg. It makes no creative choices of its own.

Picture pipeline: frame the source (layout + camera motion) -> colour grade -> vignette ->
timed effects (blur, black and white, glitch) -> burnt-in text and shapes (libass) -> fades.
The same steps, with the same numbers, are drawn live by the editor's preview."""
from __future__ import annotations

import math
from pathlib import Path

from ..config import Settings
from ..schemas import EDL, CaptionTrack, RenderReport, SourceRecord
from . import audio, captions, ffmpeg, studio

FX = studio.catalog()["fx"]
ZOOM_AMOUNT, ZOOM_RAMP = FX["zoom"], FX["ramp"]


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def motion(edl: EDL) -> tuple[str, str, str] | None:
    """Camera motion as zoompan expressions (zoom, dx, dy), dx / dy in output pixels.
    None when the clip has no punch-in, slow zoom or shake."""
    punch, slow, shake = [], [], []
    for fx in edl.effects:
        a, b, k = fx.t, fx.t + fx.duration, fx.intensity
        if fx.type == "punch_in":
            punch.append(f"{k:.2f}*clip((it-{a:.3f})/{ZOOM_RAMP},0,1)*clip(({b:.3f}-it)/{ZOOM_RAMP},0,1)")
        elif fx.type == "zoom_slow":
            slow.append(f"{k:.2f}*between(it,{a:.3f},{b:.3f})*(it-{a:.3f})/{fx.duration:.3f}")
        elif fx.type == "shake":
            shake.append(f"{k:.2f}*between(it,{a:.3f},{b:.3f})")
    if not (punch or slow or shake):
        return None
    z = ["1"]
    if punch:
        z.append(f"{ZOOM_AMOUNT}*min(2,{'+'.join(punch)})")
    if slow:
        z.append(f"{FX['slow']}*min(2,{'+'.join(slow)})")
    dx = dy = "0"
    if shake:
        env = f"min(2,{'+'.join(shake)})"
        z.append(f"{FX['shake_zoom']}*{env}")
        w = 2 * math.pi * FX["shake_hz"]
        dx = f"{FX['shake_px']}*{env}*sin({w:.3f}*it)"
        dy = f"{FX['shake_px']}*{env}*cos({w * 1.3:.3f}*it)"
    return "+".join(z), dx, dy


def _zoompan(m: tuple[str, str, str], w: int, h: int, fps: int) -> str:
    z, dx, dy = m
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)+({dx})*(iw/zoom)/ow':y='ih/2-(ih/zoom/2)+({dy})*(ih/zoom)/oh'"
            f":d=1:s={w}x{h}:fps={fps}")


def timed_filters(edl: EDL) -> list[str]:
    """Effects that switch a filter on for a stretch of the clip."""
    out = []
    for fx in edl.effects:
        on = f"enable='between(t,{fx.t:.3f},{fx.t + fx.duration:.3f})'"
        if fx.type == "blur":
            out.append(f"gblur=sigma={FX['blur_sigma'] * fx.intensity:.1f}:{on}")
        elif fx.type == "bw":
            out.append(f"hue=s=0:{on}")
        elif fx.type == "glitch":
            n = max(2, int(round(FX["glitch_px"] * fx.intensity)))
            out.append(f"rgbashift=rh={-n}:bh={n}:{on}")
    return out


def video_graph(edl: EDL, src: SourceRecord, s: Settings, ass_path: Path, vignette_input: int | None = None) -> str:
    g = captions.geometry(edl, src.width, src.height, s)
    W, H, fps = s.width, s.height, s.fps
    m = motion(edl)
    if edl.layout == "gameplay_blur_bg":
        fg_h = g["fg_h"]
        fg = f"scale={W * 2}:{fg_h * 2}:flags=bicubic,{_zoompan(m, W, fg_h, fps)}" if m else f"scale={W}:{fg_h}:flags=lanczos"
        graph = [
            f"[0:v]fps={fps},setsar=1,split=2[bgs][fgs]",
            f"[bgs]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},gblur=sigma=9,"
            f"scale={W}:{H}:flags=bilinear,eq=brightness=-0.16:saturation=0.85[bg]",
            f"[fgs]{fg}[fg]",
            f"[bg][fg]overlay=0:{g['fg_y']}[v0]",
        ]
    else:
        crop = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(iw-{W})*{edl.crop_x:.3f}:(ih-{H})/2"
        if m:
            crop += f",scale={W * 3 // 2}:{H * 3 // 2}:flags=bicubic,{_zoompan(m, W, H, fps)}"
        graph = [f"[0:v]fps={fps},setsar=1,{crop}[v0]"]

    grade = studio.color_filter(edl.color)
    pre = [grade] if grade else []
    tail = timed_filters(edl)
    tail.append(f"ass='{_filter_path(ass_path)}':fontsdir='{_filter_path(s.fonts_dir)}'")
    tr, dur = edl.transitions, edl.duration
    if tr.intro == "fade":
        tail.append(f"fade=t=in:st=0:d={min(tr.intro_d, dur):.3f}")
    if tr.outro == "fade":
        d = min(tr.outro_d, dur)
        tail.append(f"fade=t=out:st={dur - d:.3f}:d={d:.3f}")
    tail.append("format=yuv420p")
    vig = studio.color_params(edl.color)["vignette"]
    if vig > 0 and vignette_input is not None:
        graph += [f"[v0]{','.join(pre) or 'null'}[vc]",
                  f"[{vignette_input}:v]scale={W}:{H},format=rgba,colorchannelmixer=aa={vig:.3f}[vg]",
                  "[vc][vg]overlay=shortest=1[v1]",
                  f"[v1]{','.join(tail)}[v]"]
    else:
        graph.append(f"[v0]{','.join(pre + tail)}[v]")
    return ";".join(graph)


def encoder_args(s: Settings) -> list[str]:
    """Video encoder for the first pass. CLIPPER_ENCODER=h264_nvenc uses an NVIDIA GPU when the
    container (or machine) exposes one; the default is libx264 on the CPU."""
    from .hardware import args
    return args(s.encoder, s.render_quality)


def render_clip(edl: EDL, src: SourceRecord, track: CaptionTrack | None, lang: str, out_dir: Path, s: Settings) -> RenderReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_path, srt_path = out_dir / f"{lang}.ass", out_dir / f"{lang}.srt"
    ass_path.write_text(captions.build_ass(edl, track, lang, src.width, src.height, s), encoding="utf-8")
    srt_path.write_text(captions.build_srt(track), encoding="utf-8")

    extra_inputs: list[str] = []
    vignette_input = None
    vignette = s.studio_dir / "vignette.png"
    if studio.color_params(edl.color)["vignette"] > 0 and vignette.exists():
        extra_inputs += ["-loop", "1", "-i", str(vignette)]
        vignette_input = 1
    library = audio.load_library(s.sfx_dir)
    audio_inputs, a_graph, a_out = audio.mix_graph(edl, library, s.sfx_dir, has_audio=src.has_audio,
                                                   first_extra_input=1 if vignette_input is None else 2)
    extra_inputs += audio_inputs
    dur = edl.duration
    temp, final = out_dir / f"{lang}.premix.mkv", out_dir / f"{lang}.mp4"

    # Pass A: picture, text and the audio mix, with audio kept as float so nothing clips yet.
    command = ["-ss", f"{edl.source.start:.3f}", "-t", f"{dur:.3f}", "-i", src.path, *extra_inputs,
                "-filter_complex", f"{video_graph(edl, src, s, ass_path, vignette_input)};{a_graph}",
                "-map", "[v]", "-map", a_out, "-t", f"{dur:.3f}", "-r", str(s.fps),
                *encoder_args(s), "-c:a", "pcm_f32le", str(temp)]
    try:
        ffmpeg.run(command)
    except ffmpeg.FFmpegError:
        if s.encoder == "libx264":
            raise
        from .hardware import args
        start = command.index("-c:v")
        end = command.index("-c:a", start)
        ffmpeg.run([*command[:start], *args("libx264", s.render_quality), *command[end:]])

    # Pass B: two-pass loudness normalisation, only when the clip has real programme audio.
    target, tp = edl.audio.normalize_lufs, s.true_peak
    encode = ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(final)]
    normalized = src.has_audio and edl.audio.voice_gain > 0 and audio.has_program_audio(src.path, edl.source.start, dur)
    measured = audio.measure(temp, target, tp) if normalized else None
    if measured:
        ffmpeg.run(["-i", str(temp), "-af", audio.loudnorm_filter(measured, target, tp), *encode])
        after = audio.measure(final, target, tp)
        if after is None or abs(after["input_i"] - target) > 0.7:
            ffmpeg.run(["-i", str(temp), "-af", audio.loudnorm_dynamic(target, tp), *encode])
    else:
        normalized = False
        ffmpeg.run(["-i", str(temp), "-af", "alimiter=limit=0.89:level=disabled", *encode])
    temp.unlink(missing_ok=True)

    info = ffmpeg.probe(final)
    after = audio.measure(final, edl.audio.normalize_lufs, s.true_peak)
    return RenderReport(lang=lang, path=str(final), width=info["width"], height=info["height"], duration=info["duration"],
                        lufs=after["input_i"] if after else None, true_peak=after["input_tp"] if after else None,
                        normalized=normalized,
                        ass_path=str(ass_path), srt_path=str(srt_path))
