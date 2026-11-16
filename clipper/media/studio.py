"""Studio catalog: colour looks, effects, caption styles, text presets and bundled fonts.

The catalog (assets/studio/catalog.json) is data shared by every renderer of an EDL: this FFmpeg
renderer, the live preview in the browser, and the Windows desktop app. The maths in here
(`color_affine`) is mirrored line by line in editor.js and in the desktop engine, so the preview
and both renders agree."""
from __future__ import annotations

import functools
import json
from pathlib import Path

from ..config import REPO_ROOT

STUDIO_DIR = REPO_ROOT / "assets" / "studio"
FONTS_DIR = REPO_ROOT / "assets" / "fonts"
LUMA = (0.2126, 0.7152, 0.0722)
SEPIA = ((0.393, 0.769, 0.189), (0.349, 0.686, 0.168), (0.272, 0.534, 0.131))


@functools.lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads((STUDIO_DIR / "catalog.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def fonts() -> dict[str, dict]:
    """Bundled fonts by id. Only entries whose file exists."""
    index = FONTS_DIR / "fonts.json"
    if not index.exists():
        return {}
    return {f["id"]: {**f, "path": str(FONTS_DIR / f["file"])}
            for f in json.loads(index.read_text(encoding="utf-8")) if (FONTS_DIR / f["file"]).exists()}


def font(font_id: str) -> dict:
    reg = fonts()
    return reg.get(font_id) or reg.get("caption") or {"id": font_id, "family": "Inter", "bold": True, "path": ""}


def bundled_font_file(family: str, bold: bool) -> str | None:
    for f in fonts().values():
        if f["family"].lower() == family.lower() and bool(f["bold"]) == bool(bold):
            return f["path"]
    return None


@functools.lru_cache(maxsize=64)
def font_scale(path: str) -> float:
    """Em size per unit of ASS font size, the way libass sizes text: an ASS size is the font's
    Windows line height (OS/2 usWinAscent + usWinDescent), or the hhea height without OS/2.
    The preview multiplies its CSS font size by this, so text is as big as in the render."""
    import struct

    try:
        data = Path(path).read_bytes()
        tables = {}
        for i in range(struct.unpack(">H", data[4:6])[0]):
            tag, _, off, _ = struct.unpack(">4sLLL", data[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        upm = struct.unpack(">H", data[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        height = 0
        if b"OS/2" in tables:
            height = sum(struct.unpack(">HH", data[tables[b"OS/2"] + 74: tables[b"OS/2"] + 78]))
        if not height:
            asc, desc = struct.unpack(">hh", data[tables[b"hhea"] + 4: tables[b"hhea"] + 8])
            height = asc - desc
        return round(upm / height, 4)
    except Exception:
        return 0.83


def look(look_id: str) -> dict:
    return next((l["p"] for l in catalog()["looks"] if l["id"] == look_id), {})


def effect_spec(effect_id: str) -> dict | None:
    return next((e for e in catalog()["effects"] if e["id"] == effect_id), None)


# ---------- colour ----------
def color_params(color) -> dict[str, float]:
    """Effective grade: the look scaled by its amount, plus the manual adjustments, clamped."""
    get = (lambda k, d=0.0: color.get(k, d)) if isinstance(color, dict) else (lambda k, d=0.0: getattr(color, k, d))
    base, amount = look(get("look", "none")), float(get("look_amount", 1.0))
    out = {}
    for k in catalog()["color_params"]:
        v = float(base.get(k, 0.0)) * amount + float(get(k, 0.0) or 0.0)
        out[k] = max(0.0 if k in ("fade", "sepia", "vignette") else -1.0, min(1.0, v))
    return out


def color_affine(p: dict[str, float]) -> list[list[float]] | None:
    """The grade as three rows [r, g, b, offset] applied to gamma-encoded RGB in 0..1.
    None when it changes nothing."""
    sat = 1.0 + p["saturation"]
    m = [[(1 - sat) * LUMA[j] + (sat if i == j else 0.0) for j in range(3)] for i in range(3)]
    sp = p["sepia"]
    if sp:
        mix = [[(1 - sp) * (1.0 if i == j else 0.0) + sp * SEPIA[i][j] for j in range(3)] for i in range(3)]
        m = [[sum(mix[i][k] * m[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    t, ti = p["temperature"], p["tint"]
    gains = (1 + 0.18 * t + 0.05 * ti, 1 - 0.14 * ti, 1 - 0.18 * t + 0.05 * ti)
    c = p["contrast"]
    slope = 1 + c * (0.6 if c >= 0 else 0.5)
    f = p["fade"]
    k = slope * (1 - 0.2 * f)
    off = (0.5 - 0.5 * slope + 0.25 * p["brightness"]) * (1 - 0.2 * f) + 0.1 * f
    rows = [[round(max(-2.0, min(2.0, k * gains[i] * m[i][j])), 5) for j in range(3)] + [round(off, 5)] for i in range(3)]
    ident = all(abs(rows[i][j] - (1.0 if i == j else 0.0)) < 1e-4 for i in range(3) for j in range(3)) and abs(off) < 1e-4
    return None if ident else rows


def color_filter(color) -> str | None:
    """FFmpeg filter text for the grade. Uses the alpha input of colorchannelmixer (always 1 on
    opaque video) as the offset term, so one filter does matrix + offset."""
    rows = color_affine(color_params(color))
    if rows is None:
        return None
    names = ("r", "g", "b")
    parts = [f"{names[i]}{'rgba'[j]}={rows[i][j]}" for i in range(3) for j in range(4)]
    return "format=rgba,colorchannelmixer=" + ":".join(parts) + ",format=yuv420p"


def ass_color(hex_color: str, alpha: float = 1.0) -> str:
    """#RRGGBB -> ASS &HAABBGGRR (AA: 00 opaque, FF transparent)."""
    h = hex_color.lstrip("#")
    a = int(round((1 - max(0.0, min(1.0, alpha))) * 255))
    return f"&H{a:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()
