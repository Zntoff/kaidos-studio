"""Cheap, deterministic signals that hint at where something happens: loudness over time
and hard visual cuts. Claude weighs them together with the transcript."""
from __future__ import annotations

import math
import re
import wave
from pathlib import Path

import numpy as np

from ..schemas import Segment, Signals
from . import ffmpeg


def audio_energy(wav_path: str | Path, hop_s: float = 0.5) -> list[float]:
    with wave.open(str(wav_path), "rb") as wf:
        rate, n = wf.getframerate(), wf.getnframes()
        data = np.frombuffer(wf.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        if wf.getnchannels() > 1:
            data = data.reshape(-1, wf.getnchannels()).mean(axis=1)
    hop = max(1, int(rate * hop_s))
    if len(data) < hop:
        return []
    frames = data[: len(data) // hop * hop].reshape(-1, hop)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)
    top = float(db.max())
    if top < -70:  # digital silence
        return [0.0] * len(db)
    norm = np.clip((db - (top - 40.0)) / 40.0, 0.0, 1.0)
    return [round(float(x), 3) for x in norm]


def scene_cuts(video: str | Path, threshold: float = 0.35, mode: str = "full") -> list[float]:
    """Timestamps of hard cuts, found on a small, low-frame-rate copy.

    mode "full" decodes every frame (accurate; minutes on an hour of 1080p).
    mode "keyframes" decodes only keyframes (much faster, coarser: encoders usually place a
    keyframe at a cut, so it still catches most of them). mode "off" skips the signal."""
    if mode == "off":
        return []
    if mode == "keyframes":
        args = ["-skip_frame", "nokey", "-i", str(video), "-an", "-fps_mode", "vfr",
                "-vf", f"scale=320:-2,select='gt(scene,{max(threshold, 0.5)})',showinfo"]
    else:
        args = ["-i", str(video), "-an", "-vf", f"fps=6,scale=320:-2,select='gt(scene,{threshold})',showinfo"]
    log = ffmpeg.run([*args, "-f", "null", "-"], capture_stderr=True)
    return [round(float(m), 2) for m in re.findall(r"pts_time:([0-9.]+)", log)]


def compute(video: str | Path, wav_path: Path | None, hop_s: float = 0.5, scene_mode: str = "full") -> Signals:
    energy = audio_energy(wav_path, hop_s) if wav_path and Path(wav_path).exists() else []
    return Signals(hop_s=hop_s, energy=energy, scene_cuts=scene_cuts(video, mode=scene_mode))


def segment_features(seg: Segment, signals: Signals) -> tuple[float, float, int]:
    """(mean energy, peak energy, number of cuts) inside a segment."""
    a = int(seg.start / signals.hop_s)
    b = max(a + 1, math.ceil(seg.end / signals.hop_s))  # every hop the segment touches
    window = signals.energy[a:b]
    mean = float(np.mean(window)) if window else 0.0
    peak = float(np.max(window)) if window else 0.0
    cuts = sum(1 for c in signals.scene_cuts if seg.start <= c < seg.end)
    return round(mean, 2), round(peak, 2), cuts
