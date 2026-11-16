"""Thin wrappers around ffmpeg / ffprobe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def run(args: list[str], *, capture_stderr: bool = False) -> str:
    """Run ffmpeg with the given arguments. Returns stderr text (ffmpeg logs there)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        raise FFmpegError(f"ffmpeg failed ({p.returncode}): {' '.join(cmd[:12])} ...\n{p.stderr[-2500:]}")
    return p.stderr if capture_stderr else ""


def probe(path: str | Path) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path}: {p.stderr[-800:]}")
    info = json.loads(p.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if video is None:
        raise FFmpegError(f"{path} has no video stream")
    num, den = (video.get("avg_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    w, h = int(video["width"]), int(video["height"])
    rotation = 0
    for sd in video.get("side_data_list", []):
        rotation = int(sd.get("rotation", 0)) or rotation
    if abs(rotation) in (90, 270):
        w, h = h, w
    return {
        "duration": float(info["format"].get("duration") or video.get("duration") or 0.0),
        "width": w, "height": h, "fps": fps, "has_audio": audio is not None,
        "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name") if audio else None,
    }


def extract_frames(path: str | Path, out_dir: Path, count: int = 4, width: int = 360) -> list[Path]:
    """Evenly spaced JPEG frames, for the reviewer's visual check."""
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = probe(path)["duration"]
    frames = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        out = out_dir / f"frame_{i:02d}.jpg"
        run(["-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "5", str(out)])
        frames.append(out)
    return frames
