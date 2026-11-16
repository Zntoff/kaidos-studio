"""Generate the starter sound library (effects and music beds) with FFmpeg synthesis, and the
vignette overlay used by the colour tools.

Every sound here is synthesised by this script, so there is no third-party licence to track.
To add your own sounds or music, drop the file in assets/sfx/ and add an entry to library.json
with its licence; entries without a licence are ignored by the pipeline.

Usage: python scripts/make_sfx.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "sfx"
LICENSE = "Synthesized with FFmpeg by this project's scripts/make_sfx.py; no third-party material."


def ev(expr: str, d: float, post: str = "") -> str:
    return f"aevalsrc='{expr}':d={d}:s=48000" + (f",{post}" if post else "")


SOUNDS = [
    ("whoosh_01", "Whoosh: quick air sweep, for the hook or a fast transition", 0.55,
     "anoisesrc=d=0.6:c=pink:a=0.9,highpass=f=350,lowpass=f=5000,aphaser=speed=2:decay=0.5,"
     "afade=t=in:d=0.36:curve=qsin,afade=t=out:st=0.38:d=0.22"),
    ("swoosh_01", "Swoosh: short bright sweep, for text sliding in", 0.5,
     "anoisesrc=d=0.35:c=white:a=0.8,highpass=f=1200,lowpass=f=9000,afade=t=in:d=0.2:curve=exp,afade=t=out:st=0.22:d=0.13"),
    ("pop_01", "Pop: short soft click, for a text note appearing", 0.6, ev("0.8*sin(2*PI*(950-2800*t)*t)*exp(-38*t)", 0.14)),
    ("click_01", "Click: tiny tick, for small UI-like accents", 0.6, ev("0.7*sin(2*PI*2200*t)*exp(-90*t)", 0.06)),
    ("tick_01", "Tick: clock tick, for countdowns", 0.6, ev("0.6*sin(2*PI*3200*t)*exp(-200*t)", 0.05)),
    ("ding_01", "Ding: bright bell, for a fact, a win or a correct call", 0.45,
     ev("0.5*sin(2*PI*1320*t)*exp(-6*t)+0.28*sin(2*PI*2640*t)*exp(-9*t)", 0.9)),
    ("notify_01", "Notify: two-tone chime, for a tip or a reveal", 0.45,
     ev("0.45*sin(2*PI*880*t)*exp(-9*t)+0.45*sin(2*PI*1320*(t-0.13))*exp(-9*max(0,t-0.13))*gt(t,0.13)", 0.7)),
    ("coin_01", "Coin: retro pickup, for points, loot or money", 0.4,
     ev("0.4*sin(2*PI*(988*lt(t,0.08)+1319*gte(t,0.08))*t)*exp(-5*max(0,t-0.08))", 0.6)),
    ("levelup_01", "Level up: rising arpeggio, for a win or an upgrade", 0.4,
     ev("0.4*sin(2*PI*(523.25*lt(t,0.09)+659.25*between(t,0.09,0.18)+783.99*between(t,0.18,0.27)+1046.5*gte(t,0.27))*t)"
        "*exp(-2.5*max(0,t-0.27))", 0.9)),
    ("error_01", "Error: double buzz, for a fail or a wrong call", 0.4,
     ev("0.4*(2*gt(sin(2*PI*150*t),0)-1)*lt(mod(t,0.22),0.16)", 0.42, "lowpass=f=2500")),
    ("boing_01", "Boing: springy bounce, for a funny moment", 0.5,
     ev("0.6*sin(2*PI*(300+180*sin(2*PI*9*t))*t)*exp(-4*t)", 0.7)),
    ("laser_01", "Laser: falling zap, for a shot or a quick cut", 0.4, ev("0.5*sin(2*PI*(2400*exp(-9*t))*t)*exp(-6*t)", 0.35)),
    ("glitch_01", "Glitch: digital stutter, to go with the glitch effect", 0.45,
     ev("0.5*(random(0)*2-1)*gt(sin(2*PI*31*t),0.2)*exp(-3*t)+0.3*sin(2*PI*(900+800*gt(sin(2*PI*17*t),0))*t)*exp(-5*t)", 0.45)),
    ("shutter_01", "Shutter: camera click, to go with a flash", 0.55,
     ev("0.8*(random(0)*2-1)*(exp(-120*t)+exp(-120*abs(t-0.09))*gt(t,0.085))", 0.2, "highpass=f=1500")),
    ("impact_01", "Impact: low thud, for a crash, a hit or a punch-in zoom", 0.7,
     ev("0.9*sin(2*PI*(95-55*t)*t)*exp(-5.5*t)+0.25*(random(0)*2-1)*exp(-30*t)", 0.8, "lowpass=f=1800")),
    ("bassdrop_01", "Bass drop: deep falling boom, for the payoff", 0.7,
     ev("0.9*sin(2*PI*(40+120*exp(-3*t))*t)*exp(-2.2*t)", 1.4, "lowpass=f=400")),
    ("heartbeat_01", "Heartbeat: two low thumps, for tension", 0.7,
     ev("0.9*sin(2*PI*55*t)*(exp(-25*t)+exp(-25*abs(t-0.28))*gt(t,0.2))", 0.8)),
    ("riser_01", "Riser: rising tone, to build tension before the key moment", 0.4,
     ev("0.45*sin(2*PI*(220+520*t)*t)*(t/1.2)", 1.2, "afade=t=out:st=1.1:d=0.1")),
    ("suspense_01", "Suspense: dark drone, under a tense stretch", 0.5,
     ev("0.35*sin(2*PI*55*t)*(1+0.5*sin(2*PI*0.7*t))/1.5+0.15*sin(2*PI*82.4*t)", 3, "afade=t=in:d=0.8,afade=t=out:st=2.2:d=0.8")),
]

# Music beds loop seamlessly (their length is a whole number of bars).
CHILL = ("st(0,floor(mod(t,12)/3));st(1,mod(t,0.75));"
         "st(2,220*eq(ld(0),0)+174.61*eq(ld(0),1)+130.81*eq(ld(0),2)+196*eq(ld(0),3));"
         "0.75*sin(2*PI*(50+90*exp(-30*ld(1)))*ld(1))*exp(-7*ld(1))"
         "+0.1*(random(0)*2-1)*exp(-60*mod(t+0.375,0.75))"
         "+(0.13*sin(2*PI*ld(2)*t)+0.1*sin(2*PI*ld(2)*1.2599*t)+0.1*sin(2*PI*ld(2)*1.4983*t))*(0.8+0.2*sin(2*PI*0.33*t))")
ENERGY = ("st(1,mod(t,0.46875));st(0,floor(mod(t,7.5)/1.875));"
          "st(2,55*eq(ld(0),0)+65.41*eq(ld(0),1)+73.42*eq(ld(0),2)+49*eq(ld(0),3));"
          "0.85*sin(2*PI*(48+110*exp(-35*ld(1)))*ld(1))*exp(-9*ld(1))"
          "+0.09*(random(0)*2-1)*exp(-90*mod(t,0.1171875))"
          "+0.22*(2*gt(sin(2*PI*ld(2)*t),0)-1)*(1-exp(-12*ld(1)))*exp(-2*ld(1))"
          "+0.07*sin(2*PI*ld(2)*4*t)*gt(sin(2*PI*2.1333*t),0)")
AMBIENT = ("0.16*sin(2*PI*110*t)*(0.7+0.3*sin(2*PI*0.125*t))+0.12*sin(2*PI*164.81*t)*(0.7+0.3*sin(2*PI*0.1875*t+1))"
           "+0.1*sin(2*PI*220.5*t)*(0.6+0.4*sin(2*PI*0.0625*t+2))+0.06*sin(2*PI*329.63*t)*(0.5+0.5*sin(2*PI*0.25*t))")
MUSIC = [
    ("music_chill_01", "Chill: slow lo-fi bed with a soft kick (80 BPM)", 0.24, ev(CHILL, 12, "lowpass=f=3500")),
    ("music_energy_01", "Energy: driving electronic bed (128 BPM)", 0.2, ev(ENERGY, 7.5, "lowpass=f=6000")),
    ("music_ambient_01", "Ambient: calm pad without drums", 0.3, ev(AMBIENT, 16, "lowpass=f=2500")),
]


def make_vignette() -> None:
    """Black frame whose opacity grows towards the corners; the renderer and the preview both
    lay this same image over the picture, scaled by the vignette amount."""
    from PIL import Image

    w, h = 270, 480
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            r = (((x + 0.5) / w - 0.5) ** 2 + ((y + 0.5) / h - 0.5) ** 2) ** 0.5 / 0.7071
            a = max(0.0, min(1.0, (r - 0.35) / 0.65)) ** 1.6
            px[x, y] = (0, 0, 0, int(round(a * 255)))
    out = ROOT / "assets" / "studio" / "vignette.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    library = []
    for kind, items in (("sfx", SOUNDS), ("music", MUSIC)):
        for sound_id, description, gain, graph in items:
            path = OUT / f"{sound_id}.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", graph,
                            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(path)], check=True)
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                       capture_output=True, text=True, check=True).stdout.strip())
            library.append({"id": sound_id, "file": path.name, "kind": kind, "description": description,
                            "duration": round(dur, 2), "gain": gain, "license": LICENSE})
    manifest = OUT / "library.json"
    if manifest.exists():
        generated = {entry["id"] for entry in library}
        library.extend(entry for entry in json.loads(manifest.read_text(encoding="utf-8"))
                       if entry["id"] not in generated and (OUT / entry["file"]).is_file())
    manifest.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    make_vignette()
    print(f"{len(library)} sonidos en {OUT}")


if __name__ == "__main__":
    main()
