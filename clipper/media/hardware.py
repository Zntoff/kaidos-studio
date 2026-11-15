"""Probe encoders exposed to this process, including inside a container."""
from functools import lru_cache
import subprocess

LABELS = {"h264_nvenc": "NVIDIA · NVENC", "h264_amf": "AMD · AMF", "h264_qsv": "Intel · Quick Sync", "libx264": "Procesador · CPU"}


def args(encoder: str, quality: int = 19) -> list[str]:
    q = str(quality)
    recipes = {
        "h264_nvenc": ["-preset", "p5", "-rc", "vbr", "-cq", q, "-b:v", "0"],
        "h264_amf": ["-quality", "balanced", "-rc", "cqp", "-qp_i", q, "-qp_p", q],
        "h264_qsv": ["-preset", "fast", "-global_quality", q],
        "libx264": ["-preset", "veryfast", "-crf", q],
    }
    enc = encoder if encoder in recipes else "libx264"
    return ["-c:v", enc, *recipes[enc], "-pix_fmt", "yuv420p"]


@lru_cache(maxsize=1)
def devices() -> list[dict]:
    result = []
    for enc, name in LABELS.items():
        if enc == "libx264":
            continue
        try:
            p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=s=320x320:d=0.2", *args(enc), "-f", "null", "-"], capture_output=True, timeout=12)
            if p.returncode == 0:
                result.append({"id": enc, "name": name, "kind": "GPU accesible al contenedor", "encoder": enc, "available": True})
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def resolve(device: str) -> str:
    working = [d["encoder"] for d in devices()]
    if device == "auto":
        return working[0] if working else "libx264"
    return device if device in working else "libx264"
