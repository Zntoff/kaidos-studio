"""Audio: licensed sound library, mix graph (voice + SFX + ducked music) and two-pass loudness."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..schemas import EDL
from . import ffmpeg

FMT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def load_library(sfx_dir: Path) -> dict[str, dict]:
    """Only sounds listed in library.json, each with a licence, can be used in a clip."""
    index = Path(sfx_dir) / "library.json"
    if not index.exists():
        return {}
    out = {}
    for e in json.loads(index.read_text(encoding="utf-8")):
        if e.get("license") and (Path(sfx_dir) / e["file"]).exists():
            out[e["id"]] = e
    return out


def mix_graph(edl: EDL, library: dict[str, dict], sfx_dir: Path, *, has_audio: bool, first_extra_input: int = 1
              ) -> tuple[list[str], str, str]:
    """Returns (extra ffmpeg input args, filter graph text, output label)."""
    dur = edl.duration
    inputs: list[str] = []
    graph: list[str] = []
    k = first_extra_input
    au = edl.audio
    if has_audio:
        enhance = "highpass=f=85,acompressor=threshold=-20dB:ratio=3:attack=8:release=160:makeup=2," if au.voice_enhance else ""
        graph.append(f"[0:a]{FMT},{enhance}volume={au.voice_gain:.3f},afade=t=in:d=0.04,"
                     f"afade=t=out:st={max(0.0, dur - 0.08):.3f}:d=0.08[voice]")
    else:
        inputs += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        graph.append(f"[{k}:a]{FMT}[voice]")
        k += 1

    layers: list[str] = []
    for i, s in enumerate(edl.audio.sfx):
        entry = library.get(s.id)
        if not entry or entry["kind"] != "sfx":
            continue
        inputs += ["-i", str(Path(sfx_dir) / entry["file"])]
        graph.append(f"[{k}:a]{FMT},volume={entry.get('gain', 0.6) * s.gain:.3f},adelay={int(s.t * 1000)}:all=1[sfx{i}]")
        layers.append(f"[sfx{i}]")
        k += 1

    music = library.get(edl.audio.music_id) if edl.audio.music_id else None
    voice = "[voice]"
    if music and music["kind"] == "music":
        inputs += ["-stream_loop", "-1", "-i", str(Path(sfx_dir) / music["file"])]
        graph.append(f"[{k}:a]{FMT},volume={music.get('gain', 0.22) * au.music_gain:.3f}[mraw]")
        if edl.audio.duck_music and has_audio:
            # The voice drives a compressor on the music: music dips while someone speaks.
            graph.append("[voice]asplit=2[voicem][vkey]")
            graph.append("[mraw][vkey]sidechaincompress=threshold=0.02:ratio=8:attack=100:release=800[music]")
            voice = "[voicem]"
        else:
            graph.append("[mraw]anull[music]")
        layers.append("[music]")
        k += 1

    # A fade to black takes the whole mix down with it.
    tr = edl.transitions
    d = min(tr.outro_d, dur)
    end = f",afade=t=out:st={dur - d:.3f}:d={d:.3f}" if tr.outro == "fade" else ""
    if layers:
        graph.append(f"{voice}{''.join(layers)}amix=inputs={len(layers) + 1}:normalize=0:duration=first:dropout_transition=0{end}[aout]")
    else:
        graph.append(f"{voice}anull{end}[aout]")
    return inputs, ";".join(graph), "[aout]"


def measure(path: str | Path, target_i: float = -14.0, tp: float = -1.0, *, start: float | None = None,
            duration: float | None = None) -> dict | None:
    """EBU R128 measurement via loudnorm's analysis pass. None when the audio is silent."""
    window = (["-ss", f"{start:.3f}"] if start is not None else []) + (["-t", f"{duration:.3f}"] if duration is not None else [])
    log = ffmpeg.run([*window, "-i", str(path), "-vn", "-af", f"loudnorm=I={target_i}:TP={tp}:LRA=11:print_format=json",
                      "-f", "null", "-"], capture_stderr=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log, re.S)
    if not m:
        return None
    raw = json.loads(m.group(0))
    try:
        vals = {k: float(raw[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except ValueError:
        return None
    if vals["input_i"] < -69 or any(v != v or abs(v) == float("inf") for v in vals.values()):
        return None
    return vals


def has_program_audio(src_path: str | Path, start: float, duration: float, floor_lufs: float = -45.0) -> bool:
    """True when this stretch of the source has real sound. Near-silence must not be 'normalised':
    that would only amplify hiss, or blast a few sound effects up to full programme level."""
    m = measure(src_path, start=start, duration=duration)
    return m is not None and m["input_i"] > floor_lufs


def loudnorm_dynamic(target_i: float, tp: float) -> str:
    """Fallback for very peaky audio, where a plain gain change cannot reach the target without
    clipping: loudnorm's dynamic mode evens out the level as it goes."""
    return f"loudnorm=I={target_i}:TP={tp}:LRA=11,aresample=48000"


def loudnorm_filter(measured: dict, target_i: float, tp: float) -> str:
    return (f"loudnorm=I={target_i}:TP={tp}:LRA=11:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true,aresample=48000")
